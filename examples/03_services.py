"""
03_services.py —— 服务的动态可用性（cordis 的灵魂）

演示（对应 cordis-tutorial 03-services）：
  - 依赖缺失时插件不报错，只是 PENDING；provider 出现的那一刻自动激活
  - provider 卸载 → 依赖者退回 PENDING；provider 恢复 → 再激活
  - check 谓词：服务"活着但暂不可用"（如数据库断线）同样能惊动依赖者
  - 依赖被"替换"（dispose 后重新 provide 新实现）→ 依赖者重载
运行：python3 examples/03_services.py
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mini_cordis import Context, Service  # noqa: E402

LOG = []


class Bus(Service):
    """一个带可用性谓词的服务：connected 为假时依赖者不可用它。"""

    provide = 'bus'

    def __init__(self, ctx: Context):
        super().__init__(ctx)
        self.connected = False

    def check(self) -> bool:          # ← 约定：check() 为假 = 暂不可用
        return self.connected

    def send(self, msg):
        LOG.append(f'bus:send {msg}')


def consumer(ctx: Context):
    """声明 inject bus —— bus 不可用时本插件整体不激活。"""
    LOG.append('consumer:LOAD')
    ctx.on('tick', lambda: ctx.bus.send('tick'))
    return lambda: LOG.append('consumer:unload')


async def main():
    root = Context()
    log = root.logger('03')

    # 1. 先加载依赖者：bus 不存在 → PENDING，不报错
    fc = root.plugin({'apply': consumer, 'inject': ['bus'], 'name': 'consumer'})
    await asyncio.sleep(0)
    log.info('步骤1 consumer 状态=%s（等 bus）', fc.state)
    assert fc.state == 0  # PENDING

    # 2. bus 出现但 check() 为假 → 仍然 PENDING
    fb = root.plugin(Bus)
    await fb
    await asyncio.sleep(0)
    log.info('步骤2 bus ACTIVE 但 connected=False → consumer=%s', fc.state)
    assert fc.state == 0

    # 3. connected=True → notify → consumer 自动激活
    bus: Bus = root.get('bus')
    bus.connected = True
    root.reflect.notify(['bus'])       # 业务侧状态翻转后主动惊动依赖者
    await fc
    log.info('步骤3 connected=True → consumer=%s（自动激活）', fc.state)
    assert fc.state == 2  # ACTIVE

    root.emit('tick')
    assert LOG[-1] == 'bus:send tick'

    # 4. bus 卸载 → consumer 退回 PENDING
    await fb.dispose()
    await fc
    log.info('步骤4 bus 卸载 → consumer=%s', fc.state)
    assert fc.state == 0

    # 5. 重新 provide 一个新 bus → consumer 用新实现再激活
    #    注意：provide 发生在 super().__init__() 内部，此刻 connected 还没置位，
    #    check() 仍为假 —— 业务状态翻转后必须 reflect.notify 惊动依赖者。
    bus2 = Bus(root.fiber.ctx)
    bus2.connected = True
    root.reflect.notify(['bus'])
    await fc
    log.info('步骤5 新 bus → consumer=%s', fc.state)
    assert fc.state == 2
    root.emit('tick')

    log.info('LOG=%s', LOG)
    await root.fiber.dispose()
    log.info('依赖动态编排演示完成 ✓')


if __name__ == '__main__':
    asyncio.run(main())
