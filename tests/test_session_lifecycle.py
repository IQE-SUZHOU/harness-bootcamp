"""session 完整生命周期验收：创建 → 运行 → 中断 → 恢复 → 结束。"""

import asyncio
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402
from plugins.session import SessionClosed  # noqa: E402
from plugins.llm import FakeDriver  # noqa: E402
from run import prepare_profile  # noqa: E402


async def boot(tmp):
    eff = prepare_profile('base', data_dir=str(tmp), overrides=['llm.driver="fake"'])
    root = Context()
    await root.loader.load(str(eff))
    return root


def lines(path):
    out = []
    with open(path, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                out.append(json.loads(ln))   # 每行都必须是合法 JSON
    return out


class SessionLifecycleTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='life-test-'))

    async def asyncTearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------ 创建

    async def test_create_meta_and_list(self):
        root = await boot(self.tmp)
        try:
            sess = root.get('session')
            s = sess.create('我的会话')
            assert s.status == 'active'
            row = [x for x in sess.list() if x['id'] == s.id][0]
            assert row['status'] == 'active' and row['title'] == '我的会话'
            # 首行必须是出生 meta
            assert lines(s.path)[0]['_meta']['id'] == s.id
        finally:
            await root.fiber.shutdown()

    # ------------------------------------------------------------ 结束

    async def test_close_is_final_readonly(self):
        root = await boot(self.tmp)
        try:
            sess = root.get('session')
            s = sess.create()
            s.append({'role': 'user', 'content': 'hi'})
            s.close()
            assert s.status == 'closed'
            with self.assertRaises(SessionClosed):
                s.append({'role': 'user', 'content': 'again'})
            with self.assertRaises(SessionClosed):
                s.mark('active')
            row = [x for x in sess.list() if x['id'] == s.id][0]
            assert row['status'] == 'closed'
            # closed 会话对 agent 也拒写（显式传入）
            with self.assertRaises(SessionClosed):
                await root.get('agent').chat('hi', session=s)
        finally:
            await root.fiber.shutdown()

    # ------------------------------------------------------------ 中断+恢复

    async def test_crash_halfline_recovery(self):
        root = await boot(self.tmp)
        s = root.get('session').create()
        s.append({'role': 'user', 'content': 'q1'})
        s.append({'role': 'assistant', 'content': 'a1'})
        path = pathlib.Path(s.path)
        await root.fiber.shutdown()

        # 模拟崩溃：尾部追加半行截断 JSON
        with open(path, 'a', encoding='utf-8') as f:
            f.write('{"role":"assistant","con')

        root2 = await boot(self.tmp)
        try:
            s2 = root2.get('session').open(s.id)
            assert len(s2.messages) == 2                 # 半行被丢弃
            assert s2.status == 'interrupted'            # active 文件+无人持有=中断
            lines(path)                                  # 整文件已重写为合法 JSON
            assert path.read_text(encoding='utf-8').endswith('\n')
            s2.append({'role': 'user', 'content': 'resume'})
            assert s2.status == 'active'                 # 续聊自动复活
        finally:
            await root2.fiber.shutdown()

    async def test_dangling_tool_calls_repair(self):
        # 中断现场的典型形态：assistant 带 tool_calls，tool 响应没来得及写
        root = await boot(self.tmp)
        s = root.get('session').create()
        s.append({'role': 'user', 'content': 'run: x'})
        s.append({'role': 'assistant', 'content': None,
                  'tool_calls': [{'id': 'c9', 'type': 'function',
                                  'function': {'name': 'bash',
                                               'arguments': '{"command":"x"}'}}]})
        path = pathlib.Path(s.path)
        await root.fiber.shutdown()

        root2 = await boot(self.tmp)
        try:
            s2 = root2.get('session').open(s.id)
            assert s2.status == 'interrupted'
            roles = [m['role'] for m in s2.messages]
            assert roles == ['user', 'assistant', 'tool']
            synth = s2.messages[-1]
            assert synth['tool_call_id'] == 'c9' and synth['content'] == '[interrupted]'
            # API 合法性：每个 tool_calls id 都有对应 tool 响应
            api = s2.api_messages()
            have = {m.get('tool_call_id') for m in api if m['role'] == 'tool'}
            for m in api:
                for tc in (m.get('tool_calls') or []):
                    assert tc['id'] in have
            lines(path)                                  # 重写后文件行行合法
        finally:
            await root2.fiber.shutdown()

    async def test_interrupt_running_chat_then_resume(self):
        root = await boot(self.tmp)
        try:
            agent = root.get('agent')

            class SlowToolLLM:
                async def chat(self, messages, tools):
                    if messages[-1]['role'] == 'tool':
                        return {'role': 'assistant', 'content': 'done'}
                    return {'role': 'assistant', 'content': None,
                            'tool_calls': [{'id': 'slow1', 'type': 'function',
                                            'function': {'name': 'bash',
                                                         'arguments': json.dumps(
                                                             {'command': 'sleep 5'})}}]}

            agent.llm = SlowToolLLM()
            t = asyncio.ensure_future(agent.chat('跑个慢命令'))
            await asyncio.sleep(0.4)                     # 进入工具执行中
            assert agent.interrupt() is True
            r = await asyncio.wait_for(t, 3)             # 取消不打断返回协议
            assert r['interrupted'] is True
            sess = root.get('session').current()
            assert sess.status == 'interrupted'
            last = sess.messages[-1]                     # 半截工具调用被修补
            assert last['role'] == 'tool' and last['tool_call_id'] == 'slow1'
            assert last['content'] == '[已中断]'

            # 恢复：续聊自动回到 active，历史 API 合法
            agent.llm = FakeDriver()
            r2 = await agent.chat('run: echo resumed')
            assert 'resumed' in r2['final']
            assert sess.status == 'active'
        finally:
            await root.fiber.shutdown()

    async def test_llm_error_marks_interrupted(self):
        root = await boot(self.tmp)
        try:
            agent = root.get('agent')

            class BoomLLM:
                async def chat(self, messages, tools):
                    raise RuntimeError('llm down')

            agent.llm = BoomLLM()
            with self.assertRaises(RuntimeError):
                await agent.chat('hi')
            sess = root.get('session').current()
            assert sess.status == 'interrupted'
        finally:
            await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
