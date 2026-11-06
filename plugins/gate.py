"""gate 插件 —— 验证门禁（对标 DSH：hooks 外部命令 + permission/approval + fail-closed）。

DSH 的门禁共同点：**不通过 = 不放行，且一切不确定都按不通过**（approval 缺失=拒、
auto-review 含糊=拒、沙箱命中=拒）。本插件把这套语义装进工具调用链：

  agent_loop 的 ToolRegistry.call 在真正执行工具前，走事件 `tool/before-call`
  的 serial 链（mini_cordis 的 bail 语义：第一个非 None 返回值即为否决）。

三层检查（任一命中即拒绝，拒绝文案喂回模型、进会话）：
  1. deny 规则：正则匹配 "工具名 + JSON 参数"（对应 sandbox 之外的策略层）
  2. 命令钩子（对应 DSH hooks/）：外部命令拿 $GATE_TOOL 与 stdin 里的 JSON 参数，
     exit 0 = 放行；非 0 = 拒绝（stderr 尾部作为理由回给模型）
  3. **fail-closed**：钩子命令不存在 / 超时 / 解析异常 → 一律拒绝
     （门禁自己坏了不允许"默认放行"——这是 DSH 所有 gate 的统一形状）

用法：
  - 装到 profile 即自动拦在工具链上（本插件 inject ['tools']，加载序在 tools 之后）
  - 也可直接调用 await ctx.gate.check(name, args) → None=放行 / str=拒绝文案
配置：{'deny': [正则...], 'hooks': [{'name': str, 'command': str, 'timeout_s': 10}]}
"""

import asyncio
import json
import re

from mini_cordis import Service

inject = ['tools']


class Gate(Service):
    provide = 'gate'

    class Config:
        @staticmethod
        def validate(raw):
            """standard-schema：返回 {'value', 'issues'}（见 mini_cordis.resolve_config）。"""
            raw = raw or {}
            issues = []
            deny = raw.get('deny', [])
            if not isinstance(deny, list) or not all(isinstance(p, str) for p in deny):
                issues.append({'message': 'deny 必须是字符串（正则）列表', 'path': ['deny']})
                deny = []
            else:
                for p in deny:
                    try:
                        re.compile(p)
                    except re.error as e:
                        issues.append({'message': f'非法正则 {p!r}: {e}', 'path': ['deny']})
            hooks = raw.get('hooks', [])
            if not isinstance(hooks, list) or not all(
                    isinstance(h, dict) and h.get('name') and h.get('command')
                    for h in hooks):
                issues.append({'message': 'hooks 每项需含 name/command', 'path': ['hooks']})
                hooks = []
            if issues:
                return {'issues': issues}
            return {'value': {'deny': [re.compile(p) for p in deny],
                              'hooks': hooks,
                              'fail_closed': bool(raw.get('fail_closed', True))},
                    'issues': []}

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        self.config = config or {}      # fiber 已按 Config.validate 归一
        self._log = ctx.logger('gate')
        self._off = ctx.on('tool/before-call', self._listener)

    # ------------------------------------------------------------ 核心判定

    async def check(self, name: str, arguments: dict):
        """None=放行；返回 str=拒绝文案。fail-closed：自身异常也是拒绝。"""
        try:
            blob = f'{name} {json.dumps(arguments, ensure_ascii=False)}'
            for pat in self.config['deny']:
                if pat.search(blob):
                    self._log.info('deny %r ← 规则 /%s/', blob[:80], pat.pattern)
                    return f'命中门禁规则 /{pat.pattern}/'
            for hook in self.config['hooks']:
                reason = await self._run_hook(hook, name, arguments)
                if reason is not None:
                    return reason
            return None
        except Exception as e:  # noqa: BLE001 —— 门禁自身故障必须按拒绝处理
            if self.config['fail_closed']:
                return f'门禁自身异常（fail-closed 拒绝）：{type(e).__name__}: {e}'
            return None

    async def _run_hook(self, hook, name, arguments):
        """外部命令钩子（DSH hooks 的最小形状）：0 放行，非 0 拒绝。"""
        try:
            proc = await asyncio.create_subprocess_shell(
                hook['command'],
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={'PATH': '/usr/bin:/bin'},
            )
            payload = json.dumps({'tool': name, 'arguments': arguments},
                                 ensure_ascii=False).encode()
            try:
                _out, err = await asyncio.wait_for(
                    proc.communicate(payload), hook.get('timeout_s', 10))
            except (TimeoutError, asyncio.TimeoutError):
                proc.kill()
                await proc.wait()
                return f"钩子 {hook['name']} 超时（fail-closed 拒绝）"
            if proc.returncode == 127:
                # 命令不存在 = 门禁自身坏了，不是业务拒绝 —— 仍拒绝，但语义不同
                if self.config['fail_closed']:
                    return f"钩子 {hook['name']} 无法执行（fail-closed 拒绝）：命令未找到"
                return None
            if proc.returncode != 0:
                why = (err or b'').decode('utf-8', 'replace').strip()[-200:]
                return f"钩子 {hook['name']} 判定不通过(exit {proc.returncode})：{why or '无原因'}"
            return None
        except Exception as e:  # noqa: BLE001
            # 命令不存在等：fail_closed 时拒绝；显式关掉则放行
            if self.config['fail_closed']:
                return f"钩子 {hook['name']} 无法执行（fail-closed 拒绝）：{e}"
            return None

    # ------------------------------------------------------------ 事件挂点

    async def _listener(self, name, arguments):
        return await self.check(name, arguments)

plugin = Gate          # loader 入口（三件套约定）
