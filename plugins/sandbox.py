"""sandbox 插件 —— bash/文件操作的执行环境限制（策略层）。

对应 DSH sandbox 概念的最小实现（策略层，非内核隔离，限制见文末）：
  - 三种模式：read-only（拒绝一切命令）/ workspace-write（默认）/ full
  - 命令黑名单（可配置覆盖）：sudo、rm -rf /、mkfs、fork 炸弹……
  - cwd 钉在 workspace root 内（越界即拒）
  - 环境清洗：只保留 PATH/HOME 等白名单变量（防 token/密钥泄漏给子进程）
  - 超时强杀（杀整个进程组）、stdout/stderr 各自限量（头+尾保留）
  - 违规不发异常给模型：exec 返回 denied 结果，工具层转成可读文案
  - 事件：sandbox/violation、sandbox/exec

check_path() 为将来的文件工具预留：写必须落在 root 内。
"""

import asyncio
import os
import re
import signal
import time

from mini_cordis import Service

DEFAULT_DENY = [
    r'\bsudo\b',
    r'\brm\s+(-[a-zA-Z]+\s+)*/(\s|$|\*)',       # rm -rf /
    r'\bmkfs(\.|\s)',
    r'\bdd\b[^\n]*\bof=/dev/',
    r':\(\)\s*\{.*\}\s*;?\s*',                    # fork 炸弹
    r'\b(shutdown|reboot|poweroff|halt)\b',
    r'\bkill\s+-9\s+-?1\b',
    r'\bchmod\s+(-[a-zA-Z]+\s+)*777\s+/(\s|$)',
]

ENV_KEEP_DEFAULT = ['PATH', 'LANG', 'TERM']


class PolicyViolation(Exception):
    """命令/路径违反沙箱策略。"""


class Config:
    _MODES = ('read-only', 'workspace-write', 'full')

    @staticmethod
    def validate(raw):
        raw = raw or {}
        issues = []
        mode = raw.get('mode', 'workspace-write')
        if mode not in Config._MODES:
            issues.append({'message': f'mode must be one of {Config._MODES}', 'path': ['mode']})
        root = raw.get('root')
        if root is not None:
            if not isinstance(root, str) or not root:
                issues.append({'message': 'root must be a non-empty string', 'path': ['root']})
            elif os.path.exists(root) and not os.path.isdir(root):
                issues.append({'message': f'root exists but is not a directory: {root}',
                               'path': ['root']})
        # root 不存在时不报错：Sandbox 初始化会创建（workspace 自举）
        for k in ('timeout_s',):
            v = raw.get(k, 30)
            if not isinstance(v, (int, float)) or v <= 0:
                issues.append({'message': f'{k} must be a positive number', 'path': [k]})
        mo = raw.get('max_output', 32 * 1024)
        if not isinstance(mo, int) or mo < 16:
            issues.append({'message': 'max_output must be >= 16 bytes', 'path': ['max_output']})
        return {'value': {'mode': mode, 'root': root, 'timeout_s': v,
                          'max_output': mo, 'deny': raw.get('deny'),
                          'env': raw.get('env') or {}},
                'issues': issues or None}


def _truncate(text: str, cap: int):
    """头尾各留一半，中间打标记。返回 (text, truncated)。"""
    if len(text) <= cap:
        return text, False
    half = cap // 2
    return (text[:half]
            + f'\n... [已截断 {len(text) - cap} 字节] ...\n'
            + text[-half:]), True


class Sandbox(Service):
    provide = 'sandbox'
    Config = Config

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        cfg = config or {}
        self.mode = cfg.get('mode', 'workspace-write')
        self.root = os.path.realpath(cfg.get('root') or os.getcwd())
        self.timeout = cfg.get('timeout_s', 30)
        self.max_output = cfg.get('max_output', 32 * 1024)
        deny = cfg.get('deny') if cfg.get('deny') is not None else DEFAULT_DENY
        self._deny = [re.compile(p) for p in deny]
        self._env_extra = cfg.get('env') or {}
        os.makedirs(self.root, exist_ok=True)

    # ------------------------------------------------------------ 策略检查

    def check_command(self, command: str):
        if self.mode == 'read-only':
            raise PolicyViolation('沙箱为只读模式，禁止执行命令')
        for rx in self._deny:
            if rx.search(command):
                self.ctx.emit('sandbox/violation', command, f'黑名单命中: {rx.pattern}')
                raise PolicyViolation(f'命令被沙箱策略禁止（命中 {rx.pattern}）')

    def check_path(self, path: str, write: bool = False) -> str:
        """文件工具预留：解析路径；写模式要求落在 root 内。"""
        p = os.path.realpath(os.path.join(self.root, path))
        if write and self.mode == 'read-only':
            raise PolicyViolation('沙箱为只读模式，禁止写文件')
        if write and self.mode == 'workspace-write':
            if not (p == self.root or p.startswith(self.root + os.sep)):
                raise PolicyViolation(f'写路径越出 workspace: {p}')
        return p

    # ------------------------------------------------------------ 执行

    async def exec(self, command: str, cwd: str = None, timeout=None) -> dict:
        """执行命令。策略拒绝不抛异常，返回 {'denied': True, 'reason': ...}。"""
        try:
            self.check_command(command)
        except PolicyViolation as e:
            return {'denied': True, 'reason': str(e), 'command': command,
                    'stdout': '', 'stderr': '', 'exit_code': -1}

        work = os.path.realpath(os.path.join(self.root, cwd or '.'))
        if not (work == self.root or work.startswith(self.root + os.sep)):
            return {'denied': True, 'reason': f'cwd 越出 workspace: {work}',
                    'command': command, 'stdout': '', 'stderr': '', 'exit_code': -1}

        env = {k: os.environ[k] for k in ENV_KEEP_DEFAULT if k in os.environ}
        env.setdefault('PATH', '/usr/local/bin:/usr/bin:/bin')
        env['HOME'] = self.root          # HOME 收进 workspace，子进程写 ~ 也落在圈内
        env.update({k: str(v) for k, v in self._env_extra.items()})

        t0 = time.monotonic()
        timed_out = False
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work, env=env,
            start_new_session=True,      # 独立进程组，超时可整组击杀
        )
        try:
            raw_out, raw_err = await asyncio.wait_for(
                proc.communicate(), timeout or self.timeout)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            raw_out, raw_err = b'', b''
            await proc.wait()
        except asyncio.CancelledError:
            # agent 中断传导到进行中的工具：击杀子进程组后再上抛，不泄漏
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.wait()
            raise

        stdout, t1 = _truncate(raw_out.decode('utf-8', 'replace'), self.max_output)
        stderr, t2 = _truncate(raw_err.decode('utf-8', 'replace'), self.max_output)
        result = {
            'denied': False, 'command': command,
            'stdout': stdout, 'stderr': stderr,
            'exit_code': proc.returncode if not timed_out else -1,
            'timed_out': timed_out,
            'truncated': t1 or t2,
            'duration_s': round(time.monotonic() - t0, 3),
        }
        self.ctx.emit('sandbox/exec', command, result['exit_code'], result['duration_s'])
        return result


plugin = Sandbox
