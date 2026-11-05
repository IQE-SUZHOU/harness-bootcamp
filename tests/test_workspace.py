"""workspace 插件验收测试：持久化、并发串行化、损坏状态隔离。"""

import asyncio
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context, ValidationError  # noqa: E402
from plugins.workspace import WorkspaceRegistry  # noqa: E402


class WorkspacePluginTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='ws-test-'))
        (self.tmp / 'proj-a').mkdir()
        (self.tmp / 'proj-b').mkdir()
        self.store = self.tmp / 'ws.json'

    async def _registry(self):
        root = Context()
        fiber = root.plugin(WorkspaceRegistry, {'file': str(self.store)})
        await fiber
        return root, root.get('workspace_registry')

    async def test_persistence_roundtrip(self):
        root, reg = await self._registry()
        p1 = await reg.create(self.tmp / 'proj-a', title='A')
        await p1.attach_session('s1')
        await p1.attach_session('s2')
        await p1.insert_session_before('s2', 's1')
        await reg.archive_session('s2')
        await root.fiber.shutdown()

        root2, reg2 = await self._registry()
        ws = reg2.list()
        assert len(ws) == 1 and ws[0].title == 'A'
        assert ws[0].sessions == ['s2', 's1']
        assert reg2.is_hidden('s2')
        assert reg2.workspace_of('s1').id == p1.id
        await root2.fiber.shutdown()

    async def test_create_is_idempotent_by_path(self):
        root, reg = await self._registry()
        a = await reg.create(self.tmp / 'proj-a')
        b = await reg.create(self.tmp / str(self.tmp / 'proj-a' / '.'))  # 非规范路径
        assert a.id == b.id
        assert len(reg.list()) == 1
        await root.fiber.shutdown()

    async def test_concurrent_mutations_serialized(self):
        root, reg = await self._registry()
        p = await reg.create(self.tmp / 'proj-b')
        await asyncio.gather(*(p.attach_session(f's{i}') for i in range(20)))
        assert sorted(p.sessions) == sorted(f's{i}' for i in range(20))
        # 磁盘状态始终合法
        data = json.loads(self.store.read_text(encoding='utf-8'))
        assert len(data['workspaces'][0]['sessions']) == 20
        await root.fiber.shutdown()

    async def test_corrupted_store_isolated_as_failed(self):
        self.store.write_text('{"workspaces": "not-a-list"}', encoding='utf-8')
        root = Context()
        fiber = root.plugin(WorkspaceRegistry, {'file': str(self.store)})
        with self.assertRaises(ValidationError):
            await fiber
        assert fiber.state == 3  # FAILED：坏插件不拖垮宿主
        await root.fiber.shutdown()

    async def test_delete_project_keeps_sessions(self):
        root, reg = await self._registry()
        p = await reg.create(self.tmp / 'proj-a')
        await p.attach_session('keep-me')
        await reg.delete(p.id)
        assert reg.get(p.id) is None
        assert 'keep-me' in reg.ungrouped_sessions()
        await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
