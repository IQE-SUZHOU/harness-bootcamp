"""workspace 插件 —— DSH `@dsh/workspace`（ctx.workspaceRegistry）的最小移植。

对应 dsh_back/packages/workspace/workspace 的核心语义子集：
  - 命名且有序的项目（workspace）列表：create / list / insert_before / delete
  - 项目内有序会话：attach_session / detach_session / insert_session_before / set_title
  - 隐藏（归档）会话：archive_session / unarchive_session —— 隐藏 ≠ 删除
  - 删除项目绝不删除会话记录（会话回落为"未分组"）
  - mutate 串行化（对齐 DSH 的 enqueueOperation）+ JSON 文件持久化（原子替换）
  - 加载失败隔离：损坏的状态文件 → 校验失败 → 插件 FAILED 而非带病运行

有意省略：会话存储/会话头校验（session storage headers）、跨进程锁、
WorkspaceId 品牌类型、invariant 错误族。

用法（loader 装配）：
  {"id": "workspace", "module": "<abs>/plugins/workspace.py",
   "config": {"file": "<abs>/workspaces.json"}}
之后任意注入 'workspace_registry' 的插件可用 ctx.workspace_registry。
"""

import json
import os
import tempfile

from mini_cordis import Service, ValidationError


class Config:
    """配置校验器（standard-schema 风格）。"""

    @staticmethod
    def validate(raw):
        raw = raw or {}
        issues = []
        file = raw.get('file', 'workspaces.json')
        if not isinstance(file, str) or not file:
            issues.append({'message': 'file must be a non-empty string', 'path': ['file']})
        return {'value': {'file': file}, 'issues': issues or None}


class Workspace:
    """项目实体（对齐 DSH WorkspaceEntity：持 host/id/record，改动走宿主串行通道）。"""

    def __init__(self, registry: 'WorkspaceRegistry', id: str, record: dict):
        self._registry = registry
        self.id = id
        self._record = record

    @property
    def path(self):
        return self._record['path']

    @property
    def title(self):
        return self._record['title']

    @property
    def sessions(self):
        return list(self._record['sessions'])

    async def set_title(self, title: str):
        def op(_state):
            self._record['title'] = title
            return title
        return await self._registry._mutate(op)

    async def attach_session(self, session_id: str):
        def op(state):
            if session_id not in self._record['sessions']:
                self._record['sessions'].append(session_id)
            if session_id in state['hidden']:            # 重新入组即取消隐藏
                state['hidden'] = [s for s in state['hidden'] if s != session_id]
            self._registry._known.add(session_id)
        await self._registry._mutate(op)
        self._registry.ctx.emit('workspace/session-attached', self.id, session_id)

    async def detach_session(self, session_id: str):
        def op(_):
            if session_id in self._record['sessions']:
                self._record['sessions'].remove(session_id)
        await self._registry._mutate(op)
        self._registry.ctx.emit('workspace/session-detached', self.id, session_id)

    async def insert_session_before(self, session_id: str, before_id):
        def op(_):
            ss = self._record['sessions']
            if session_id in ss:
                ss.remove(session_id)
            i = ss.index(before_id) if before_id in ss else len(ss)
            ss.insert(i, session_id)
        await self._registry._mutate(op)

    def __repr__(self):
        return f'Workspace({self.id!r} {self.title!r} sessions={self.sessions})'


