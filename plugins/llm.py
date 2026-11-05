"""llm 插件 —— LLM 接入服务，直接消费本机 DSH 的 LLM 配置。

配置来源（优先级从高到低）：
  1. 插件 config 显式指定 {provider, model}
  2. ~/.dsh/settings.yaml 的 `agent-default-model`（provider + model）——
     即"本机 DSH 当前用的模型"，provider 定义在同文件 `llm-pi-ai.providers`：
       api: openai-completions / baseURL / headers(Authorization) / models[]
  3. 环境变量 OPENAI_API_KEY / OPENAI_BASE_URL（通用 OpenAI 兼容兜底）
  4. 以上皆无 → fake 驱动（离线演示不断链）

设计要点：
  - YAML 用手写子集解析器（缩进/映射/列表/标量），保持 mini_cordis 零依赖
  - API key 只驻内存，任何日志与 list_providers() 均做掩码
  - 对外契约：await ctx.llm.chat(messages, tools=None) → response message dict
    （{'role','content','tool_calls'?}），与 OpenAI chat/completions 一致
  - 驱动实现从 agent_loop 抽出：agent-loop 只依赖 ctx.llm，不再关心后端
"""

import asyncio
import json
import os
import urllib.error
import urllib.request

from mini_cordis import Service


class LLMError(Exception):
    pass


# ------------------------------------------------------- 零依赖 YAML 子集解析

def _coerce(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
        return v[1:-1]
    low = v.lower()
    if low in ('true', 'yes'):
        return True
    if low in ('false', 'no'):
        return False
    if low in ('null', '~', ''):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def parse_yaml_subset(text: str):
    """解析 DSH settings.yaml 用到的 YAML 子集：嵌套映射、
    ("- key: value" 映射列表、"- scalar" 标量列表)、内联标量。
    按首个 ': ' 分列，URL(http://x) 中的冒号不带空格故安全。"""
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(raw) - len(raw.lstrip(' '))
        lines.append((indent, stripped))

    def parse_block(i: int, indent: int):
        """返回 (value, next_i)。行 indent >= 参数 indent 属于本块。"""
        # 判断本块是列表还是映射
        if i < len(lines) and lines[i][1].startswith('- '):
            out_list = []
            while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith('- '):
                content = lines[i][1][2:]
                sub_indent = indent + 2
                if ':' in content and not content.startswith('"'):
                    # 列表项是映射：首键内联，后续键行缩进 >= sub_indent
                    item = {}
                    k, _, v = content.partition(':')
                    item[k.strip()] = _coerce(v) if v.strip() else None
                    i += 1
                    kids, i = _collect(i, sub_indent)
                    item.update(kids)
                    out_list.append(item)
                else:
                    out_list.append(_coerce(content))
                    i += 1
            return out_list, i
        return _collect(i, indent)

    def _collect(i: int, indent: int):
        out = {}
        while i < len(lines) and lines[i][0] == indent:
            content = lines[i][1]
            if content.startswith('- '):
                break
            if ': ' not in content and not content.endswith(':'):
                raise ValueError(f'yaml parse: bad line {content!r}')
            k, _, v = content.partition(':')
            k, v = k.strip(), v.strip()
            if v:
                out[k] = _coerce(v)
                i += 1
            else:
                # 子块：看下一行缩进
                if i + 1 < len(lines) and lines[i + 1][0] > indent:
                    child_indent = lines[i + 1][0]
                    out[k], i = parse_block(i + 1, child_indent)
                else:
                    out[k] = None
                    i += 1
        while i < len(lines) and lines[i][0] > indent:  # 收尾更深缩进
            break
        return out, i

    value, _ = parse_block(0, lines[0][0] if lines else 0)
    return value


# --------------------------------------------------------------- LLM 驱动

class OpenAICompatDriver:
    """OpenAI 兼容 chat/completions（stdlib urllib）。headers 整包透传，
    DSH 的 Authorization: Bearer xxx 直接生效。"""

    def __init__(self, base_url: str, headers: dict, model: str,
                 temperature=0.2, timeout=180, name=''):
        self.base_url = base_url.rstrip('/')
        self.headers = dict(headers or {})
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.name = name

    async def chat(self, messages, tools=None):
        payload = {'model': self.model, 'messages': messages,
                   'temperature': self.temperature}
        if tools:
            payload['tools'] = tools

        def _post():
            req = urllib.request.Request(
                f'{self.base_url}/chat/completions',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json', **self.headers},
                method='POST')
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))

        try:
            data = await asyncio.to_thread(_post)
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', 'replace')[:400]
            raise LLMError(f'LLM HTTP {e.code}: {body}') from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LLMError(f'LLM unreachable ({self.base_url}): {e}') from e
        try:
            return data['choices'][0]['message']
        except (KeyError, IndexError) as e:
            raise LLMError(f'LLM bad response: {json.dumps(data, ensure_ascii=False)[:400]}') from e


class FakeDriver:
    """离线确定性驱动（保留原 agent_loop 内置行为）：
    "run:/执行:/bash:" 触发 bash 工具调用；tool 结果 → 总结；其它 → 直接回复。"""

    def __init__(self):
        self._n = 0

    async def chat(self, messages, tools=None):
        last = messages[-1]
        if last['role'] == 'tool':
            return {'role': 'assistant',
                    'content': '(fake) 命令已执行。输出摘要：\n' + last['content'][:300]}
        text = last.get('content') or ''
        import re
        m = re.search(r'(?:run|执行|bash)\s*[:：]\s*(.+)', text, re.S)
        if m and any(t['function']['name'] == 'bash' for t in (tools or [])):
            self._n += 1
            return {'role': 'assistant', 'content': None, 'tool_calls': [{
                'id': f'call_{self._n}', 'type': 'function',
                'function': {'name': 'bash',
                             'arguments': json.dumps({'command': m.group(1).strip()},
                                                     ensure_ascii=False)}}]}
        return {'role': 'assistant',
                'content': f'(fake) 收到：{text[:80]}。想要执行命令请用 "run: <命令>"。'}


