"""
01_quickstart.py —— cordis README 快速上手的 Python 移植

演示最小闭环：Service 注册 → inject 依赖 → 事件派发 → 卸载清理。
运行：python3 examples/01_quickstart.py
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mini_cordis import Context, Service  # noqa: E402


class Counter(Service):
    provide = 'counter'

    def __init__(self, ctx: Context):
        super().__init__(ctx)
        self._counter = 0

    def incr(self):
        self._counter += 1


def greeter(ctx: Context):
    # 通过 ctx 属性直接读取已注入的服务（__getattr__ 解析）
    ctx.on('app/ready', lambda message: ctx.logger('greeter').info(
        '%s, count = %s', message, ctx.counter._counter))


async def main():
    root = Context()
    await root.plugin(Counter)
    greeter_with_inject = {'apply': greeter, 'inject': ['counter'], 'name': 'greeter'}
    await root.plugin(greeter_with_inject)

    root.emit('app/ready', 'started')

    await root.fiber.dispose()  # 级联卸载全部插件


if __name__ == '__main__':
    asyncio.run(main())
