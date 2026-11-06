"""graph 验收：可解释路由（because 强制）、no_route 回带规则、失败可见、环路保护。"""

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


def ticket(g):
    g.node('classify', lambda d: d['kind'])
    g.edge('classify', 'bug', 'fix', because='报错走修复')
    g.edge('classify', '*', 'human', because='兜底转人工')
    g.node('fix', lambda d: 'fixed')
    g.node('human', lambda d: 'triaged')
    return g


class GraphTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='graph-test-'))

    async def asyncTearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_route_with_explainable_because(self):
        root = await boot(self.tmp)
        try:
            g = ticket(root.get('graph').define('t', entry='classify'))
            r = await g.run({'kind': 'bug'})
            assert r['outcome'] == 'done' and r['value'] == 'fixed'
            assert r['path'][0] == {'node': 'classify', 'key': 'bug',
                                    'to': 'fix', 'because': '报错走修复'}
        finally:
            await root.fiber.shutdown()

    async def test_edge_requires_because(self):
        root = await boot(self.tmp)
        try:
            g = root.get('graph').define('t2', entry='a')
            g.node('a', lambda d: 'x')
            g.node('b', lambda d: 'y')
            with self.assertRaises(ValueError):
                g.edge('a', 'x', 'b', because='   ')   # 说不清就不许存在
            with self.assertRaises(ValueError):
                g.edge('a', 'x', 'b')
        finally:
            await root.fiber.shutdown()

    async def test_no_route_returns_rules(self):
        root = await boot(self.tmp)
        try:
            g = root.get('graph').define('t3', entry='a')
            g.node('a', lambda d: 'weird')
            g.node('b', lambda d: 'y')
            g.edge('a', 'x', 'b', because='只有 x 走 b')
            r = await g.run({})
            assert r['outcome'] == 'no_route' and r['key'] == 'weird'
            assert any('只有 x 走 b' in s for s in r['rules'])   # 向人解释
        finally:
            await root.fiber.shutdown()

    async def test_node_failure_is_visible(self):
        root = await boot(self.tmp)
        try:
            def boom(_d):
                raise RuntimeError('上游 502')
            g = root.get('graph').define('t4', entry='fetch')
            ran = []
            g.node('fetch', boom)
            g.node('next', lambda d: ran.append(1))
            r = await g.run({})
            assert r['outcome'] == 'failed' and r['node'] == 'fetch'
            assert '502' in r['error'] and ran == []     # 下游没跑且结果非成功
        finally:
            await root.fiber.shutdown()

    async def test_loop_guard(self):
        root = await boot(self.tmp, overrides=['graph.max_steps=5'])
        try:
            g = root.get('graph').define('t5', entry='a')
            g.node('a', lambda d: 'go')
            g.node('b', lambda d: 'go')
            g.edge('a', 'go', 'b', because='绕圈')
            g.edge('b', 'go', 'a', because='绕圈')
            r = await g.run({})
            assert r['outcome'] == 'loop_guard' and 'max_steps' in r['error']
        finally:
            await root.fiber.shutdown()

    async def test_ledger_records_because(self):
        root = await boot(self.tmp)
        try:
            g = ticket(root.get('graph').define('t6', entry='classify'))
            await g.run({'kind': 'other'})              # 走通配兜底
            import json
            rows = [json.loads(l) for l in
                    (self.tmp / 'graphs' / 'graph.jsonl').read_text().splitlines()]
            hop = [r for r in rows if r['event'] == 'hop'][0]
            assert hop['because'] == '兜底转人工' and hop['to'] == 'human'
        finally:
            await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
