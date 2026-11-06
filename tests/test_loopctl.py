"""loopctl 验收：三道保险各管一段；taskboard maker 掐表集成。"""

import asyncio
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402
from run import prepare_profile  # noqa: E402


async def boot(tmp, overrides=()):
    eff = prepare_profile('d04', data_dir=str(tmp),
                          overrides=['llm.driver="fake"', *overrides])
    root = Context()
    await root.loader.load(str(eff))
    return root


class LoopCtlTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='loop-test-'))

    async def asyncTearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_exit_condition_first(self):
        root = await boot(self.tmp)
        try:
            seq = ['red', 'red', 'green']
            r = await root.get('loop').run(
                lambda i: seq[i], exit_when=lambda i, v: v == 'green',
                max_iters=10)
            assert r == {'completed': True, 'reason': 'exit-condition',
                         'iters': 3, 'result': 'green'}
        finally:
            await root.fiber.shutdown()

    async def test_max_iters_backstop(self):
        root = await boot(self.tmp)
        try:
            r = await root.get('loop').run(lambda i: 'red',
                                           exit_when=lambda i, v: v == 'green',
                                           max_iters=4)
            assert not r['completed'] and r['reason'] == 'max-iters'
            assert r['iters'] == 4
        finally:
            await root.fiber.shutdown()

    async def test_timeout_backstop(self):
        root = await boot(self.tmp)
        try:
            async def stuck(i):
                await asyncio.sleep(30)
            r = await root.get('loop').run(stuck, timeout_s=0.2, max_iters=100)
            assert not r['completed'] and r['reason'] == 'timeout'
        finally:
            await root.fiber.shutdown()

    async def test_step_error_is_visible(self):
        root = await boot(self.tmp)
        try:
            def boom(i):
                raise ValueError('第 1 轮就炸')
            r = await root.get('loop').run(boom, max_iters=5)
            assert not r['completed'] and r['reason'] == 'error'
            assert 'ValueError' in r['result'] and r['iters'] == 1
        finally:
            await root.fiber.shutdown()

    async def test_taskboard_maker_timeout(self):
        """day03 缺口闭环：maker 卡住有人掐表，超时计一次失败并走返工/升级轨道。"""
        root = await boot(self.tmp, overrides=['taskboard.maker_timeout_s=0.3'])
        try:
            tb = root.get('tasks')

            class Never:
                async def review(self, **kw):   # 不该被问到
                    raise AssertionError('unreachable')

            tb.checker = Never()
            calls = []

            async def stuck_maker(task, feedback, sess):
                calls.append(feedback)
                await asyncio.sleep(30)        # 永不返回

            t = tb.create('t', 'a')
            v = await tb.run(t['id'], stuck_maker)
            assert v['status'] == 'escalated' and v['attempts'] == 3
            assert '超时' in v['feedback']
            assert len(calls) == 3 and '超时' in (calls[1] or '')
            import json
            rows = [json.loads(l) for l in
                    (self.tmp / 'tasks' / 'ledger.jsonl').read_text().splitlines()]
            assert sum(1 for r in rows if r['event'] == 'maker-timeout') == 3
        finally:
            await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
