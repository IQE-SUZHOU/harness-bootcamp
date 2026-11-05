"""插件：KV 存储核心服务。

演示：
  - Service 子类 + 构造参数（config 由 loader 传入）
  - 类属性 Config：standard-schema 风格校验器
  - 业务事件 kv/set、kv/evict 广播
"""

from collections import OrderedDict

from mini_cordis import Service


class Config:
    @staticmethod
    def validate(raw):
        raw = raw or {}
        issues = []
        max_keys = raw.get('max_keys', 8)
        if not isinstance(max_keys, int) or max_keys < 1:
            issues.append({'message': 'max_keys must be a positive int', 'path': ['max_keys']})
        return {'value': {'max_keys': max_keys}, 'issues': issues or None}


class KvStore(Service):
    provide = 'kvstore'

    def __init__(self, ctx, config=None):
        super().__init__(ctx)
        self._max = (config or {}).get('max_keys', 8)
        self._data: 'OrderedDict[str, str]' = OrderedDict()

    def set(self, key: str, value: str):
        """返回被逐出的 key（若有）。超过 max_keys 按写入序 FIFO 逐出。"""
        evicted = None
        if key not in self._data and len(self._data) >= self._max:
            evicted, _ = self._data.popitem(last=False)
            self.ctx.emit('kv/evict', evicted)
        self._data[key] = value
        self.ctx.emit('kv/set', key, value)
        return evicted

    def get(self, key: str):
        return self._data.get(key)

    def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    def keys(self):
        return list(self._data)


plugin = KvStore
