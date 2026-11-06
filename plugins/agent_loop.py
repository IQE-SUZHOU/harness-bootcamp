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
        """工具异常不打断循环，转成错误文案喂回模型（对齐 harness 行为）。

        执行前先走 `tool/before-call` serial 门禁链（gate 插件挂这里）：
        任一监听器返回非 None = 拒绝，工具体不执行；门禁链自身异常也按
        拒绝处理（fail-closed，对齐 DSH approval/auto-review）。
        """
        t = self._tools.get(name)
        if t is None:
            return f'Error: unknown tool "{name}"'
        try:
            verdict = await self.ctx.serial('tool/before-call', name, arguments)
        except Exception as e:  # noqa: BLE001 —— 门禁坏了不许默认放行
            return f'[gate 拒绝] 门禁链异常（fail-closed）：{type(e).__name__}: {e}'
        if verdict is not None:
            return f'[gate 拒绝] {verdict}'
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
        # instructions（day05 查漏）：行为约定放文件而不是塞配置——对齐 DSH
        # superagent 的 prompts/*.md 思路（"团队用语言描述的行为是提示词，不是设置"）。
        # 启动时读取并拼进 system；文件缺失如实告警，不 crash。
        f = cfg.get('instructions_file')
        if f:
            import pathlib
            p = pathlib.Path(f)
            if p.is_file():
                self.system += f'\n\n--- instructions: {p} ---\n' + \
                    p.read_text(encoding='utf-8')
                ctx.logger('agent').info('instructions 注入：%s (%d 字)',
                                         p, p.stat().st_size)
            else:
                ctx.logger('agent').warn('instructions_file 不存在：%s（忽略）', p)
        self.tools = ToolRegistry(ctx)          # provide='tools'
        self.llm = ctx.llm                      # 契约：chat(messages, tools)→message
        # 测试 seam：可直接给实例赋假驱动覆盖 self.llm
        self._task = None

    async def chat(self, user_msg: str = None, session=None) -> dict:
        """一轮用户输入 → 若干工具往返 → 最终文本。全程持久化到 session。

        session 显式传入 Session 对象；缺省用 ctx.session.current()。
        循环跑在独立 task 中，agent.interrupt() 可安全中止：
        内层捕获 CancelledError → 落 interrupted 标记 + 修补 dangling tool_calls。
        """
        if self._task is not None and not self._task.done():
            raise RuntimeError('agent: 上一轮尚未结束，先 interrupt() 或等待完成')
        if session is not None:
            self.ctx.session.attach(session)
        task = asyncio.ensure_future(self._chat_inner(user_msg))
        self._task = task
        try:
            return await task
        finally:
            self._task = None

    def interrupt(self) -> bool:
        """中断进行中的一轮对话；返回是否确有任务被取消。"""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            return True
        return False

    async def _chat_inner(self, user_msg) -> dict:
        sess = self.ctx.session.current()
        turns = 0
        try:
            if user_msg is not None:
                sess.append({'role': 'user', 'content': user_msg})
            self.ctx.emit('agent/turn-started', sess.id)

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
        except asyncio.CancelledError:
            # 中断不是错误：安全收尾后以正常结果返回，调用方拿到 interrupted
            self._mark_interrupted(sess, '[已中断]')
            self.ctx.emit('agent/interrupted', sess.id)
            return {'final': '[已中断]', 'turns': turns, 'aborted': False,
                    'interrupted': True}
        except Exception:
            # LLM 故障等：同样落中断标记 + 修补，异常继续上抛给调用方
            self._mark_interrupted(sess, '[执行失败]')
            raise

    @staticmethod
    def _mark_interrupted(sess, reason: str):
        try:
            sess.patch_dangling(reason)
            if sess.status != 'closed':
                sess.mark('interrupted')
        except Exception:  # noqa: BLE001 —— 收尾尽力而为，不掩盖原始异常
            pass


plugin = Agent
