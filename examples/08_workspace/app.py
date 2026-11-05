"""
08_workspace —— 在 mini_cordis 之上装配 workspace 插件

演示插件生态能力（对应 DSH packages/workspace 的核心语义子集）：
  - loader 按 JSON 配置装配有状态、带持久化后端的插件
  - 命名有序项目 + 项目内有序会话 + 隐藏（归档）≠ 删除
  - 删除项目绝不删除会话：会话回落为"未分组"历史
  - 重启进程（新 Context）后状态从磁盘完整恢复

运行：python3 examples/08_workspace/app.py
"""

import asyncio
import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402

HERE = pathlib.Path(__file__).parent


async def phase(tmp: pathlib.Path):
    """第一阶段：装配插件、建项目/会话、排序、隐藏、删项目。"""
    root = Context()
    log = root.logger('08a')
    seen_events = []
    for name in ('workspace/created', 'workspace/deleted',
                 'workspace/session-attached', 'workspace/session-detached'):
        root.on(name, lambda *a, _n=name: seen_events.append((_n, *a)))

    await root.loader.load(str(tmp / 'app.json'))
    reg = root.get('workspace_registry')

    p1 = await reg.create(tmp / 'proj-alpha', title='阿尔法')
    p2 = await reg.create(tmp / 'proj-beta')
    assert reg.resolve_by_path(str(tmp / 'proj-alpha')) is not None
    again = await reg.create(tmp / 'proj-alpha')           # 按路径幂等
    assert again.id == p1.id and len(reg.list()) == 2

    await p1.attach_session('s-1')
    await p1.attach_session('s-2')
    await p1.attach_session('s-3')
    await p1.insert_session_before('s-3', 's-1')          # 顺序变 s-3, s-1, s-2
    await p2.attach_session('s-9')
    await p1.set_title('阿尔法（改名）')
    await reg.archive_session('s-2')                       # 隐藏，不删除

    assert p1.sessions == ['s-3', 's-1', 's-2']
    visible = dict((ws.id, vis) for ws, vis in reg.visible_projects())
    assert visible[p1.id] == ['s-3', 's-1'], visible       # 隐藏会话不出现在 UI 视图

    await reg.delete(p2.id)                                # 删项目
    assert reg.get(p2.id) is None
    assert 's-9' in reg.ungrouped_sessions()               # 但会话仍在（未分组）

    p3 = await reg.create(tmp / 'proj-gamma')
    await reg.insert_before(p3.id, p1.id)                  # gamma 排到 alpha 之前
    assert [w.id for w in reg.list()] == [p3.id, p1.id]
    await reg.delete(p3.id)

    await root.fiber.shutdown()
    log.info('第一阶段完成，事件流=%s ✓', [e[0].split('/')[1] for e in seen_events])
    return seen_events


async def phase2(tmp: pathlib.Path):
    """第二阶段：全新进程式重启，从磁盘恢复并验证。"""
    root = Context()
    log = root.logger('08b')
    await root.loader.load(str(tmp / 'app.json'))
    reg = root.get('workspace_registry')

    ws = reg.list()
    assert len(ws) == 1 and ws[0].title == '阿尔法（改名）'
    assert ws[0].sessions == ['s-3', 's-1', 's-2']         # 顺序持久化
    assert reg.is_hidden('s-2') and not reg.is_hidden('s-3')  # 隐藏状态持久化
    assert 's-9' in reg.ungrouped_sessions()                # 未分组历史持久化
    assert reg.workspace_of('s-3').id == ws[0].id

    # 取消隐藏后重新可见
    await reg.unarchive_session('s-2')
    vis = dict((w.id, v) for w, v in reg.visible_projects())
    assert vis[ws[0].id] == ['s-3', 's-1', 's-2']
    log.info('重启后状态完整恢复 ✓')
    await root.fiber.shutdown()


async def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='mini-ws-'))
    try:
        (tmp / 'proj-alpha').mkdir()
        (tmp / 'proj-beta').mkdir()
        (tmp / 'app.json').write_text(json.dumps([{
            'id': 'workspace',
            'module': str(ROOT / 'plugins' / 'workspace.py'),
            'config': {'file': str(tmp / 'workspaces.json')},
        }]), encoding='utf-8')

        await phase(tmp)
        await phase2(tmp)
        print('workspace 插件演示全部通过 ✓')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    asyncio.run(main())
