"""
02_lifecycle.py —— effect / 清理 / 级联卸载

演示（对应 cordis-tutorial 02-lifecycle-and-effects）：
  - effect 的全部形状：disposer 函数 / 生成器 / 协程 / 异步 disposer
  - 同一 effect 内 disposer 逆序执行
  - 子插件随父插件卸载（级联），子先于父清理
  - get_effects() 诊断树
运行：python3 examples/02_lifecycle.py
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mini_cordis import Context  # noqa: E402

LOG = []


def plugin_a(ctx: Context):
    """生成器 effect：每次 yield 一个 disposer，卸载时逆序执行。"""
    LOG.append('a:load')

    def gen():
        LOG.append('a:effect-1')
        yield lambda: LOG.append('a:dispose-1')
        LOG.append('a:effect-2')
        yield lambda: LOG.append('a:dispose-2')

    return gen()


class PluginB:
    """class 插件：init 钩子的返回值按 effect 收集。"""

    def __init__(self, ctx: Context, config):
        self.ctx = ctx
        LOG.append(f'b:ctor config={config}')

    def init(self):
        LOG.append('b:init')
        return lambda: LOG.append('b:dispose')


async def plugin_c(ctx: Context):
    """协程插件体 + 异步 disposer。"""
    await asyncio.sleep(0.01)
    LOG.append('c:load')

    async def cleanup():
        await asyncio.sleep(0.01)
        LOG.append('c:dispose')

    return cleanup


def parent_plugin(ctx: Context):
    """在插件内部加载子插件：子生命周期归属本 fiber。"""
    LOG.append('parent:load')

    async def child(c: Context):
        LOG.append('child:load')
        return lambda: LOG.append('child:unload')

    fiber = ctx.plugin(child)
    return lambda: LOG.append('parent:unload')


async def main():
    root = Context()
    fa = await root.plugin(plugin_a)
    fb = await root.plugin(PluginB, {'hello': True})
    fc = await root.plugin(plugin_c)
    fp = await root.plugin(parent_plugin)

    ctx_logger = root.logger('02')
    ctx_logger.info('get_effects(): %s', fp.get_effects())

    LOG.clear()
    await fp.dispose()
    # 与 cordis 相同：effect 之间并发清理（Promise.all 语义）；
    # 保证点是 dispose() 返回时子插件已彻底卸载
    ctx_logger.info('父卸载后 LOG=%s（dispose 返回时子已级联卸载完）', LOG)

    LOG.clear()
    await fa.dispose()
    ctx_logger.info('生成器 effect 逆序：LOG=%s', LOG)

    await fb.dispose()
    await fc.dispose()
    await root.fiber.dispose()
    ctx_logger.info('全部卸载完成 ✓')


if __name__ == '__main__':
    asyncio.run(main())
