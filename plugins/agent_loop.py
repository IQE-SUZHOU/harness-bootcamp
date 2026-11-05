"""agent-loop 插件 —— LLM 会话循环 + 工具注册表。

对应 DSH agent-loop 概念的最小实现：
  - ToolRegistry（provide='tools'）：工具带 OpenAI function schema，bash 等插件来注册
  - LLM 驱动两种：
      openai —— OpenAI 兼容 /chat/completions（urllib，零依赖，支持 tool_calls）
      fake   —— 离线确定性驱动："run: <命令>" 触发 bash 工具调用，随后总结输出；
                没有 API key 也能把整条 loop 跑通
  - Agent（provide='agent'）.chat()：
      session 取历史 → 调 LLM → 有 tool_calls 就逐个执行、结果回写会话 → 循环
      直到纯文本回复或 max_turns 熔断；全程写 session、发事件
  - 事件：agent/turn-started、agent/tool、agent/finished
"""

import asyncio
import json
import os
import re
import urllib.error
import urllib.request

from mini_cordis import Service

DEFAULT_SYSTEM = (
    '你是 mini-harness 代理。工作目录位于沙箱内的 workspace。'
    '需要执行命令时使用 bash 工具；回答保持简洁。'
)


class LLMError(Exception):
    pass


# --------------------------------------------------------------- 工具注册表

class ToolRegistry(Service):
    """provide='tools'：name → (schema, handler)。"""

    provide = 'tools'

    def __init__(self, ctx):
        super().__init__(ctx)
        self._tools = {}

    def register(self, name: str, description: str, parameters: dict, handler):
        self._tools[name] = {'schema': {
            'type': 'function',
            'function': {'name': name, 'description': description,
                         'parameters': parameters},
        }, 'handler': handler}
        self.ctx.logger('tools').info('registered tool: %s', name)

    def names(self):
        return list(self._tools)

    def schemas(self):
        return [t['schema'] for t in self._tools.values()]

    async def call(self, name: str, arguments: dict) -> str:
        """工具异常不打断循环，转成错误文案喂回模型（对齐 harness 行为）。"""
        t = self._tools.get(name)
        if t is None:
            return f'Error: unknown tool "{name}"'
        try:
            result = t['handler'](arguments)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result)
        except Exception as e:  # noqa: BLE001 —— 工具错误是给模型看的数据
            return f'Error: {type(e).__name__}: {e}'


# --------------------------------------------------------------- LLM 驱动

class OpenAILLM:
    """OpenAI 兼容 chat/completions 客户端（stdlib urllib，零依赖）。"""

    def __init__(self, base_url, api_key, model, temperature=0.2, timeout=120):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    async def chat(self, messages, tools):
        payload = {'model': self.model, 'messages': messages,
                   'temperature': self.temperature}
        if tools:
            payload['tools'] = tools

        def _post():
            req = urllib.request.Request(
                f'{self.base_url}/chat/completions',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json',
                         'Authorization': f'Bearer {self.api_key}'},
                method='POST')
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))

        try:
            data = await asyncio.to_thread(_post)
        except urllib.error.HTTPError as e:
            raise LLMError(f'LLM HTTP {e.code}: {e.read().decode("utf-8", "replace")[:400]}'
                           ) from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(f'LLM unreachable: {e}') from e
        try:
            return data['choices'][0]['message']
        except (KeyError, IndexError) as e:
            raise LLMError(f'LLM bad response: {json.dumps(data)[:400]}') from e


class FakeLLM:
    """离线确定性驱动：无需网络即可演示完整 agent 循环。

    规则：
      - 用户消息含 "run:/执行:/bash:" → 发起 bash 工具调用
      - 收到 tool 结果 → 总结输出
      - 其它 → 直接文本回复
    """

    def __init__(self):
        self._n = 0

    async def chat(self, messages, tools):
        last = messages[-1]
        if last['role'] == 'tool':
            return {'role': 'assistant',
                    'content': '(fake) 命令已执行。输出摘要：\n' + last['content'][:300]}
        text = last.get('content') or ''
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


# --------------------------------------------------------------- Agent 循环

class Agent(Service):
    provide = 'agent'
    inject = ['session']

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        cfg = config or {}
        self.max_turns = cfg.get('max_turns', 8)
        self.system = cfg.get('system', DEFAULT_SYSTEM)
        self.tools = ToolRegistry(ctx)          # provide='tools'
        self.llm = self._build_llm(cfg.get('llm') or {})

    def _build_llm(self, llm_cfg):
        driver = llm_cfg.get('driver', 'auto')
        key_env = llm_cfg.get('api_key_env', 'OPENAI_API_KEY')
        api_key = os.environ.get(key_env, '')
        base_url = (llm_cfg.get('base_url')
                    or os.environ.get('OPENAI_BASE_URL')
                    or 'https://api.openai.com/v1')
        if driver == 'fake' or (driver == 'auto' and not api_key):
            if driver == 'auto':
                self.ctx.logger('agent').warn(
                    '%s 未设置，使用 fake LLM 驱动（离线演示模式）', key_env)
            return FakeLLM()
        model = llm_cfg.get('model') or 'gpt-4o-mini'
        self.ctx.logger('agent').info('openai driver: %s (%s)', base_url, model)
        return OpenAILLM(base_url, api_key, model,
                         temperature=llm_cfg.get('temperature', 0.2))

    async def chat(self, user_msg: str = None) -> dict:
        """一轮用户输入 → 若干工具往返 → 最终文本。全程持久化到 session。"""
        sess = self.ctx.session.current()
        if user_msg is not None:
            sess.append({'role': 'user', 'content': user_msg})
        self.ctx.emit('agent/turn-started', sess.id)

        turns = 0
        while turns < self.max_turns:
            turns += 1
            messages = ([{'role': 'system', 'content': self.system}]
                        + sess.api_messages())
            resp = await self.llm.chat(messages, self.tools.schemas())

            tool_calls = resp.get('tool_calls')
            if tool_calls:
                # 助手消息（含 tool_calls）先入会话，保持 API 因果序
                sess.append({'role': resp.get('role', 'assistant'),
                             'content': resp.get('content'),
                             'tool_calls': tool_calls})
                for tc in tool_calls:
                    fn = tc.get('function', {})
                    try:
                        args = json.loads(fn.get('arguments') or '{}')
                    except json.JSONDecodeError:
                        args = {}
                    result = await self.tools.call(fn.get('name', ''), args)
                    sess.append({'role': 'tool', 'tool_call_id': tc.get('id'),
                                 'content': result})
                    self.ctx.emit('agent/tool', sess.id, fn.get('name'), tc.get('id'))
                continue

            content = resp.get('content') or ''
            sess.append({'role': 'assistant', 'content': content})
            self.ctx.emit('agent/finished', sess.id, turns)
            return {'final': content, 'turns': turns, 'aborted': False}

        msg = f'[aborted] 达到 max_turns={self.max_turns}，循环熔断'
        sess.append({'role': 'assistant', 'content': msg})
        self.ctx.emit('agent/finished', sess.id, turns)
        return {'final': msg, 'turns': turns, 'aborted': True}


plugin = Agent
