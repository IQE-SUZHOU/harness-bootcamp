"""session 插件 v2 —— 完整会话生命周期：创建 → 运行 → 中断 → 恢复 → 结束。

状态模型（追加式日志里"最后一条 meta 为准"，保持 append-only）：

    文件首行 {"_meta":{id,title,status,created_at,updated_at}}
    之后消息行逐条追加；状态变化再追加一条 meta 行

    status ∈ active | interrupted | closed
      create() ──→ active ──chat/append──→ active
      崩溃/取消 ──(恢复时识别)──→ interrupted ──open()+续聊──→ active
      close()  ──→ closed（终态，append 抛 SessionClosed）

恢复语义（open 时自动执行）：
  1. 尾部半行（崩溃截断）→ 丢弃并计数
  2. 文件末状态 active（但没人持有它）→ 判定为 interrupted
  3. dangling tool_calls（assistant 带调用、tool 响应缺失）→ 补合成
     {"role":"tool","content":"[interrupted]"}，保证消息序列对
     OpenAI 兼容 API 永远合法；有修复时整文件原子重写（tempfile+replace）

生命周期图即本文件 docstring；事件：session/created、session/message、
session/status、session/closed、session/recovered。
"""

import json
import os
import time
import uuid

from mini_cordis import Service
from plugins.session_types import SessionClosed    # 共享类型模块，见该文件 docstring

__all__ = ['Session', 'SessionService', 'SessionClosed']


def _now():
    return time.time()


class Session:
    """单个会话句柄。messages 只含消息行（meta 单独存 self.meta）。"""

    def __init__(self, service: 'SessionService', sid: str, path: str):
        self._svc = service
        self.id = sid
        self.path = path
        self.messages: list = []
        self.meta: dict = {}

    # ------------------------------------------------------------ 状态

    @property
    def status(self) -> str:
        return self.meta.get('status', 'active')

    @property
    def title(self) -> str:
        return self.meta.get('title', '')

    def mark(self, status: str):
        """状态迁移：追加一条 meta 行（append-only 日志的更新方式）。"""
        if self.status == 'closed':
            raise SessionClosed(f'session/closed: {self.id}')
        self.meta['status'] = status
        self.meta['updated_at'] = _now()
        self._append_line({'_meta': dict(self.meta)})
        self._svc.ctx.emit('session/status', self.id, status)

    def close(self):
        """结束：写终结标记，此后只读。"""
        if self.status != 'closed':
            self.meta['updated_at'] = _now()
            self.meta['status'] = 'closed'
            self._append_line({'_meta': dict(self.meta)})
            self._svc.ctx.emit('session/status', self.id, 'closed')
            self._svc.ctx.emit('session/closed', self.id)

    # ------------------------------------------------------------ 读写

    def append(self, message: dict) -> dict:
        if self.status == 'closed':
            raise SessionClosed(f'session/closed: {self.id}')
        m = dict(message)
        m['_ts'] = _now()
        self.messages.append(m)
        if self.status == 'interrupted':
            self.meta['status'] = 'active'      # 续聊自动回到 active
            self.meta['updated_at'] = _now()
            self._append_line({'_meta': dict(self.meta)})
            self._svc.ctx.emit('session/status', self.id, 'active')
        self._append_line(m)
        self._svc.ctx.emit('session/message', self.id, m)
        return m

    def api_messages(self) -> list:
        """去掉 _ 元字段，可直接喂 LLM API。"""
        return [{k: v for k, v in m.items() if not k.startswith('_')}
                for m in self.messages]

    # ------------------------------------------------------------ 修复

    def patch_dangling(self, reason: str = '[interrupted]') -> bool:
        """协议修复：assistant.tool_calls 的每个 id 必须有对应 tool 响应，
        缺失的按调用顺序补合成响应。返回是否发生了修复。"""
        have = {m.get('tool_call_id') for m in self.messages if m.get('role') == 'tool'}
        out, need = [], False
        for m in self.messages:
            out.append(m)
            for tc in (m.get('tool_calls') or []):
                cid = tc.get('id')
                if cid not in have:
                    out.append({'role': 'tool', 'tool_call_id': cid,
                                'content': reason, '_ts': _now()})
                    need = True
        if need:
            self.messages = out
        return need

    # ------------------------------------------------------------ 底层 IO

    def _append_line(self, obj):
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(obj, ensure_ascii=False) + '\n')


