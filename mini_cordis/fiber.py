"""
fiber —— 插件生命周期状态机

对应 cordis 源码：vendor/cordis/src/fiber.ts

核心语义（逐条对齐 cordis）：
  1. epoch 指纹：fiber 持有一个 epoch —— 所有注入依赖"提供者 uid"的拼接串。
     任何一个依赖不可用（提供者不存在 / 非 ACTIVE / check() 为假）→ epoch = INACTIVE。
  2. 状态迁移由 _set_epoch 驱动：
       INACTIVE → 有效   : 调度 _load（运行插件回调）
       有效     → INACTIVE（或 uid 变化=依赖被替换）: 调度 _unload
     过渡进行中（inertia 非空）时，新的 epoch 变化只记录不启动；
     过渡结束时比较"epoch 是否还是启动时那份"来决定收尾还是再来一轮 ——
     这就是 cordis 处理依赖抖动 / 替换的竞态模型。
  3. 加载失败：进 logger，_error 置位，epoch 强制 INACTIVE（防止重试风暴）；
     之后任何依赖变化（notify → _refresh）都会带新 epoch 自动重试。
  4. effect 形状（插件回调返回值与 ctx.effect 相同）：
       None | 清理函数 | (同步)可迭代逐个 yield 清理函数
       | awaitable(→清理函数) | async generator 逐个 yield 清理函数
     插件体的异步 setup 在 fiber 进入 ACTIVE 之前完成（对齐 cordis _execute）。
     同一 effect 内 disposer 逆序执行；fiber 卸载时各 effect 并发清理
     （对齐 cordis 的 Promise.all(_disposables)）。
  5. 子 fiber 的销毁注册在父 fiber 的 effect 上 → 父卸载，子孙级联。
  6. fiber 跨越 ACTIVE 边界时 notify 它提供的所有服务 —— 解决
     "插件在 LOADING 期间 provide，依赖者必须等 ACTIVE 才能看见"的时序。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from .utils import DisposableList, is_constructor, run_disposable

if TYPE_CHECKING:
    from .context import Context

FiberState = {
    'PENDING': 0,    # 等待注入依赖全部可用
    'LOADING': 1,    # 插件回调执行中（可能异步）
    'ACTIVE': 2,     # 已激活
    'FAILED': 3,     # 回调/配置校验失败（错误已进 logger）
    'UNLOADING': 4,  # 清理中
    'DISPOSED': 5,   # 已销毁
}

INACTIVE = '__INACTIVE__'


class ValidationError(TypeError):
    """插件配置校验失败。"""


def resolve_config(validator, config: Any) -> Any:
    """支持两种校验器：callable(raw)→validated（抛错即失败）；
    或 standard-schema 风格 {validate(raw)→{value, issues}}。"""
    if validator is None:
        return config
    if hasattr(validator, 'validate') and callable(validator.validate):
        # standard-schema 风格（注意先于 callable 判断：类本身也是 callable）
        result = validator.validate(config)
    elif callable(validator):
        return validator(config)
    else:
        return config
    if result.get('issues'):
        lines = '\n'.join(
            f"  - {i['message']}" + (f" (at {'.'.join(map(str, i['path']))})" if i.get('path') else '')
            for i in result['issues']
        )
        raise ValidationError(f'invalid config:\n{lines}')
    return result.get('value', config)


def _loop() -> 'asyncio.AbstractEventLoop':
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError(
            'mini_cordis 需要运行中的事件循环：请用 asyncio.run(main()) / '
            'mini_cordis.run(main) 启动（或在 IsolatedAsyncioTestCase 中）'
        ) from None


class Effect:
    """一次 ctx.effect() 注册句柄：可调用（=dispose），可 await（=等异步 setup）。"""

    def __init__(self, fiber: 'Fiber', label: str) -> None:
        self._fiber = fiber
        self.label = label
        self.meta = {'label': label, 'children': []}
        self._disposables: List[Callable] = []
        self._setup: Optional['asyncio.Task'] = None
        self._disposed = False
        self._dispose_task: Optional['asyncio.Task'] = None
        self._remove: Optional[Callable] = None

    # ------------------------------------------------------------ collect

    def _safe_collect(self, value) -> None:
        if value is None:
            return
        if callable(value):
            self._disposables.append(value)
        else:
            raise TypeError('invalid effect')

    def collect(self, effect) -> None:
        """ctx.effect 的返回值收集：异步形状转为后台 task（注册处不等待）。"""
        if effect is None:
            return
        if callable(effect):
            self._disposables.append(effect)
        elif inspect.isgenerator(effect):
            for value in effect:
                self._safe_collect(value)
        elif inspect.isasyncgen(effect):
            self._setup = _loop().create_task(self._run_asyncgen(effect))
        elif inspect.isawaitable(effect):
            self._setup = _loop().create_task(self._run_awaitable(effect))
        elif hasattr(effect, '__iter__'):
            for value in effect:
                self._safe_collect(value)
        else:
            raise TypeError('invalid effect')

    async def _run_awaitable(self, awaitable):
        try:
            value = await awaitable
        except Exception as error:  # noqa: BLE001
            self._fiber.ctx.logger(self._fiber.name).error(error)
            await self.dispose()
            return
        if self._disposed:
            await run_disposable(value)
        else:
            self._safe_collect(value)

    async def _run_asyncgen(self, asyncgen):
        try:
            async for value in asyncgen:
                if self._disposed:
                    await run_disposable(value)
                    continue
                self._safe_collect(value)
        except Exception as error:  # noqa: BLE001
            self._fiber.ctx.logger(self._fiber.name).error(error)
            await self.dispose()

    # ------------------------------------------------------------ dispose

    async def dispose(self) -> None:
        """幂等；并发调用共享同一次清理。"""
        if self._dispose_task is None:
            self._disposed = True
            if self._remove:
                self._remove()
            self._dispose_task = _loop().create_task(self._do_dispose())
        await asyncio.shield(self._dispose_task)

    async def _do_dispose(self) -> None:
        if self._setup is not None:
            await asyncio.gather(self._setup, return_exceptions=True)
        for disposable in reversed(self._disposables):
            try:
                await run_disposable(disposable)
            except Exception as error:  # noqa: BLE001
                self._fiber.ctx.logger(self._fiber.name).error(error)
        self._disposables.clear()

    __call__ = dispose

    def __await__(self):
        if self._setup is not None:
            return asyncio.shield(self._setup).__await__()
        return self._noop().__await__()

    async def _noop(self):
        return self


class Fiber:
    """插件运行时实例。ctx.plugin(P) 返回它；await 它 = 等生命周期稳定。"""

    def __init__(self, parent: 'Context', config: Any, inject: Dict[str, Any], runtime) -> None:
        self.parent = parent
        self.runtime = runtime
        self.inject: Dict[str, Any] = dict(inject or {})
        self._config = config
        self.config: Any = None
        self._error: Optional[BaseException] = None
        self._live = False
        self._store: Dict[str, Any] = {}
        self._epoch = INACTIVE
        self._inertia: Optional['asyncio.Task'] = None
        self._disposables = DisposableList()
        self.uid: Optional[int] = None
        self.state = FiberState['PENDING']
        self.store: Optional[Dict[str, Any]] = None

        if runtime is not None:
            self.uid = parent.registry.next_uid()
            self.ctx: 'Context' = parent.extend({'fiber': self})

            # inject 声明里的按服务 intercept 配置 → 本 fiber 上下文加一层
            entries = {k: v for k, v in self.inject.items() if v is not None}
            if entries:
                self.ctx._add_intercept_layer(entries)

            # 子 fiber 的销毁挂在父 fiber 的 effect 上：父卸载 → 子级联卸载
            def _register() -> Callable:
                runtime.fibers.append(self)

                async def _cleanup():
                    self.uid = None
                    self._live = False
                    try:
                        runtime.fibers.remove(self)
                    except ValueError:
                        pass
                    self._set_epoch(INACTIVE)
                    if self._inertia is None:
                        # PENDING 期间 observer 也可能注册过 effect，显式清一遍
                        self._start_unload()
                    while self._inertia is not None:
                        await self._inertia

                return _cleanup

            self.dispose: Effect = parent.fiber.effect(_register, 'ctx.plugin()')
            self.ctx.events.emit('internal/plugin', self)

            for name in self.inject:
                self._check_impl(name)
            self._refresh()
        else:
            # root fiber：uid=0，永远存在，epoch=''（有效）
            self.uid = 0
            self.ctx = parent
            self.state = FiberState['ACTIVE']
            self.store = {}
            self._epoch = ''
            # root 的 dispose = shutdown：级联卸载全部插件，容器存活
            # （对齐 cordis：root fiber 的 dispose 实为 restart）
            self.dispose = self.shutdown

    # ---------------------------------------------------------------- misc

    @property
    def name(self) -> str:
        # 沿父链找最近的 runtime；到 root fiber（runtime=None）即止
        f: 'Fiber' = self
        while f.runtime is None:
            if f.parent is None:
                return 'root'
            nxt = f.parent._get_fiber()
            if nxt is f:
                return 'root'
            f = nxt
        return f.runtime.name or 'root'

    def assert_active(self) -> None:
        if self.uid is None:
            raise RuntimeError(f'cannot create effect on disposed fiber ({self.name})')
        if self.state == FiberState['UNLOADING']:
            raise RuntimeError(f'cannot create effect while unloading ({self.name})')

    # -------------------------------------------------------------- effect

    def effect(self, execute: Callable, label: str = 'anonymous') -> Effect:
        self.assert_active()
        eff = Effect(self, label)
        eff._remove = self._disposables.push(eff)
        try:
            eff.collect(execute())
        except BaseException:
            eff._remove()
            raise
        return eff

    def get_effects(self) -> List[dict]:
        return [e.meta for e in self._disposables if isinstance(e, Effect)]

    # ---------------------------------------------------- dependency engine

    def _check_impl(self, name: str) -> None:
        impl = self.ctx.reflect._get_impl(name, strict=True)
        if impl is None:
            return self._store.pop(name, None)
        if impl.check is not None:
            try:
                if not impl.check():
                    return self._store.pop(name, None)
            except Exception:  # check 谓词抛错 → 视为不可用
                return self._store.pop(name, None)
        self._store[name] = impl

    def _refresh(self) -> None:
        epoch = ''
        for name in self.inject:
            impl = self._store.get(name)
            if impl is None:
                epoch = INACTIVE
                break
            epoch += ':' + str(impl.uid)
        self._set_epoch(epoch)

    def _set_epoch(self, epoch: str) -> None:
        old = self._epoch
        if epoch == old:
            return
        self._epoch = epoch
        if self._inertia is not None:
            return  # 过渡中：结束时按 epoch 对比再驱动
        if epoch != INACTIVE and old == INACTIVE:
            self._start_load()
        else:
            self._start_unload()

    def _compute_state(self) -> int:
        if self.uid is None:
            return FiberState['DISPOSED']
        if self._error is not None:
            return FiberState['FAILED']
        if self._live:
            return FiberState['ACTIVE']
        return FiberState['PENDING']

    def _update_state(self, explicit: Optional[int] = None) -> None:
        old = self.state
        self.state = explicit if explicit is not None else self._compute_state()
        if old == self.state:
            return
        self.ctx.events.emit('internal/status', self, old)
        # 跨越 ACTIVE 边界 → notify 自己提供的全部服务
        if old == FiberState['ACTIVE'] or self.state == FiberState['ACTIVE']:
            names = [k for k, impl in self.ctx.reflect.store.items() if impl.fiber is self]
            if names:
                self.ctx.reflect.notify(names)

    # ------------------------------------------------------- load / unload

    def _start_load(self) -> None:
        self._inertia = _loop().create_task(self._load())
        self._update_state(FiberState['LOADING'])

    def _start_unload(self) -> None:
        self._inertia = _loop().create_task(self._unload())
        self._update_state(FiberState['UNLOADING'])

    async def _consume(self, effect, eff: Effect) -> None:
        """插件体专用收集：与 cordis _execute 相同 —— 全程 await，
        异步 setup 完成后 fiber 才算加载成功。"""
        if effect is None:
            return
        if callable(effect):
            return eff._safe_collect(effect)
        if inspect.isgenerator(effect):
            for value in effect:
                eff._safe_collect(value)
            return
        if inspect.isasyncgen(effect):
            old_epoch = self._epoch
            async for value in effect:
                if self._epoch != old_epoch:  # epoch 已失效，停止
                    return
                eff._safe_collect(value)
            return
        if inspect.isawaitable(effect):
            value = await effect
            return eff._safe_collect(value)
        if hasattr(effect, '__iter__'):
            for value in effect:
                eff._safe_collect(value)
            return
        raise TypeError('invalid effect')

    @staticmethod
    def _call_plugin(callback, ctx, config):
        """cordis 总是以 (ctx, config) 调用插件；Python 按签名适配：
        只声明 ctx 的插件不传 config（JS 构造器天然容忍多余实参）。"""
        try:
            params = inspect.signature(callback).parameters.values()
            wide = any(p.kind in (inspect.Parameter.VAR_POSITIONAL,
                                  inspect.Parameter.VAR_KEYWORD) for p in params)
            positional = sum(1 for p in params if p.kind in (
                inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD))
        except (TypeError, ValueError):
            positional, wide = 2, True
        if wide or positional >= 2:
            return callback(ctx, config)
        return callback(ctx)

    async def _execute(self) -> None:
        callback = self.runtime.callback
        if is_constructor(callback):
            instance = self._call_plugin(callback, self.ctx, self.config)
            init = getattr(instance, 'init', None)
            if callable(init):
                return await self._consume(init(), self._plugin_effect)
            return
        return await self._consume(self._call_plugin(callback, self.ctx, self.config),
                                   self._plugin_effect)

    async def _load(self) -> None:
        self.store = dict(self._store)  # 激活可见性快照（ctx 属性读服务查这份）
        old_epoch = self._epoch
        self._plugin_effect = Effect(self, f'plugin:{self.name}')
        self._plugin_effect._remove = self._disposables.push(self._plugin_effect)
        try:
            # 异步边界：让同批同步的 ctx.plugin() 先完成（对齐 Promise.resolve()）
            await asyncio.sleep(0)
            if self._epoch == old_epoch and self.uid is not None:
                self.config = resolve_config(getattr(self.runtime, 'Config', None), self._config)
                await self._execute()
                self._error = None
        except Exception as reason:  # noqa: BLE001
            self.ctx.logger(self.name).error(reason)
            self._error = reason
            self._epoch = INACTIVE  # 停止自动重试，等依赖变化 / restart()
        self._live = self._epoch == old_epoch
        if self._epoch == old_epoch:
            self._inertia = None
            self._update_state()
        else:
            self._inertia = _loop().create_task(self._unload())
            self._update_state(FiberState['UNLOADING'])

    async def _unload(self) -> None:
        # 各 effect 并发清理（对齐 cordis Promise.all）；effect 内部 disposer 逆序
        tasks = [d.dispose() if isinstance(d, Effect) else run_disposable(d)
                 for d in self._disposables.clear()]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for error in results:
                if isinstance(error, Exception):
                    self.ctx.logger(self.name).error(error)
        self.store = None
        self._live = False
        if self._epoch == INACTIVE:
            self._inertia = None
            self._update_state()
        else:
            # epoch 在卸载期间恢复有效（依赖换了新实现）→ 自动重新加载
            if self._error is not None:
                self._error = None
            self._inertia = _loop().create_task(self._load())
            self._update_state(FiberState['LOADING'])

    # -------------------------------------------------------------- public

    async def await_(self) -> 'Fiber':
        """等待全部生命周期过渡结束；若加载失败则重抛其错误。"""
        while self._inertia is not None:
            await asyncio.shield(self._inertia)
        if self._error is not None:
            raise self._error
        return self

    def __await__(self):
        return self.await_().__await__()

    async def restart(self) -> None:
        """卸载并按当前配置重新加载。"""
        self.assert_active()
        self._error = None
        self._set_epoch(INACTIVE)
        self._refresh()
        await self.await_()

    def update(self, config: Any) -> None:
        """应用新配置（先校验）再重启；依赖缺失时推迟到激活时校验。"""
        self.assert_active()
        self._config = config
        if self._epoch == INACTIVE:
            self._error = None
            self._refresh()  # 依赖就绪则激活并在校验配置
            return
        try:
            resolve_config(getattr(self.runtime, 'Config', None) if self.runtime else None, config)
        except ValidationError as error:
            self.ctx.logger(self.name).error(error)
            return
        # 同步驱动过渡（restart 的同步部分），保证调用方 await fiber 能等到重启
        self._error = None
        self._set_epoch(INACTIVE)
        self._refresh()

    async def shutdown(self) -> None:
        """root fiber 专用：级联卸载全部插件，容器保持存活。"""
        if self.runtime is not None:
            raise RuntimeError('shutdown() is for the root fiber; plugin fibers use dispose()')
        self._error = None
        self._set_epoch(INACTIVE)
        while self._inertia is not None:
            await asyncio.shield(self._inertia)
