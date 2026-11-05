"""
07_minikv —— 综合应用：一个带网络接口的 KV 服务

装配全部核心机制：
  loader 按 JSON 配置装配 → store(Service+Config校验) → api(inject 依赖+TCP 服务器)
  → audit(事件监听) ；宿主连接做协议演示；插件可单独热卸载。

运行：python3 examples/07_minikv/app.py
"""

import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402


async def main():
    root = Context()
    log = root.logger('app')

    await root.loader.load(str(pathlib.Path(__file__).parent / 'app.json'))
    api = root.get('api')
    host, port = api.addr

    reader, writer = await asyncio.open_connection(host, port)
    banner = (await reader.readline()).decode().strip()
    log.info('banner: %s', banner)

    async def cmd(line: str) -> str:
        writer.write(f'{line}\r\n'.encode())
        await writer.drain()
        return (await reader.readline()).decode().strip()

    assert await cmd('PING') == 'PONG'
    assert await cmd('SET name mini-cordis') == 'OK'
    assert await cmd('SET color blue') == 'OK'
    assert await cmd('GET name') == 'mini-cordis'
    assert await cmd('SET count 42') == 'OK'
    assert await cmd('SET lang zh') == 'OK evicted:name'   # max_keys=3 FIFO 逐出
    assert await cmd('GET name') == 'NIL'
    assert await cmd('KEYS') == 'color count lang'
    assert await cmd('DEL color') == 'OK'
    assert await cmd('KEYS') == 'count lang'
    assert await cmd('QUIT') == 'BYE'
    writer.close()
    log.info('协议演示完成 ✓')

    # 热卸载 api 插件：服务器随 effect 清理自动关闭
    await root.loader.dispose('api')
    try:
        await asyncio.wait_for(asyncio.open_connection(host, port), 1)
        raise AssertionError('port should be closed')
    except (ConnectionRefusedError, asyncio.TimeoutError):
        log.info('api 插件卸载后端口已关闭 ✓')

    await root.fiber.shutdown()
    log.info('mini-kv 优雅停机 ✓')


if __name__ == '__main__':
    asyncio.run(main())
