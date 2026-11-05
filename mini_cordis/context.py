"""
context —— 依赖注入容器（插件上下文）

对应 cordis 源码：vendor/cordis/src/context.ts + reflect.ts(Proxy handler)

JS 里 cordis 把 root context 包在 Proxy 里，任何 ctx.xxx 的属性读取
都被 handler 拦截来解析服务。Python 的等价物是 __getattr__/__setattr__：

    ctx.counter            → fiber.store 快照（激活期间可见的注入服务）
    ctx.some_service       → root 上下文：reflect 的宽松查找
    ctx.on / emit / plugin → Context 上的方法（转发给各服务）
    ctx.extend(meta)       → 原型式子上下文（不改动父级）

与 cordis 一致的查找顺序（Proxy get handler）：
  1. 实例内部属性（root/fiber/registry/reflect/events/logger…）
  2. accessor 计算属性
  3. 沿 fiber 链：本 fiber.store → 注入名但未激活则报错（"必须 inject"）
     → 父 fiber → ……
  4. 到达 root：reflect 宽松查找（strict=False，可见即所得）
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional

from .events import EventsService
from .fiber import Fiber
from .loader import LoaderService
from .logger import LoggerService
from .reflect import ReflectService
from .registry import RegistryService

# 允许直接读写的内部属性名（不参与服务解析）
INTERNAL = {'root', 'fiber', 'events', 'logger', 'reflect', 'registry', 'baseUrl', 'loader'}


class Context:
    """插件上下文。root = Context()（须在事件循环内创建）。"""

    def __init__(self) -> None:
        self._ctx_parent: Optional['Context'] = None
        self._intercept: Optional[Dict[str, Any]] = None
        self.root = self
        self.baseUrl = ''
        # 装配顺序有讲究：reflect/registry 先于 fiber；events/logger 需要 fiber 就绪
        self.reflect = ReflectService(self)
        self.registry = RegistryService(self)
        self.fiber = Fiber(self, None, {}, None)  # root fiber
        self.events = EventsService(self)
        self.logger = LoggerService(self)
        self.loader = LoaderService(self)
        # 核心服务注册为可注入服务（对应 cordis core 的提供）
        self.reflect.provide(self, 'events', self.events)
        self.reflect.provide(self, 'logger', self.logger)
        self.reflect.provide(self, 'loader', self.loader)

    # ---------------------------------------------------------------- 扩展

    def extend(self, meta: Dict[str, Any]) -> 'Context':
        """原型式子上下文：只读父链，不修改父级（对齐 cordis Context.extend）。"""
        child = Context.__new__(Context)
        child.__dict__['_ctx_parent'] = self
        child.__dict__['_intercept'] = None
        child.__dict__.update(meta)
        return child

    def intercept(self, name: str, config: Dict[str, Any]) -> 'Context':
        """返回带"按服务截获配置"的子上下文；用它加载的插件，
        对应服务可通过 resolve_config 读到这份配置（对齐 cordis ctx.intercept）。"""
        child = self.extend({})
        child.__dict__['_intercept'] = {name: dict(config)}
        return child

    def _add_intercept_layer(self, entries: Dict[str, Any]) -> None:
        """fiber 构造时挂 inject 声明里的截获配置（一层）。"""
        self.__dict__['_intercept'] = dict(entries)

    def _intercept_layers(self, name: str) -> list:
        """收集该服务名在 ctx 链上的全部截获配置，越靠近 root 的越靠前。"""
        layers = []
        cur: Optional['Context'] = self
        while cur is not None:
            layer = cur.__dict__.get('_intercept')
            if layer and name in layer:
                layers.append(layer[name])
            cur = cur.__dict__.get('_ctx_parent')
        layers.reverse()
        return layers

    def resolve_intercept(self, name: str) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for layer in self._intercept_layers(name):
            merged.update(layer)
        return merged

    # ------------------------------------------------------------ 属性拦截

    def _get_fiber(self) -> Fiber:
        cur: Optional['Context'] = self
        while cur is not None:
            f = cur.__dict__.get('fiber')
            if f is not None:
                return f
            cur = cur.__dict__.get('_ctx_parent')
        raise AttributeError('context has no fiber')

    def __getattr__(self, name: str):
        # __getattr__ 只在常规查找失败后触发：本实例 dict 里必然没有 name
        if name.startswith('__') or name.startswith('_ctx') or name in ('_intercept', '_intercept_name'):
            raise AttributeError(name)
        # 1) 沿上下文链找内部属性（fiber/root/events/logger/…）
        cur: Optional['Context'] = self.__dict__.get('_ctx_parent')
        while cur is not None:
            if name in cur.__dict__:
                return cur.__dict__[name]
            cur = cur.__dict__.get('_ctx_parent')
        # 2) accessor 计算属性
        root: 'Context' = self._get_root()
        prop = root.reflect.props.get(name)
        if prop is not None:
            return prop['get'](self)
        # 3) 沿 fiber 链解析服务
        fiber = self._get_fiber()
        f = fiber
        while True:
            store = f.store
            if store and name in store:
                return store[name].value
            if name in f.inject:
                raise AttributeError(
                    f"plugin '{f.name}' injects '{name}' but it is not active yet")
            if f.runtime is None:
                break
            f = f.parent._get_fiber()
        # 4) root：宽松查找
        impl = root.reflect._get_impl(name, strict=False)
        if impl is not None:
            return impl.value
        raise AttributeError(
            f'cannot get "{name}" without inject (plugin "{fiber.name}"); '
            f'declare inject=["{name}"] or provide it before loading')

    def __setattr__(self, name: str, value: Any) -> None:
        d = self.__dict__
        if (name in d or name.startswith('_') or name in INTERNAL
                or hasattr(type(self), name)):
            object.__setattr__(self, name, value)
            return
        root = self._get_root()
        prop = root.reflect.props.get(name)
        if prop is not None:
            if prop.get('set') is None:
                raise AttributeError(f'accessor "{name}" is read-only')
            return prop['set'](self, value)
        if name in root.reflect.store:
            return root.reflect.set(self, name, value)
        raise AttributeError(f'cannot set "{name}": not a provided service')

    def _get_root(self) -> 'Context':
        cur: 'Context' = self
        while cur.__dict__.get('_ctx_parent') is not None:
            cur = cur.__dict__['_ctx_parent']
        return cur

    # ------------------------------------------------------- 服务 / 生命周期 API

    def get(self, name: str, strict: bool = True) -> Any:
        """显式读取服务；strict=False 可看到未激活的注册。"""
        return self._get_root().reflect.get(name, strict)

    def provide(self, name: str, value: Any, check: Optional[Callable[[], bool]] = None) -> Callable:
        """在当前 fiber 上注册服务（随 fiber 卸载自动注销）。"""
        return self._get_root().reflect.provide(self, name, value, check)

    def accessor(self, name: str, get: Callable, set_: Optional[Callable] = None) -> None:
        self._get_root().reflect.accessor(self, name, get, set_)

    def effect(self, execute: Callable, label: str = 'ctx.effect()'):
        """注册带清理的副作用。execute 返回 disposer / 生成器 / 协程 / 异步生成器。"""
        return self.fiber.effect(execute, label)

    def plugin(self, plugin: Any, config: Any = None) -> Fiber:
        """加载插件。返回 Fiber（可 await；await 表示生命周期稳定）。"""
        return self.registry.plugin(self, plugin, config)

    def inject(self, deps, callback: Callable, name: Optional[str] = None) -> Fiber:
        """ctx.inject(['a','b'], fn) ≡ ctx.plugin({'apply': fn, 'inject': deps})。"""
        return self.registry.inject(self, deps, callback, name)

    # ------------------------------------------------------------- 事件转发

    def on(self, name: str, listener: Callable):
        """监听事件；绑定到当前 fiber，卸载即摘除。"""
        return self.events.on(name, listener, fiber=self.fiber)

    def once(self, name: str, listener: Callable):
        return self.events.once(name, listener, fiber=self.fiber)

    def emit(self, *args: Any) -> None:
        self.events.emit(*args)

    def parallel(self, *args: Any):
        return self.events.parallel(*args)

    def serial(self, *args: Any):
        return self.events.serial(*args)

    def bail(self, *args: Any):
        return self.events.bail(*args)

    def waterfall(self, *args: Any):
        return self.events.waterfall(*args)


def run(entrypoint: Callable) -> Any:
    """应用入口便捷函数：建 root context → await entrypoint(root) → 级联卸载。"""
    async def _main():
        root = Context()
        try:
            result = entrypoint(root)
            if asyncio.iscoroutine(result):
                await result
        finally:
            await root.fiber.shutdown()

    return asyncio.run(_main())
