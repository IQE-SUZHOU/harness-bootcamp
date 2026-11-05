"""mini-harness 四插件（session/sandbox/agent-loop/bash）验收测试。"""

import asyncio
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402


async def boot(tmp: pathlib.Path, sandbox_cfg=None, agent_cfg=None):
    """按 loader 方式装配四插件（与真实部署同路径）。"""
    workspace = tmp / 'workspace'
    workspace.mkdir(exist_ok=True)
    cfg = [
        {'id': 'session', 'module': str(ROOT / 'plugins' / 'session.py'),
         'config': {'dir': str(tmp / 'sessions')}},
        {'id': 'sandbox', 'module': str(ROOT / 'plugins' / 'sandbox.py'),
         'config': sandbox_cfg or {'root': str(workspace), 'timeout_s': 10}},
        {'id': 'agent-loop', 'module': str(ROOT / 'plugins' / 'agent_loop.py'),
         'config': agent_cfg or {'llm': {'driver': 'fake'}}},
        {'id': 'bash', 'module': str(ROOT / 'plugins' / 'bash.py'), 'config': {}},
    ]
    path = tmp / 'app.json'
    path.write_text(json.dumps(cfg), encoding='utf-8')
    root = Context()
    await root.loader.load(str(path))
    return root


class MiniHarnessTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='mh-test-'))

    async def asyncTearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------ 全链路

    async def test_chat_tool_roundtrip(self):
        root = await boot(self.tmp)
        try:
            r = await root.get('agent').chat('run: echo mh-ok')
            assert 'mh-ok' in r['final'] and not r['aborted'] and r['turns'] == 2
            msgs = root.get('session').current().messages
            roles = [m['role'] for m in msgs]
            assert roles == ['user', 'assistant', 'tool', 'assistant']
            assert msgs[1]['tool_calls'][0]['function']['name'] == 'bash'
            assert msgs[2]['tool_call_id'] == msgs[1]['tool_calls'][0]['id']
        finally:
            await root.fiber.shutdown()

    async def test_session_persistence_across_restart(self):
        root = await boot(self.tmp)
        await root.get('agent').chat('run: echo persisted')
        sess = root.get('session').current()
        sid, count = sess.id, len(sess.messages)
        jsonl = pathlib.Path(sess.path)
        await root.fiber.shutdown()
        assert jsonl.exists() and count == 4

        root2 = await boot(self.tmp)
        try:
            s2 = root2.get('session').open(sid)
            assert len(s2.messages) == count
            # 续聊：历史在上下文中继续增长
            await root2.get('agent').chat('run: echo more')
            assert len(s2.messages) == count + 4
        finally:
            await root2.fiber.shutdown()

    # ------------------------------------------------------------ sandbox

    async def test_sandbox_readonly_denies(self):
        root = await boot(self.tmp, sandbox_cfg={
            'root': str(self.tmp / 'ws1'), 'mode': 'read-only'})
        try:
            r = await root.get('agent').chat('run: echo should-not-run')
            assert '拒绝' in r['final'] and 'should-not-run' not in r['final']
            res = await root.get('sandbox').exec('echo x')
            assert res['denied'] is True
        finally:
            await root.fiber.shutdown()

    async def test_sandbox_denylist(self):
        root = await boot(self.tmp)
        sb = root.get('sandbox')
        try:
            for bad in ('sudo whoami', 'rm -rf /', 'mkfs.ext4 /dev/sda',
                        ':(){ :|:& };:', 'shutdown now'):
                r = await sb.exec(bad)
                assert r['denied'] is True, bad
            ok = await sb.exec('rm -rf ./build && echo fine')   # 合法删除不误伤
            assert not ok['denied'] and 'fine' in ok['stdout']
        finally:
            await root.fiber.shutdown()

    async def test_sandbox_timeout_kills_process_group(self):
        root = await boot(self.tmp)
        t0 = time.monotonic()
        r = await root.get('sandbox').exec('sleep 30', timeout=1)
        assert r['timed_out'] is True and time.monotonic() - t0 < 4
        await root.fiber.shutdown()

    async def test_sandbox_output_truncation(self):
        root = await boot(self.tmp, sandbox_cfg={
            'root': str(self.tmp / 'ws2'), 'max_output': 256})
        r = await root.get('sandbox').exec('seq 1 20000')
        assert r['truncated'] is True and len(r['stdout']) < 600
        assert '已截断' in r['stdout']
        await root.fiber.shutdown()

    async def test_sandbox_env_scrubbed(self):
        os.environ['MH_SECRET_TOKEN'] = 'sekret'
        root = await boot(self.tmp)
        try:
            r = await root.get('sandbox').exec('echo "[$MH_SECRET_TOKEN]"; command -v bash')
            assert 'sekret' not in r['stdout']
            assert '/bash' in r['stdout']          # PATH 保留可用
        finally:
            del os.environ['MH_SECRET_TOKEN']
            await root.fiber.shutdown()

    async def test_sandbox_cwd_escape_denied(self):
        root = await boot(self.tmp)
        r = await root.get('sandbox').exec('pwd', cwd='../../etc')
        assert r['denied'] is True
        await root.fiber.shutdown()

    async def test_sandbox_write_stays_in_workspace(self):
        root = await boot(self.tmp)
        sb = root.get('sandbox')
        try:
            r = await sb.exec('echo data > out.txt')
            assert not r['denied']
            assert (sb.root + '/out.txt') and pathlib.Path(sb.root, 'out.txt').exists()
            with self.assertRaises(Exception):
                sb.check_path('/etc/passwd', write=True)
            sb.check_path('./notes/a.md', write=True)  # root 内合法
        finally:
            await root.fiber.shutdown()

    # ------------------------------------------------------------ agent-loop

    async def test_max_turns_breaker(self):
        root = await boot(self.tmp, agent_cfg={'max_turns': 3, 'llm': {'driver': 'fake'}})
        try:

            class AlwaysCall:
                def __init__(self):
                    self.n = 0

                async def chat(self, messages, tools):
                    self.n += 1
                    return {'role': 'assistant', 'content': None, 'tool_calls': [{
                        'id': f'c{self.n}', 'type': 'function',
                        'function': {'name': 'bash',
                                     'arguments': json.dumps({'command': 'true'})}}]}

            root.get('agent').llm = AlwaysCall()
            r = await root.get('agent').chat('run: true')
            assert r['aborted'] is True and r['turns'] == 3
        finally:
            await root.fiber.shutdown()

    async def test_unknown_tool_and_bad_json_are_text(self):
        root = await boot(self.tmp)
        try:
            tools = root.get('tools')
            assert 'unknown tool' in await tools.call('nope', {})
            # 非法 arguments JSON 不炸循环：按空参调用
            agent = root.get('agent')

            class BadArgs:
                async def chat(self, messages, tools):
                    last = messages[-1]
                    if last['role'] == 'tool':
                        return {'role': 'assistant', 'content': 'done'}
                    fn = {'name': 'bash', 'arguments': "{not json"}
                    tc = {'id': 'x', 'type': 'function', 'function': fn}
                    return {'role': 'assistant', 'content': None, 'tool_calls': [tc]}

            agent.llm = BadArgs()
            r = await agent.chat('hi')
            assert r['final'] == 'done'
            tool_msg = root.get('session').current().messages[2]['content']
            assert '缺少' in tool_msg or 'Error' in tool_msg
        finally:
            await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
