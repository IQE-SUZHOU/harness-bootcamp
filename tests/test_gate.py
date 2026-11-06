"""gate 插件验收：规则拒绝、命令钩子、fail-closed、工具链集成。"""

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402
from run import prepare_profile  # noqa: E402


async def boot(tmp, overrides=()):
    eff = prepare_profile('d03', data_dir=str(tmp),
                          overrides=['llm.driver="fake"', *overrides])
    root = Context()
    await root.loader.load(str(eff))
    return root


class ToolCallStub:
    """第一轮发 bash tool_call，第二轮收尾。"""

    def __init__(self, command):
        self.command = command

    async def chat(self, messages, tools):
        if messages[-1]['role'] == 'tool':
            return {'role': 'assistant', 'content': 'done'}
        return {'role': 'assistant', 'content': None,
                'tool_calls': [{'id': 'g1', 'type': 'function',
                                'function': {'name': 'bash',
                                             'arguments':
                                                 f'{{"command": "{self.command}"}}'}}]}


class GateTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='gate-test-'))

    async def asyncTearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_deny_rule_blocks_tool_and_skips_execution(self):
        root = await boot(self.tmp)
        try:
            agent = root.get('agent')
            agent.llm = ToolCallStub('echo leak > prod.env')
            await agent.chat('写个 env')
            msgs = root.get('session').current().messages
            tool = [m for m in msgs if m['role'] == 'tool'][-1]
            assert '[gate 拒绝]' in tool['content'] and '.env' in tool['content']
            # 工具体没执行：文件不存在
            assert not (self.tmp / 'workspace' / 'prod.env').exists()
        finally:
            await root.fiber.shutdown()

    async def test_check_direct_match_and_pass(self):
        root = await boot(self.tmp)
        try:
            gate = root.get('gate')
            assert await gate.check('bash', {'command': 'cat /etc/app.env'})
            assert await gate.check('bash', {'command': 'chmod +x evil.sh'})
            assert await gate.check('bash', {'command': 'ls'}) is None
        finally:
            await root.fiber.shutdown()

    async def test_hook_pass_and_deny(self):
        ok_hook = '[{"name": "eyes", "command": "cat >/dev/null"}]'
        root = await boot(self.tmp, overrides=[f'gate.hooks={ok_hook}'])
        try:
            assert await root.get('gate').check('bash', {'command': 'ls'}) is None
        finally:
            await root.fiber.shutdown()

        deny_hook = '[{"name": "judge", "command": "echo why-not >&2; exit 3"}]'
        root2 = await boot(self.tmp / 'b', overrides=[f'gate.hooks={deny_hook}'])
        try:
            reason = await root2.get('gate').check('bash', {'command': 'ls'})
            assert reason and 'judge' in reason and 'why-not' in reason
        finally:
            await root2.fiber.shutdown()

    async def test_hook_failure_fail_closed(self):
        broken = '[{"name": "ghost", "command": "/nonexistent/xyz"}]'
        root = await boot(self.tmp, overrides=[f'gate.hooks={broken}'])
        try:
            reason = await root.get('gate').check('bash', {'command': 'ls'})
            assert reason and 'fail-closed' in reason   # 命令坏了 = 拒绝，不是放行
        finally:
            await root.fiber.shutdown()

    async def test_no_gate_tools_still_run(self):
        """回归：没装 gate 的 profile，before-call 链为空，工具照常执行。"""
        eff = prepare_profile('base', data_dir=str(self.tmp),
                              overrides=['llm.driver="fake"'])
        root = Context()
        await root.loader.load(str(eff))
        try:
            agent = root.get('agent')
            agent.llm = ToolCallStub('echo hello-gate-off')
            await agent.chat('说你好')
            tool = [m for m in root.get('session').current().messages
                    if m['role'] == 'tool'][-1]
            assert 'hello-gate-off' in tool['content'] and '拒绝' not in tool['content']
        finally:
            await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
