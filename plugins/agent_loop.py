"""agent-loop 插件 —— LLM 会话循环 + 工具注册表。

对应 DSH agent-loop 概念的最小实现：
  - ToolRegistry（provide='tools'）：工具带 OpenAI function schema，bash 等插件来注册
  - LLM 接入解耦到独立 llm 插件（provide='llm'）：本插件只依赖 ctx.llm 的
    chat(messages, tools) → message dict 契约；测试可给 agent.llm 换假驱动
  - Agent（provide='agent'）.chat()：
      session 取历史 → 调 LLM → 有 tool_calls 就逐个执行、结果回写会话 → 循环
      直到纯文本回复或 max_turns 熔断；全程写 session、发事件
  - 事件：agent/turn-started、agent/tool、agent/finished
"""

import asyncio
import json

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


# --------------------------------------------------------------- Agent 循环

class Agent(Service):
    provide = 'agent'
    inject = ['session', 'llm']

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        cfg = config or {}
        self.max_turns = cfg.get('max_turns', 8)
        self.system = cfg.get('system', DEFAULT_SYSTEM)
        self.tools = ToolRegistry(ctx)          # provide='tools'
        self.llm = ctx.llm                      # 契约：chat(messages, tools)→message
        # 测试 seam：可直接给实例赋假驱动覆盖 self.llm

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
