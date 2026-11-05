"""
reflect —— 服务注册表与依赖唤醒

对应 cordis 源码：vendor/cordis/src/reflect.ts + fiber.ts::_updateState

Python 差异说明：
  cordis 用 JS Proxy 拦截 ctx.xxx 属性读写来解析服务；Python 用
  Context.__getattr__ / __setattr__ 达到同样效果（见 context.py）。
  本模块只负责"服务存储 + 可见性 + 通知"。

与 cordis 完全一致的三条关键语义：
  1. 可见性（strict）：impl.fiber.state 必须是 ACTIVE。
  2. 唤醒时机：provider 跨越 ACTIVE 边界（进入/离开）时，
     由 fiber._update_state 调用 notify() 通知所有注入者 ——
     这解决了"插件在 LOADING 期间 provide，此时依赖者不能立刻激活"的时序问题。
     provide 本身只在"当前已经 ACTIVE"时立即 notify。
  3. 服务注销（disposer）：先 notify，并等待所有依赖者完成
     加载/卸载过渡后，才从提供者 store 中删除 —— 保证依赖者
     在 provider 消失前已把自己收拾干净。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from .fiber import FiberState


class Impl:
    """一个服务的注册记录。uid 取自提供者 fiber，参与依赖 epoch 指纹。"""

    def __init__(self, fiber: Any, value: Any, check: Optional[Callable[[], bool]] = None) -> None:
        self.fiber = fiber
        self.value = value
        self.check = check

    @property
    def uid(self):
        return self.fiber.uid


class ReflectService:
    """服务存储。挂在 ctx.reflect。"""

    def __init__(self, ctx: Any) -> None:
        self.store: Dict[str, Impl] = {}
        # 计算属性注册表：name -> {"type": "accessor", "get": fn, "set": fn|None}
        self.props: Dict[str, dict] = {}
        self._ctx_ref = ctx

    # ------------------------------------------------------------- 读取

    def _get_impl(self, name: str, strict: bool = True) -> Optional[Impl]:
        impl = self.store.get(name)
        if not impl:
            return None
        if strict and impl.fiber.state != FiberState['ACTIVE']:
            return None
        return impl

    def get(self, name: str, strict: bool = True) -> Any:
        """按名字读服务；strict 时要求提供者 ACTIVE。"""
        impl = self._get_impl(name, strict)
        return impl.value if impl else None

    def has(self, name: str) -> bool:
        return name in self.store

    # ------------------------------------------------------------- 写入

    def set(self, ctx: Any, name: str, value: Any) -> None:
        """只有提供者 fiber 的上下文能更新自己提供的服务。"""
        impl = self.store.get(name)
        if not impl:
            raise NameError(f"cannot set '{name}' before provide")
        if impl.fiber is not ctx.fiber:
            raise RuntimeError(f"cannot set '{name}' from another context")
        impl.value = value
        if ctx.fiber.state == FiberState['ACTIVE']:
            self.notify([name])

    def provide(self, ctx: Any, name: str, value: Any, check: Optional[Callable[[], bool]] = None):
        """在 current fiber 上注册服务，返回 disposer（协程函数）。

        必须在插件回调执行期间调用（fiber 处于 LOADING/ACTIVE）。
        """
        fiber = ctx.fiber
        if fiber.state == FiberState['PENDING']:
            raise RuntimeError("cannot provide in inactive context")
        if name in self.store:
            raise RuntimeError(f"cannot provide '{name}' because it is provided")

        impl = Impl(fiber, value, check)
        self.store[name] = impl
        if fiber.store is not None:
            fiber.store[name] = impl

        # 仅在已 ACTIVE 时立即唤醒依赖者；LOADING 期间的注册，
        # 依赖者将在 provider 跨越 ACTIVE 边界时被统一唤醒。
        if fiber.state == FiberState['ACTIVE']:
            self.notify([name])

        async def dispose():
            if self.store.get(name) is impl:
                del self.store[name]
            # 先让所有依赖者完成过渡（卸载自己或换用新实现），再收尾
            fibers = self.notify([name])
            if fibers:
                await asyncio.gather(*(f.await_() for f in fibers), return_exceptions=True)
            if fiber.store and name in fiber.store:
                del fiber.store[name]

        # 注册到 fiber 的 effect 链：fiber 卸载 → 服务自动注销
        # （对应 cordis reflect.provide 内部的 fiber.effect 包装）
        fiber.effect(lambda: dispose, f'ctx.provide({name})')
        return dispose

    def accessor(self, ctx: Any, name: str, get: Callable, set_: Optional[Callable] = None) -> None:
        """定义计算属性（随 current fiber 卸载消失）。"""
        fiber = ctx.fiber
        if name in self.props:
            raise RuntimeError(f"cannot redefine accessor '{name}'")
        self.props[name] = {"type": "accessor", "get": get, "set": set_}

        def _remove():
            self.props.pop(name, None)

        # 注意：effect(execute) 的 execute 会立即运行，disposer 要作为返回值
        fiber.effect(lambda: _remove, f"ctx.accessor({name})")

    # ------------------------------------------------------------- 通知

    def notify(self, names: List[str]) -> List[Any]:
        """让注入了这些名字的 fiber 重新计算依赖 epoch。

        返回受影响的 fiber 列表（调用方可 await 它们完成过渡）。
        同时向内部事件 internal/service 广播。
        """
        name_set = set(names)
        fibers: List[Any] = []
        for runtime in self._ctx_ref.registry.values():
            for fiber in runtime.fibers:
                if name_set & fiber.inject.keys():
                    for name in names:
                        fiber._check_impl(name)
                    fiber._refresh()
                    if fiber not in fibers:
                        fibers.append(fiber)
        for name in names:
            impl = self.store.get(name)
            self._ctx_ref.events.emit("internal/service", name, impl.value if impl else None)
        return fibers