# --------------------------------------------------------------- 服务

def _mask(secret: str) -> str:
    if not secret:
        return '(none)'
    return secret[:4] + '***' if len(secret) > 8 else '***'


class LLM(Service):
    provide = 'llm'

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        cfg = config or {}
        self.log = ctx.logger('llm')
        driver = cfg.get('driver', 'auto')   # auto | dsh | openai | fake
        self.info = {'driver': None}

        if driver == 'fake':
            self._driver, self.info['driver'] = FakeDriver(), 'fake'
            return

        if driver in ('auto', 'dsh'):
            built = self._build_from_dsh(cfg)
            if built is not None:
                self._driver, self.info['driver'] = built, 'dsh'
                return
            if driver == 'dsh':
                raise LLMError('driver=dsh 但无法从 DSH 配置解析出可用 provider')

        built = self._build_from_env(cfg)     # 通用 OpenAI 兼容兜底
        if built is not None:
            self._driver, self.info['driver'] = built, 'openai'
            return

        self.log.warn('无可用 LLM 配置（DSH settings / OPENAI_API_KEY 均缺），使用 fake 驱动')
        self._driver, self.info['driver'] = FakeDriver(), 'fake'

    # ---------------------------------------------------- 解析 DSH settings

    def _build_from_dsh(self, cfg):
        path = os.path.expanduser(
            cfg.get('settings') or os.environ.get('DSH_SETTINGS')
            or '~/.dsh/settings.yaml')
        if not os.path.exists(path):
            self.log.debug('DSH settings 不存在: %s', path)
            return None
        try:
            with open(path, encoding='utf-8') as f:
                settings = parse_yaml_subset(f.read())
        except Exception as e:  # noqa: BLE001 —— 配置坏了应降级而非炸插件
            self.log.error('解析 %s 失败: %s', path, e)
            return None
        providers = ((settings.get('llm-pi-ai') or {}).get('providers')) or {}
        default = settings.get('agent-default-model') or {}
        pid = cfg.get('provider') or default.get('provider')
        model = cfg.get('model')
        if not pid and len(providers) == 1:
            pid = next(iter(providers))       # 只有一个 provider 时免配置
        if not pid or pid not in providers:
            self.log.warn('provider %r 不在 %s 的 llm-pi-ai.providers 中', pid, path)
            return None
        p = providers[pid]
        api = p.get('api', 'openai-completions')
        if api != 'openai-completions':
            self.log.warn('provider %s api=%s 暂不支持（仅 openai-completions）', pid, api)
            return None
        # model 解析：显式 config > agent-default-model（仅当 provider 也是默认）> 该 provider 首模型
        if not model:
            if pid == default.get('provider'):
                model = default.get('model')
            model = model or ((p.get('models') or [{}])[0]).get('id')
        driver = OpenAICompatDriver(
            base_url=p['baseURL'], headers=p.get('headers') or {},
            model=model, temperature=cfg.get('temperature', 0.2),
            timeout=cfg.get('timeout_s', 180), name=pid)
        self.info.update({'provider': pid, 'model': model,
                          'baseURL': p['baseURL'],
                          'auth': _mask((p.get('headers') or {})
                                        .get('Authorization', '').replace('Bearer ', ''))})
        self.log.info('driver=dsh provider=%s model=%s baseURL=%s auth=%s',
                      pid, model, p['baseURL'], self.info['auth'])
        return driver

    def _build_from_env(self, cfg):
        key_env = cfg.get('api_key_env', 'OPENAI_API_KEY')
        api_key = os.environ.get(key_env, '')
        base_url = cfg.get('base_url') or os.environ.get('OPENAI_BASE_URL', '')
        if not api_key and not base_url:
            return None
        driver = OpenAICompatDriver(
            base_url=base_url or 'https://api.openai.com/v1',
            headers={'Authorization': f'Bearer {api_key}'} if api_key else {},
            model=cfg.get('model', 'gpt-4o-mini'),
            temperature=cfg.get('temperature', 0.2), name='env')
        self.info.update({'model': driver.model, 'baseURL': driver.base_url,
                          'auth': _mask(api_key)})
        self.log.info('driver=openai(env) baseURL=%s model=%s auth=%s',
                      driver.base_url, driver.model, self.info['auth'])
        return driver

    # ---------------------------------------------------- 对外 API

    def list_providers(self) -> list:
        """列出 DSH settings 里的 providers（密钥掩码）。"""
        path = os.path.expanduser(os.environ.get('DSH_SETTINGS') or '~/.dsh/settings.yaml')
        if not os.path.exists(path):
            return []
        with open(path, encoding='utf-8') as f:
            providers = ((parse_yaml_subset(f.read()).get('llm-pi-ai')
                          or {}).get('providers')) or {}
        out = []
        for pid, p in providers.items():
            out.append({'id': pid, 'displayName': p.get('displayName'),
                        'baseURL': p.get('baseURL'),
                        'models': [m.get('id') for m in (p.get('models') or [])]})
        return out

    async def chat(self, messages, tools=None):
        return await self._driver.chat(messages, tools)

    async def ping(self) -> dict:
        """连通性自测：一句极短对话。"""
        msg = await self.chat([{'role': 'user', 'content': 'ping'}], tools=None)
        return {'ok': True, 'reply': (msg.get('content') or '')[:80]}


plugin = LLM
