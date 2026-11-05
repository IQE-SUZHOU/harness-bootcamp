"""session 插件 —— 会话持久化（JSONL 消息流）。

对应 DSH `@dsh/session` + `session-persistence-jsonl` 的最小骨架：
  - 一个会话 = 一个 <dir>/<id>.jsonl，每行一条 API 形状的消息
    （user / assistant(+tool_calls) / tool），附 _ts 元字段
  - 重启后 list()/open() 可完整恢复上下文
  - 事件：session/message、session/created

供 agent-loop 写入、宿主 UI 读取；对模型不直接可见。
"""

import json
import os
import time
import uuid

from mini_cordis import Service


class Session:
    """单个会话句柄；append 即落盘（对齐 JSONL 追加式存储）。"""

    def __init__(self, service: 'SessionService', sid: str, path: str):
        self._svc = service
        self.id = sid
        self.path = path
        self.messages: list = []
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.messages.append(json.loads(line))

    def append(self, message: dict) -> dict:
        m = dict(message)
        m['_ts'] = time.time()
        self.messages.append(m)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(m, ensure_ascii=False) + '\n')
        self._svc.ctx.emit('session/message', self.id, m)
        return m

    def api_messages(self) -> list:
        """去掉 _ 元字段，得到可直接喂给 LLM API 的消息列表。"""
        return [{k: v for k, v in m.items() if not k.startswith('_')}
                for m in self.messages]


class SessionService(Service):
    provide = 'session'

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        cfg = config or {}
        self._dir = os.path.abspath(cfg.get('dir', './.sessions'))
        os.makedirs(self._dir, exist_ok=True)
        self._current = None

    # ------------------------------------------------------------ 会话管理

    def create(self, title: str = '') -> Session:
        sid = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
        sess = Session(self, sid, os.path.join(self._dir, f'{sid}.jsonl'))
        sess.title = title
        self._current = sess
        self.ctx.emit('session/created', sid)
        return sess

    def current(self) -> Session:
        if self._current is None:
            return self.create()          # 首次使用自动开会话
        return self._current

    def open(self, sid: str) -> Session:
        path = os.path.join(self._dir, f'{sid}.jsonl')
        if not os.path.exists(path):
            raise FileNotFoundError(f'session/not-found: {sid}')
        self._current = Session(self, sid, path)
        return self._current

    def list(self) -> list:
        out = []
        for name in sorted(os.listdir(self._dir)):
            if not name.endswith('.jsonl'):
                continue
            sid = name[:-6]
            with open(os.path.join(self._dir, name), encoding='utf-8') as f:
                count = sum(1 for line in f if line.strip())
            out.append({'id': sid, 'messages': count})
        return out


plugin = SessionService
