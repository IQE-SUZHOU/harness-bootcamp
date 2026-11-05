"""
04_events.py —— 事件总线五种派发模式

对应 cordis-tutorial 04-events：
  emit      同步触发；协程监听器后台调度（fire-and-forget）
  parallel  并发 await 全部监听器
  serial    顺序 await；监听器返回"否决值"（非 None/False）即停
  bail      serial 的同步版（监听器必须同步）
  waterfall 责任链：监听器收 next 关键字参数，改写参数继续传
运行：python3 examples/04_events.py
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mini_cordis import Context  # noqa: E402


async def main():
    root = Context()
    log = root.logger('04')
    order = []

    # ---- emit：fire-and-forget
    def l_sync(msg):
        order.append(f'sync:{msg}')

    async def l_async(msg):
        await asyncio.sleep(0.01)
        order.append(f'async:{msg}')

    root.on('ping', l_sync)
    root.on('ping', l_async)
    root.emit('ping', 'x')
    assert order == ['sync:x'], order          # 同步监听器立即执行
    await asyncio.sleep(0.05)
    assert order == ['sync:x', 'async:x'], order  # 异步监听器随后完成
    log.info('emit: %s ✓', order)

    # ---- serial：否决即停（bail 判定：非 None/False 即否决）
    async def veto_a(msg):
        order.append('veto_a')
        return 'blocked-by-a'                  # 否决值

    async def never(msg):
        order.append('never!')

    root.on('guard', veto_a)
    root.on('guard', never)
    result = await root.serial('guard', 'req')
    assert result == 'blocked-by-a' and 'never!' not in order
    log.info('serial: 否决值=%s，后续监听器未执行 ✓', result)

    # ---- bail：同步监听器
    root.emit('bailing-test', 'noop')          # 无监听器也安全
    def sync_ok(m): return None
    def sync_stop(m): return {'code': 403}
    fiber = root.inject([], lambda ctx: None)
    ctx = fiber.ctx
    ctx.on('auth', sync_ok)
    ctx.on('auth', sync_stop)
    ctx.on('auth', lambda m: order.append('auth-never!'))
    stopped = ctx.bail('auth', 'user')
    assert stopped == {'code': 403}
    log.info('bail: 同步短路返回 %s ✓', stopped)
    await fiber.dispose()

    # ---- waterfall：责任链改写参数
    async def add_header(*args, next):
        headers = dict(args[0])
        headers['x-trace'] = 'trace-1'
        return await next(headers)

    async def add_auth(*args, next):
        headers = dict(args[0])
        headers['authorization'] = 'Bearer ***'
        return await next(headers)

    root.on('http.request', add_header)
    root.on('http.request', add_auth)
    final = await root.waterfall('http.request', {},
                                 lambda h: dict(h, handled=True))
    assert final == {'x-trace': 'trace-1', 'authorization': 'Bearer ***', 'handled': True}
    log.info('waterfall: %s ✓', final)

    # ---- 生命周期：插件卸载 → 它的监听器自动摘除
    def listener_plugin(c):
        c.on('ping', lambda m: order.append('plugin-listener!'))

    before = len(root.events.listeners('ping'))
    fp = await root.plugin(listener_plugin)
    assert len(root.events.listeners('ping')) == before + 1
    await fp.dispose()
    assert len(root.events.listeners('ping')) == before
    order.clear()
    root.emit('ping', 'after')
    await asyncio.sleep(0.02)
    assert 'plugin-listener!' not in order
    log.info('插件卸载后其监听器自动摘除 ✓')

    await root.fiber.dispose()


if __name__ == '__main__':
    asyncio.run(main())
