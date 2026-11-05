"""
registry —— 插件运行时注册表

对应 cordis 源码：vendor/cordis/src/registry.ts

职责：
  1. 把"插件"归一化为 PluginRuntime{name, callback, Config, fibers}。
     插件三种形态（与 cordis 相同）：
       - 函数：def plugin(ctx, config): ...
       - 类  ：class P: def __init__(self, ctx, config): ...（可带 init 钩子）
       - 字典：{'apply': fn|class, 'name': ..., 'inject': ..., 'Config': ...}
  2. 解析 inject 声明：列表 ['a','b'] 或字典 {'a': 截获配置, 'b': None}；
     类插件沿 MRO 收集（对应 cordis 的 checkProto 静态继承）。
  3. 以 callback 对象为身份缓存 runtime（同一插件加载两次共享 fibers 列表）。
  4. counter 提供全局 uid。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from .fiber import Fiber

if TYPE_CHECKING:
    from .context import Context


class PluginRuntime:
    """共享的插件运行时记录：同一插件回调的所有 fiber。"""

    def __init__(self, name: str, callback: Any, config_validator=None) -> None:
        self.name = name
        self.callback = callback
        self.Config = config_validator
        self.fibers: List[Fiber] = []


def resolve_inject(plugin: Any) -> Dict[str, Any]:
    """解析插件的 inject 声明（函数属性 / 类 MRO / 字典字段）。"""
    inject = None
    if isinstance(plugin, dict):
        inject = plugin.get('inject')
    elif isinstance(plugin, type):
        # 沿 MRO 从基类到子类合并（子类覆盖父类）
        merged: Dict[str, Any] = {}
        for klass in reversed(plugin.__mro__):
            own = klass.__dict__.get('inject')
            if own is not None:
                merged.update(_normalize_inject(own))
        return merged
    else:
        inject = getattr(plugin, 'inject', None)
    return _normalize_inject(inject)


def _normalize_inject(inject) -> Dict[str, Any]:
    if inject is None:
        return {}
    if isinstance(inject, (list, tuple, set)):
        return {name: None for name in inject}
    if isinstance(inject, dict):
        return dict(inject)
    raise TypeError(f'invalid inject declaration: {inject!r}')


class RegistryService(dict):
    """callback → PluginRuntime。ctx.registry。"""

    def __init__(self, ctx: 'Context') -> None:
        super().__init__()
        self._ctx = ctx
        self._counter = 0

    def next_uid(self) -> int:
        self._counter += 1
        return self._counter

    def _runtime(self, plugin: Any) -> PluginRuntime:
        if isinstance(plugin, dict):
            callback = plugin.get('apply')
            if callback is None:
                raise TypeError('dict plugin requires "apply"')
            name = plugin.get('name') or getattr(callback, '__name__', 'anonymous')
            validator = plugin.get('Config')
        else:
            callback = plugin
            name = getattr(callback, '__name__', 'anonymous')
            validator = getattr(callback, 'Config', None)
        if not callable(callback):
            raise TypeError(f'invalid plugin: {plugin!r}')
        runtime = self.get(callback)
        if runtime is None:
            runtime = PluginRuntime(name, callback, validator)
            self[callback] = runtime
        return runtime

    def plugin(self, ctx: 'Context', plugin: Any, config: Any = None) -> Fiber:
        """加载插件：返回 Fiber（awaitable）。缺依赖不报错，只是 PENDING。"""
        runtime = self._runtime(plugin)
        inject = resolve_inject(plugin)
        return Fiber(ctx, config, inject, runtime)

    def inject(self, ctx: 'Context', deps, callback: Callable, name: Optional[str] = None) -> Fiber:
        """ctx.inject(['a','b'], fn)：匿名插件 + 依赖声明，等价于
        ctx.plugin({'apply': fn, 'inject': deps})。"""
        wrapped = {
            'apply': callback,
            'inject': deps,
            'name': name or getattr(callback, '__name__', 'inject'),
        }
        return self.plugin(ctx, wrapped)

    def delete(self, callback: Callable):
        """删除运行时记录并销毁其全部 fiber（对应 cordis registry.delete）。"""
        runtime = self.pop(callback, None)
        if runtime is None:
            return

        async def _dispose_all():
            for fiber in list(runtime.fibers):
                await fiber.dispose()

        return _dispose_all()