class SessionService(Service):
    provide = 'session'

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        cfg = config or {}
        self._dir = os.path.abspath(cfg.get('dir', './.sessions'))
        os.makedirs(self._dir, exist_ok=True)
        self._current = None

    # ------------------------------------------------------------ 管理

    def create(self, title: str = '') -> Session:
        sid = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
        sess = Session(self, sid, os.path.join(self._dir, f'{sid}.jsonl'))
        sess.meta = {'id': sid, 'title': title, 'status': 'active',
                     'created_at': _now(), 'updated_at': _now()}
        sess._append_line({'_meta': dict(sess.meta)})   # 首行 = 出生记录
        self._current = sess
        self.ctx.emit('session/created', sid)
        return sess

    def current(self) -> Session:
        if self._current is None:
            return self.create()
        return self._current

    def peek(self):
        """当前会话，不自动创建（UI/状态查询用）。"""
        return self._current

    def attach(self, sess: Session):
        """显式指认当前会话（agent.chat(session=...) 用）。"""
        self._current = sess

    def open(self, sid: str) -> Session:
        """恢复：读取 + 半行截尾 + active→interrupted 判定 + dangling 修补。"""
        path = os.path.join(self._dir, f'{sid}.jsonl')
        if not os.path.exists(path):
            raise FileNotFoundError(f'session/not-found: {sid}')
        sess = Session(self, sid, path)
        dropped = 0
        with open(path, encoding='utf-8') as f:
            raw = f.read()
        tail_ok = raw.endswith('\n') or raw == ''
        lines = [ln for ln in raw.split('\n') if ln != '']
        if not tail_ok and lines:
            dropped += 1
            lines.pop()                      # 崩溃截断的半行
        for i, ln in enumerate(lines):
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                dropped += 1
                continue
            if '_meta' in obj:
                sess.meta = obj['_meta']     # 最后一条 meta 为准
            else:
                sess.messages.append(obj)
        repaired = dropped > 0
        if sess.meta.get('status') == 'active':
            sess.meta['status'] = 'interrupted'   # 文件说活着但无人持有 = 中断
            repaired = True
        if not sess.meta:
            sess.meta = {'id': sid, 'title': '', 'status': 'interrupted',
                         'created_at': os.path.getmtime(path), 'updated_at': _now()}
        if sess.patch_dangling():
            repaired = True
        if repaired:
            self._rewrite(sess)
        self._current = sess
        self.ctx.emit('session/recovered', sid, repaired)
        return sess

    def close(self, sid: str):
        sess = self.current() if self._current and self._current.id == sid \
            else self.open(sid)
        sess.close()

    def list(self) -> list:
        out = []
        for name in sorted(os.listdir(self._dir)):
            if not name.endswith('.jsonl'):
                continue
            meta, count = {}, 0
            with open(os.path.join(self._dir, name), encoding='utf-8') as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        obj = json.loads(ln)
                    except json.JSONDecodeError:
                        continue
                    if '_meta' in obj:
                        meta = obj['_meta']
                    else:
                        count += 1
            out.append({'id': name[:-6], 'title': meta.get('title', ''),
                        'status': meta.get('status', 'interrupted'),
                        'messages': count,
                        'updated_at': meta.get('updated_at',
                                               os.path.getmtime(
                                                   os.path.join(self._dir, name)))})
        return out

    def _rewrite(self, sess: Session):
        """修复后的整文件原子重写（tempfile + os.replace）。"""
        tmp = sess.path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(json.dumps({'_meta': dict(sess.meta)}, ensure_ascii=False) + '\n')
            for m in sess.messages:
                f.write(json.dumps(m, ensure_ascii=False) + '\n')
        os.replace(tmp, sess.path)


plugin = SessionService
