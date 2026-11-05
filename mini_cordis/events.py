"""
events —— 事件总线，五种派发模式

对应 cordis 源码：vendor/cordis/src/events.ts

与 cordis 对齐的语义：
  emit      同步触发。监听器若返回协程，则后台调度执行（fire-and-forget），
            等价于 JS 里"不 await Promise"。
  parallel  并发执行所有监听器，全部完成后返回。
  serial    依次执行并等待，遇到"否决"提前停止。
  bail      同步版 serial：同步监听器返回否决值即停。
  waterfall 责任链：每个监听器收到 next 关键字参数，必须调用 next(...)
            才会继续；可以改写传递的参数；返回值即链的结果。

  "否决"（bail）的判定与 cordis 相同：返回值不是 None/False（isBailed）。

  通过 ctx.on/once 注册的监听器绑定在注册者 fiber 的 effect 上：
  fiber 卸载 → 监听器自动摘除。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Dict, List


def is_bailed(value: Any) -> bool:
    """bail 判定：非 None、非 False 即视为否决。"""
    return value is not None and value is not False


def _unwrap(call_args: tuple):
    """cordis 约定：ctx.emit("name", ...) 或 ctx.emit(this_arg, "name", ...)。
    事件名永远是字符串；若首参不是字符串则它是显式 thisArg（本实现透传给忽略，
    保留与 cordis 相同的调用形态）。"""
    if not call_args:
        raise TypeError("emit() requires an event name")
    if isinstance(call_args[0], str):
        return None, call_args[0], call_args[1:]
    if len(call_args) >= 2 and isinstance(call_args[1], str):
        return call_args[0], call_args[1], call_args[2:]
    raise TypeError("event name must be a string")


class EventsService:
    """服务名 'events'。ctx 上的 on/once/emit/... 会转发到这里。"""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._map: Dict[str, List[Callable]] = {}
        self._sn = 0
        # 派发前的拦截点（内部用），对应 cordis 的 'internal/dispatch'
        self.filter = None

    # ------------------------------------------------------------- 注册

    def on(self, name: str, listener: Callable, fiber=None) -> Callable[[], None]:
        """加监听器；生命周期挂到注册者 fiber 上（ctx.on 会传入自己的 fiber）。"""
        (fiber or self.ctx.fiber).effect(lambda: self._register(name, listener), f"ctx.on({name})")
        return lambda: self._remove(name, listener)

    def once(self, name: str, listener: Callable, fiber=None) -> Callable[[], None]:
        def wrapper(*args: Any):
            self._remove(name, wrapper)
            return listener(*args)

        (fiber or self.ctx.fiber).effect(lambda: self._register(name, wrapper), f"ctx.once({name})")
        return lambda: self._remove(name, wrapper)

    def _register(self, name: str, listener: Callable):
        hooks = self._map.setdefault(name, [])
        hooks.append(listener)

        def remove():
            try:
                hooks.remove(listener)
            except ValueError:
                pass

        return remove

    def _remove(self, name: str, listener: Callable) -> None:
        hooks = self._map.get(name)
        if hooks and listener in hooks:
            hooks.remove(listener)

    def listeners(self, name: str) -> List[Callable]:
        return list(self._map.get(name, []))

    # ------------------------------------------------------------- 派发

    def _get(self, name: str) -> List[Callable]:
        return list(self._map.get(name, []))

    def emit(self, *call_args: Any) -> None:
        """同步触发；异步监听器被调度到后台。返回 None。"""
        this_arg, name, args = _unwrap(call_args)
        if not isinstance(name, str):
            raise TypeError("event name must be a string")
        for hook in self._get(name):
            try:
                result = hook(*args)
                if inspect.isawaitable(result):
                    task = asyncio.get_running_loop().create_task(result)
                    task.add_done_callback(self._task_error)
            except Exception as error:  # noqa: BLE001 - cordis 同样吞下 emit 错误并记录
                self.ctx.logger("events").error(error)

    async def parallel(self, *call_args: Any) -> None:
        """并发执行所有监听器（协程并发，非协程直接调用）。"""
        this_arg, name, args = _unwrap(call_args)
        for hook in self._get(name):
            result = hook(*args)
            if inspect.isawaitable(result):
                await result

    async def serial(self, *call_args: Any) -> Any:
        """顺序执行并等待；监听器返回否决值时停止并返回该值。"""
        this_arg, name, args = _unwrap(call_args)
        for hook in self._get(name):
            result = hook(*args)
            if inspect.isawaitable(result):
                result = await result
            if is_bailed(result):
                return result
        return None

    def bail(self, *call_args: Any) -> Any:
        """同步版 serial。监听器应为同步函数。"""
        this_arg, name, args = _unwrap(call_args)
        for hook in self._get(name):
            result = hook(*args)
            if inspect.isawaitable(result):
                raise TypeError("bail() requires sync listeners; use serial() for async")
            if is_bailed(result):
                return result
        return None

    async def waterfall(self, *call_args: Any) -> Any:
        """责任链。最后一个位置参数是终结回调 inner；
        监听器签名 fn(*args, next=...)：不调 next 即终止整条链。"""
        this_arg, name, args = _unwrap(call_args)
        if not args or not callable(args[-1]):
            raise TypeError("waterfall requires a final inner callback")
        inner, args = args[-1], args[:-1]

        async def chain_next(*next_args: Any):
            result = inner(*next_args)
            return await result if inspect.isawaitable(result) else result

        for hook in reversed(self._get(name)):
            chain_next = self._wrap_hook(hook, chain_next)
        return await chain_next(*args)

    @staticmethod
    def _wrap_hook(hook: Callable, following) :
        async def run(*a: Any):
            result = hook(*a, next=following)
            if inspect.isawaitable(result):
                return await result
            return result

        return run

    @staticmethod
    def _task_error(task: "asyncio.Task") -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            import traceback

            traceback.print_exception(type(error), error, error.__traceback__)
