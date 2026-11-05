"""webui 插件验收：页面、状态 API、聊天/会话管理、单飞+中断、SSE 事件流。"""

import asyncio
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mini_cordis import Context  # noqa: E402
from run import prepare_profile  # noqa: E402


async def http(port, method, path, body=None, timeout=10):
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    data = json.dumps(body).encode() if body is not None else b''
    head = (f'{method} {path} HTTP/1.1\r\nHost: x\r\n'
            f'Content-Type: application/json\r\nContent-Length: {len(data)}\r\n'
            'Connection: close\r\n\r\n').encode()
    writer.write(head + data)
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(), timeout)
    writer.close()
    hdr, _, payload = raw.partition(b'\r\n\r\n')
    return int(hdr.split(b' ')[1]), payload


class WebuiTest(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix='webui-test-'))

    async def asyncTearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def _boot(self):
        eff = prepare_profile('web', data_dir=str(self.tmp),
                              overrides=['llm.driver="fake"', 'webui.port=0'])
        root = Context()
        await root.loader.load(str(eff))
        return root

    async def test_page_and_state(self):
        root = await self._boot()
        try:
            port = root.get('webui').port
            st, body = await http(port, 'GET', '/')
            assert st == 200 and b'mini-harness' in body and b'EventSource' in body
            st, body = await http(port, 'GET', '/api/state')
            j = json.loads(body)
            assert st == 200 and j['llm']['driver'] == 'fake'
            assert j['tools'] == ['bash'] and j['sessions'] == []
            assert j['current'] is None                  # 状态查询不创建会话
        finally:
            await root.fiber.shutdown()

    async def test_chat_sessions_and_close(self):
        root = await self._boot()
        try:
            port = root.get('webui').port
            st, body = await http(port, 'POST', '/api/chat',
                                  {'prompt': 'run: echo web-ok'})
            j = json.loads(body)
            assert st == 200 and j['ok'] and 'web-ok' in j['result']['final']
            sid = j.get('session_id') or root.get('session').current().id
            st, body = await http(port, 'GET', '/api/state')
            rows = json.loads(body)['sessions']
            assert len(rows) == 1 and rows[0]['status'] == 'active'
            st, body = await http(port, 'GET', f'/api/session/messages?id={sid}')
            j = json.loads(body)
            assert st == 200 and j['meta']['status'] == 'active'
            assert [m['role'] for m in j['messages']] == \
                ['user', 'assistant', 'tool', 'assistant']
            st, _ = await http(port, 'POST', '/api/sessions/close', {'id': sid})
            assert st == 200
            # closed 会话继续聊天 → 4xx，消息不丢
            st, body = await http(port, 'POST', '/api/chat',
                                  {'prompt': 'hi', 'session_id': sid})
            assert st in (400, 409) and 'closed' in body.decode().lower()
            st, body = await http(port, 'GET', f'/api/session/messages?id={sid}')
            assert len(json.loads(body)['messages']) == 4
        finally:
            await root.fiber.shutdown()

    async def test_busy_409_and_interrupt(self):
        root = await self._boot()
        try:
            port = root.get('webui').port

            class NeverLLM:
                async def chat(self, messages, tools):
                    await asyncio.sleep(30)
                    return {'role': 'assistant', 'content': 'never'}

            root.get('agent').llm = NeverLLM()
            first = asyncio.ensure_future(
                http(port, 'POST', '/api/chat', {'prompt': '长任务'}))
            await asyncio.sleep(0.3)
            st, _ = await http(port, 'POST', '/api/chat', {'prompt': '插队'})
            assert st == 409                              # 单飞约束
            st, body = await http(port, 'POST', '/api/interrupt')
            assert st == 200 and json.loads(body)['interrupted'] is True
            st, body = await asyncio.wait_for(first, 5)
            j = json.loads(body)
            assert st == 200 and j['result']['interrupted'] is True
            assert root.get('session').current().status == 'interrupted'
        finally:
            await root.fiber.shutdown()

    async def test_sse_event_stream(self):
        root = await self._boot()
        try:
            port = root.get('webui').port
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.write(b'GET /api/events HTTP/1.1\r\nHost: x\r\n\r\n')
            await writer.drain()
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            assert b'text/event-stream' in head
            # SSE 建立后发生一轮对话 → 事件流里应出现 session/message / agent/tool
            await asyncio.wait_for(http(
                port, 'POST', '/api/chat', {'prompt': 'run: echo sse-ok'}), 10)
            buf = b''
            for _ in range(20):
                buf += await asyncio.wait_for(reader.read(4096), 5)
                if b'agent/finished' in buf:
                    break
            assert b'session/message' in buf and b'agent/tool' in buf
            writer.close()
        finally:
            await root.fiber.shutdown()

    async def test_404_and_bad_route(self):
        root = await self._boot()
        try:
            port = root.get('webui').port
            st, body = await http(port, 'GET', '/api/nope')
            assert st == 404
        finally:
            await root.fiber.shutdown()


if __name__ == '__main__':
    unittest.main(verbosity=2)
