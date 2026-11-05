"""mini_cordis 核心语义验收测试（unittest.IsolatedAsyncioTestCase）。

运行：python3 tests/test_runtime.py  或  python3 -m unittest discover -s tests
"""

import asyncio
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mini_cordis import Context, Service, FiberState, ValidationError  # noqa: E402


class RuntimeTest(unittest.IsolatedAsyncioTestCase):

    async def asyncTearDown(self):
        # 每个用例结束后关闭事件循环里残留的任务由各自 dispose 保证
        pass

    # ---------------------------------------------------------- 基础闭环

    async def test_service_inject_events(self):
        root = Context()

        class Counter(Service):
            provide = 'counter'

            def __init__(self, ctx):
                super().__init__(ctx)
                self.n = 0

        seen = []

        def greeter(ctx):
            ctx.on('hi', lambda m: seen.append((m, ctx.counter.n)))

        await root.plugin(Counter)
        await root.plugin({'apply': greeter, 'inject': ['counter'], 'name': 'g'})
        root.emit('hi', 'x')
        assert seen == [('x', 0)]
        await root.fiber.dispose()
        root.emit('hi', 'y')
        assert seen == [('x', 0)]  # 监听器随插件卸载摘除

    async def test_class_and_dict_plugins(self):
        root = Context()
        log = []

        class P:
            inject = ['a']

            def __init__(self, ctx, config):
                log.append(('class', config))

        def fn(ctx, config):
            log.append(('fn', config))

        root.reflect.provide(root, 'a', object())
        await root.plugin(P, 1)
        await root.plugin({'apply': fn, 'name': 'dictfn'}, 2)
        assert ('class', 1) in log and ('fn', 2) in log
        await root.fiber.dispose()

    # ------------------------------------------------------- 依赖动态编排

    async def test_pending_then_provider_appears(self):
        root = Context()
        loaded = []

        def consumer(ctx):
            loaded.append(1)

        fc = root.plugin({'apply': consumer, 'inject': ['db'], 'name': 'c'})
        await asyncio.sleep(0)
        assert fc.state == FiberState['PENDING'] and not loaded

        class Db(Service):
            provide = 'db'

        fd = root.plugin(Db)
        await fd
        await fc  # provider ACTIVE → 依赖者自动激活
        assert fc.state == FiberState['ACTIVE'] and loaded == [1]
        await root.fiber.dispose()

    async def test_provider_dispose_pends_dependent(self):
        root = Context()
        events = []

        def consumer(ctx):
            events.append('load')
            return lambda: events.append('unload')

        class Db(Service):
            provide = 'db'

        fc = root.plugin({'apply': consumer, 'inject': ['db'], 'name': 'c'})
        fd = root.plugin(Db)
        await fd
        await fc
        assert events == ['load']

        await fd.dispose()
        await fc
        assert events == ['load', 'unload']
        assert fc.state == FiberState['PENDING']

        # 新实现出现 → 再次激活（epoch 换 uid）
        fd2 = root.plugin(Db)
        await fd2
        await fc
        assert fc.state == FiberState['ACTIVE'] and events == ['load', 'unload', 'load']
        await root.fiber.dispose()

    async def test_check_predicate_gates_dependent(self):
        root = Context()

        class Gate(Service):
            provide = 'gate'

            def __init__(self, ctx):
                super().__init__(ctx)
                self.ok = False

            def check(self):
                return self.ok

        loaded = []
        fc = root.plugin({'apply': lambda c: loaded.append(1), 'inject': ['gate'], 'name': 'd'})
        fg = root.plugin(Gate)
        await fg
        await asyncio.sleep(0)
        assert fc.state == FiberState['PENDING'] and not loaded

        root.get('gate').ok = True
        root.reflect.notify(['gate'])
        await fc
        assert fc.state == FiberState['ACTIVE'] and loaded == [1]
        await root.fiber.dispose()

    # ------------------------------------------------------------ effects

    async def test_effect_shapes_and_order(self):
        root = Context()
        log = []

        async def plugin(ctx):
            # 生成器：注册序 1,2 → 卸载逆序 2,1
            def gen():
                yield lambda: log.append('d1')
                yield lambda: log.append('d2')
            ctx.effect(gen, 'gen-effect')
            # 协程 effect：await 句柄可等待 setup 完成
            eff = ctx.effect(lambda: asyncio.sleep(0.01, result=lambda: log.append('async')),
                             'async-effect')
            await eff
            return lambda: log.append('body')

        f = await root.plugin(plugin)
        await f.dispose()
        # 各 effect 间并发、effect 内逆序：d2 必在 d1 前
        assert log.index('d2') < log.index('d1')
        assert set(log) == {'d1', 'd2', 'async', 'body'}

    async def test_child_cascade(self):
        root = Context()
        log = []

        async def child(ctx):
            log.append('child+')
            return lambda: log.append('child-')

        def parent(ctx):
            ctx.plugin(child)
            return lambda: log.append('parent-')

        f = await root.plugin(parent)
        assert 'child+' in log
        await f.dispose()
        assert 'child-' in log  # 父卸载级联卸载子

    # -------------------------------------------------------------- events

    async def test_event_modes(self):
        root = Context()
        order = []

        root.on('p', lambda: order.append('a'))
        async def slow():
            await asyncio.sleep(0.02)
            order.append('slow')
        root.on('p', slow)
        await root.parallel('p')
        assert order == ['a', 'slow']

        r = await root.serial('s', lambda: None, )  # 无监听
        assert r is None

        root.on('s', lambda: 'veto!')
        root.on('s', lambda: order.append('never'))
        assert await root.serial('s') == 'veto!'
        assert root.bail('s') == 'veto!'  # bail 是同步的（对齐 cordis）

        async def step(*a, next):
            return await next(a[0] + 1)
        root.on('w', step)
        result = await root.waterfall('w', 0, lambda v: v * 10)
        assert result == 10

        hits = []
        root.once('o', lambda: hits.append(1))
        root.emit('o')
        root.emit('o')
        assert hits == [1]
        await root.fiber.dispose()

    # -------------------------------------------------------------- config

    async def test_config_validation_and_update(self):
        root = Context()
        runs = []

        def Cfg(raw):
            if not isinstance(raw, dict) or 'port' not in raw:
                raise ValidationError('port required')
            return {'port': int(raw['port'])}

        def plugin(ctx, config):
            runs.append(config['port'])

        plugin.Config = Cfg
        f = root.plugin(plugin, {})
        with self.assertRaises(ValidationError):
            await f
        assert f.state == FiberState['FAILED']

        f.update({'port': '8081'})
        await f
        assert runs == [8081] and f.state == FiberState['ACTIVE']
        f.update({'port': 9090})
        await f
        assert runs == [8081, 9090]  # 热重启
        await root.fiber.dispose()

    async def test_intercept_chain(self):
        root = Context()

        class Mailer(Service):
            provide = 'mailer'

            def __init__(self, ctx):
                super().__init__(ctx)
                self.settings = self.resolve_config(base={'a': 1, 'b': 1})

        deep = root.intercept('mailer', {'b': 2}).intercept('mailer', {'c': 3})
        await deep.plugin(Mailer)
        assert root.get('mailer').settings == {'a': 1, 'b': 2, 'c': 3}
        await root.fiber.dispose()

    # ------------------------------------------------------------ services

    async def test_set_only_by_provider(self):
        root = Context()
        box = {'value': 1}

        class Box(Service):
            provide = 'box'

            def __init__(self, ctx):
                super().__init__(ctx)
                self.value = 1

        fb = root.plugin(Box)
        await fb

        def other(ctx):
            pass

        fo = root.plugin({'apply': other, 'inject': ['box'], 'name': 'o'})
        await fo
        with self.assertRaises(RuntimeError):
            fo.ctx.box = object()  # 非提供者不能 set
        fb.ctx.box = object()      # 提供者可以
        await root.fiber.dispose()

    async def test_provide_conflict_and_reprovide(self):
        root = Context()
        fb = root.plugin(type('S', (Service,), {'provide': 'dup', '__init__':
                       lambda self, ctx: Service.__init__(self, ctx)}))
        await fb
        with self.assertRaises(RuntimeError):
            root.provide('dup', object())
        await fb.dispose()
        root.provide('dup', 'second')  # 卸载后可再注册
        assert root.get('dup') == 'second'
        await root.fiber.dispose()

    async def test_accessor(self):
        root = Context()
        f = root.plugin(lambda ctx: ctx.accessor('answer', lambda c: 42))
        await f
        assert f.ctx.answer == 42
        await f.dispose()
        with self.assertRaises(AttributeError):
            root.answer  # accessor 随 fiber 卸载消失

    async def test_get_strict(self):
        root = Context()
        marker = object()

        async def provider(ctx):
            ctx.provide('late', marker)
            await asyncio.sleep(0.05)   # 停留在 LOADING 窗口

        fb = root.plugin(provider)
        await asyncio.sleep(0.01)
        # provider LOADING：注册可见（loose）但依赖不可用（strict）
        assert root.get('late', strict=False) is marker
        assert root.get('late', strict=True) is None
        await fb
        # ACTIVE 之后 strict 也可见
        assert root.get('late', strict=True) is marker
        await root.fiber.dispose()

    # -------------------------------------------------------------- loader

    async def test_loader_lifecycle(self):
        root = Context()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / 'a.py').write_text(
                'from mini_cordis import Service\n'
                'class A(Service):\n'
                '    provide = "a"\n'
                'plugin = A\n', encoding='utf-8')
            (tmp / 'b.py').write_text(
                'inject = ["a"]\n'
                'LOADS = []\n'
                'def plugin(ctx, config):\n'
                '    LOADS.append(config)\n', encoding='utf-8')
            (tmp / 'off.py').write_text(
                'def plugin(ctx):\n    raise AssertionError("must not load")\n',
                encoding='utf-8')
            cfg = tmp / 'app.json'
            cfg.write_text(json.dumps([
                {'id': 'a', 'module': './a.py'},
                {'id': 'b', 'module': './b.py', 'config': {'x': 1}},
                {'id': 'off', 'module': './off.py', 'disabled': True},
            ]), encoding='utf-8')
            fibers = await root.loader.load(str(cfg))
            assert set(root.loader.fibers) == {'a', 'b'}
            assert fibers[1].state == FiberState['ACTIVE']

            assert await root.loader.reload('b') is True
            assert await root.loader.dispose('a') is True
            # a 卸载后 b 依赖缺失 → PENDING
            assert fibers[1].state == FiberState['PENDING']
            await root.fiber.dispose()

    # ------------------------------------------------------------ registry

    async def test_registry_delete_disposes_fibers(self):
        root = Context()
        log = []

        def P(ctx):
            return lambda: log.append('-')

        f1 = root.plugin(P)
        await f1
        await root.registry.delete(P)
        assert log == ['-']
        assert P not in root.registry

    async def test_restart_and_failed_retry_on_dependency_change(self):
        root = Context()
        runs = []

        def boom(ctx):
            runs.append(1)
            raise RuntimeError('boom')

        f = root.plugin(boom)
        with self.assertRaises(RuntimeError):
            await f
        assert f.state == FiberState['FAILED'] and runs == [1]

        # 依赖未变不会自动重试；restart 强制重试
        with self.assertRaises(RuntimeError):
            await f.restart()
        assert runs == [1, 1]
        await f.dispose()
        await root.fiber.dispose()


if __name__ == '__main__':
    unittest.main(verbosity=2)
