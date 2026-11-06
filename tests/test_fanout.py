"""fanout 验收：全成/部分/全败三态、分支失败与超时可见、汇合器炸留现场、并发有界。"""

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


class FanOutTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='fan-test-'))

    async def asyncTearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_all_ok(self):
        root = await boot(self.tmp)
        try:
            r = await root.get('fanout').scatter([1, 2, 3], lambda i: i * 10)
            assert r['outcome'] == 'ok' and r['merged'] == [10, 20, 30]
            assert r['counts'] == {'ok': 3, 'failed': 0}
        finally:
            await root.fiber.shutdown()

    async def test_partial_failure_visible_to_fanin(self):
        root = await boot(self.tmp)
        try:
            def w(i):
                if i == 2:
                    raise ValueError('双数不行')
                return i
            seen = {}

            def reducer(results):
                seen['statuses'] = [(r['ok'], r.get('error')) for r in results]
                return [r['value'] for r in results if r['ok']]

            r = await root.get('fanout').scatter([1, 2, 3], w, reduce=reducer)
            assert r['outcome'] == 'partial'              # 绝不报成功
            assert any(e and '双数不行' in e for _ok, e in seen['statuses'])
            assert r['merged'] == [1, 3] and r['counts']['failed'] == 1
        finally:
            await root.fiber.shutdown()

    async def test_branch_timeout_visible(self):
        root = await boot(self.tmp)
        try:
            async def w(i):
                if i == 1:
                    await asyncio.sleep(30)
                return i
            r = await root.get('fanout').scatter([0, 1], w, timeout_s=0.2)
            assert r['outcome'] == 'partial'
            assert 'timeout' in r['results'][1]['error']
        finally:
            await root.fiber.shutdown()

    async def test_all_failed_is_failed_not_ok(self):
        root = await boot(self.tmp)
        try:
            def w(i):
                raise RuntimeError('全炸')
            r = await root.get('fanout').scatter([1, 2], w)
            assert r['outcome'] == 'failed' and r['counts']['ok'] == 0
            assert all('全炸' in x['error'] for x in r['results'])
        finally:
            await root.fiber.shutdown()

    async def test_reducer_error_keeps_evidence(self):
        root = await boot(self.tmp)
        try:
            def bad_reducer(results):
                raise KeyError('reduce 自己炸了')
            r = await root.get('fanout').scatter([1], lambda i: i,
                                                 reduce=bad_reducer)
            assert r['outcome'] == 'reduce_error'
            assert 'reduce 自己炸了' in r['error']
            assert r['results'][0]['ok'] is True          # 原始分支结果原样保留
        finally:
            await root.fiber.shutdown()

    async def test_concurrency_bounded(self):
        root = await boot(self.tmp, overrides=['fanout.max_parallel=2'])
        try:
            cur = {'n': 0, 'peak': 0}

            async def w(i):
                cur['n'] += 1
                cur['peak'] = max(cur['peak'], cur['n'])
                await asyncio.sleep(0.05)
                cur['n'] -= 1
                return i
            await root.get('fanout').scatter(list(range(6)), w)
            assert cur['peak'] <= 2
        finally:
            await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
