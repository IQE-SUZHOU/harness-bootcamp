"""插件：mini-kv 网络 API（asyncio TCP 行协议）。

演示：
  - inject 依赖（kvstore / logger）
  - 服务端资源随 effect 清理（server.close + wait_closed）
  - provide 'api' 供宿主读取实际监听地址
"""

import asyncio

inject = ['kvstore', 'logger']


class ApiService:
    def __init__(self, server, addr):
        self.server = server
        self.addr = addr   # (host, port)


async def plugin(ctx, config):
    log = ctx.logger('api')
    port = (config or {}).get('port', 0)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info('peername')
        log.info('client connected %s', peer)
        writer.write(b'mini-kv 1.0\r\n')
        await writer.drain()
        while True:
            line = await reader.readline()
            if not line:
                break
            parts = line.decode('utf-8', 'replace').strip().split(' ', 2)
            if not parts or not parts[0]:
                continue
            cmd = parts[0].upper()
            if cmd == 'PING':
                resp = 'PONG'
            elif cmd == 'SET' and len(parts) == 3:
                evicted = ctx.kvstore.set(parts[1], parts[2])
                resp = f'OK evicted:{evicted}' if evicted else 'OK'
            elif cmd == 'GET' and len(parts) == 2:
                value = ctx.kvstore.get(parts[1])
                resp = value if value is not None else 'NIL'
            elif cmd == 'DEL' and len(parts) == 2:
                resp = 'OK' if ctx.kvstore.delete(parts[1]) else 'NIL'
            elif cmd == 'KEYS':
                keys = ctx.kvstore.keys()
                resp = ' '.join(keys) if keys else 'EMPTY'
            elif cmd == 'QUIT':
                writer.write(b'BYE\r\n')
                break
            else:
                resp = 'ERR syntax'
            writer.write((resp + '\r\n').encode())
            await writer.drain()
        writer.close()
        log.info('client left %s', peer)

    server = await asyncio.start_server(handle, '127.0.0.1', port)
    addr = server.sockets[0].getsockname()
    log.info('listening on %s:%s', *addr)
    ctx.provide('api', ApiService(server, addr))

    async def cleanup():
        server.close()
        await server.wait_closed()
        log.info('server closed')

    return cleanup