class WorkspaceRegistry(Service):
    """ctx.workspace_registry —— 命名有序项目 + 按目录归组的会话。"""

    provide = 'workspace_registry'
    Config = Config

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        self._file = (config or {}).get('file', 'workspaces.json')
        self._state = {'next_id': 1, 'workspaces': [], 'hidden': []}
        self._known: set = set()
        self._mutating = None  # asyncio.Lock，延迟到首次 mutate 创建（绑定运行循环）
        if os.path.exists(self._file):
            with open(self._file, encoding='utf-8') as f:
                loaded = json.load(f)
            self._state = self._validate_stored(loaded)
            for ws in self._state['workspaces']:
                self._known.update(ws['sessions'])
            self._known.update(self._state['hidden'])
            self._known.update(loaded.get('known') or [])

    # ------------------------------------------------------------ 查询

    def list(self):
        return [Workspace(self, r['id'], r) for r in self._state['workspaces']]

    def get(self, workspace_id: str):
        for r in self._state['workspaces']:
            if r['id'] == workspace_id:
                return Workspace(self, r['id'], r)
        return None

    def resolve_by_path(self, path: str):
        canonical = os.path.realpath(path)
        for r in self._state['workspaces']:
            if r['path'] == canonical:
                return Workspace(self, r['id'], r)
        return None

    def is_hidden(self, session_id: str) -> bool:
        return session_id in self._state['hidden']

    def workspace_of(self, session_id: str):
        for r in self._state['workspaces']:
            if session_id in r['sessions']:
                return Workspace(self, r['id'], r)
        return None

    def ungrouped_sessions(self):
        """未分组历史：已知但不在任何项目中（隐藏与否都算，DSH 语义：隐藏会话仍可用）。"""
        in_projects = {s for r in self._state['workspaces'] for s in r['sessions']}
        return sorted(self._known - in_projects)

    def visible_projects(self, session_id_filter=None):
        """UI 视图：隐藏会话从项目列表中过滤掉。"""
        out = []
        for ws in self.list():
            vis = [s for s in ws.sessions if s not in self._state['hidden']]
            out.append((ws, vis))
        return out

    # ------------------------------------------------------------ 变更（串行）

    async def create(self, path: str, title=None):
        canonical = os.path.realpath(path)
        existing = self.resolve_by_path(canonical)
        if existing is not None:
            return existing  # DSH 幂等语义：按路径解析到既有项目

        def op(state):
            wid = f"w{state['next_id']}"
            state['next_id'] += 1
            state['workspaces'].append({
                'id': wid, 'path': canonical,
                'title': title or os.path.basename(canonical.rstrip('/')) or canonical,
                'sessions': [],
            })
            return wid
        wid = await self._mutate(op)
        ws = self.get(wid)
        self.ctx.emit('workspace/created', wid, canonical)
        return ws

    async def delete(self, workspace_id: str) -> bool:
        """删除项目：绝不删除会话（回落为未分组历史）。"""
        def op(state):
            before = len(state['workspaces'])
            state['workspaces'] = [r for r in state['workspaces'] if r['id'] != workspace_id]
            return len(state['workspaces']) < before
        removed = await self._mutate(op)
        if removed:
            self.ctx.emit('workspace/deleted', workspace_id)
        return removed

    async def insert_before(self, workspace_id: str, before_id):
        def op(state):
            ws = state['workspaces']
            r = next((x for x in ws if x['id'] == workspace_id), None)
            if r is None:
                raise ValueError(f'workspace/not-found: {workspace_id}')
            ws.remove(r)
            i = next((i for i, x in enumerate(ws) if x['id'] == before_id), len(ws))
            ws.insert(i, r)
        await self._mutate(op)

    async def archive_session(self, session_id: str):
        """隐藏（不删除）：UI 不再展示，仍可作为未分组历史使用。"""
        self._known.add(session_id)

        def op(state):
            state['hidden'] = sorted(set(state['hidden']) | {session_id})
        await self._mutate(op)

    async def unarchive_session(self, session_id: str):
        def op(state):
            state['hidden'] = [s for s in state['hidden'] if s != session_id]
        await self._mutate(op)

    # ------------------------------------------------------------ 持久化内核

    async def _mutate(self, fn):
        import asyncio
        if self._mutating is None:
            self._mutating = asyncio.Lock()
        async with self._mutating:
            result = fn(self._state)
            self._save()
            return result

    def _save(self):
        payload = {
            'next_id': self._state['next_id'],
            'workspaces': self._state['workspaces'],
            'hidden': sorted(self._state['hidden']),
            'known': sorted(self._known),
        }
        d = os.path.dirname(os.path.abspath(self._file))
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._file)   # 原子替换，避免半写状态
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _validate_stored(state):
        if not isinstance(state, dict) or not isinstance(state.get('workspaces'), list):
            raise ValidationError('workspace store: corrupted state')
        for r in state['workspaces']:
            if not all(k in r for k in ('id', 'path', 'title', 'sessions')) \
                    or not isinstance(r['sessions'], list):
                raise ValidationError(f'workspace store: bad record {r!r}')
        return {
            'next_id': int(state.get('next_id', len(state['workspaces']) + 1)),
            'workspaces': state['workspaces'],
            'hidden': list(state.get('hidden', [])),
        }


plugin = WorkspaceRegistry  # 约定：模块暴露 plugin
