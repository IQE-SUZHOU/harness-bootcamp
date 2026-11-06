"""full profile（交付形态）验收：全家桶装配、instructions 文件注入、缺文件不 crash。"""

import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402
from run import prepare_profile  # noqa: E402


async def boot(tmp, overrides=()):
    eff = prepare_profile('full', data_dir=str(tmp),
                          overrides=['llm.driver="fake"', 'webui.port=0',
                                     *overrides])
    root = Context()
    await root.loader.load(str(eff))
    return root


class FullHarnessTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='full-test-'))

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_all_services_assembled(self):
        """可用 harness 的装配审计：五天的件必须全在一条真实装配路径上。"""
        root = await boot(self.tmp)
        try:
            for pid in ('session', 'sandbox', 'llm', 'tools', 'agent',
                        'gate', 'checker', 'tasks', 'loop', 'graph',
                        'fanout', 'webui'):
                assert root.get(pid) is not None, f'缺服务 {pid}'
        finally:
            await root.fiber.shutdown()

    async def test_instructions_file_injected(self):
        inj = self.tmp / 'INSTR.md'
        inj.write_text('你是被说明书约束的 agent。坑位口令：BLUE-42',
                       encoding='utf-8')
        root = await boot(self.tmp,
                          overrides=[f'agent-loop.instructions_file="{inj}"'])
        try:
            seen = {}

            class Spy:
                async def chat(self, messages, tools=None):
                    seen['system'] = messages[0]
                    return {'role': 'assistant', 'content': 'ok'}

            root.get('agent').llm = Spy()
            await root.get('agent').chat('hi')
            assert seen['system']['role'] == 'system'
            assert 'BLUE-42' in seen['system']['content']   # 文件内容进 system
            assert 'instructions:' in seen['system']['content']  # 且标明出处
        finally:
            await root.fiber.shutdown()

    async def test_missing_instructions_does_not_crash(self):
        """如实告警而不是 crash——可用 harness 不因说明书缺失罢工。"""
        root = await boot(self.tmp,
                          overrides=['agent-loop.instructions_file="nope.md"'])
        try:
            assert root.get('agent') is not None
            assert 'BLUE-42' not in root.get('agent').system
        finally:
            await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
