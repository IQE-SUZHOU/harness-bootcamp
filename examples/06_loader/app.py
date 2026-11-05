"""
06_loader —— 配置驱动的插件装配（@cordisjs/plugin-loader 最小版）

app.json 列出插件条目（module/config/disabled），ctx.loader.load() 一次性装配。
运行：python3 examples/06_loader/app.py
"""

import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402


async def main():
    root = Context()
    log = root.logger('06')

    fibers = await root.loader.load(str(pathlib.Path(__file__).parent / 'app.json'))
    log.info('已加载 %s：disabled 条目被跳过 ✓', list(root.loader.fibers))
    assert set(root.loader.fibers) == {'clock', 'ticker'}

    # reload 演示：重启 ticker（其异步生成器体会重新打点）
    await root.loader.reload('ticker')
    log.info('reload ticker 完成 ✓')

    await root.fiber.dispose()
    log.info('loader 演示结束 ✓')


if __name__ == '__main__':
    asyncio.run(main())
