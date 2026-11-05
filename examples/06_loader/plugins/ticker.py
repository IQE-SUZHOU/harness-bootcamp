"""插件：注入 clock + logger，周期打点。

演示【异步生成器 effect】作为插件返回值：
  - 每次 yield 出一个 disposer，卸载时逐个执行
  - 插件体的异步 setup 全部完成后，fiber 才进入 ACTIVE（对齐 cordis _execute）
"""

import asyncio

inject = ['clock', 'logger']


def plugin(ctx, config):
    log = ctx.logger('ticker')

    async def beats():
        for i in range(config['ticks']):
            await asyncio.sleep(0.02)
            n = ctx.clock.now()
            log.info('tick %s', n)

            def undo(i=i, n=n):
                log.info('rollback tick %s (was %s)', i, n)

            yield undo

    return beats()
