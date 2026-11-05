"""
utils —— 运行时基础设施

对应 cordis 源码：vendor/cordis/src/utils.ts

核心概念
  DisposableList: 清理函数的集合。push() 返回移除函数；clear() 取出并清空。
                  Fiber 用它收集 effect 产生的 disposer。
  协议符号:       插件通过与运行时的"私下约定"（约定方法名）交互，
                  而不是往公共 API 上挂东西。
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, List

# 清理函数：由 effect 返回，fiber 卸载时按注册的逆序执行；可以是协程函数。
Disposable = Callable[[], Any]


class DisposableList:
    """可迭代、可整体取出的清理函数列表。"""

    def __init__(self) -> None:
        self._items: List[Any] = []

    def push(self, item: Any) -> Callable[[], None]:
        """加入条目，返回幂等的移除函数。"""
        self._items.append(item)
        removed = False

        def remove() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            try:
                self._items.remove(item)
            except ValueError:
                pass

        return remove

    def delete(self, item: Any) -> None:
        try:
            self._items.remove(item)
        except ValueError:
            pass

    def clear(self) -> List[Any]:
        """取出全部条目并清空。"""
        taken, self._items = self._items, []
        return taken

    @property
    def length(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(list(self._items))


async def run_disposable(fn: Any) -> None:
    """执行一个清理函数；若返回 awaitable（协程/Future）则等待它。"""
    result = fn()
    if inspect.isawaitable(result):
        await result


def is_constructor(obj: Any) -> bool:
    """区分 class 插件与普通函数插件。"""
    return inspect.isclass(obj)


def define_property(obj: Any, key: str, value: Any) -> None:
    """写入实例字典（约定：下划线开头的不参与服务解析）。"""
    object.__setattr__(obj, key, value)
