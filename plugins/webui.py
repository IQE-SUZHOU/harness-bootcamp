"""webui 插件 —— mini-harness 的完整 Web 界面（stdlib asyncio，零依赖）。

能力：
  - 会话面板：列表（状态徽标 active/interrupted/closed）、新建、打开(恢复)、结束
  - 聊天：调用 ctx.agent.chat，展示 tool_calls/工具结果/最终回复；支持中断
  - 实时事件流：SSE（session/message、agent/tool、agent/finished、
    agent/interrupted、session/status、session/closed）
  - 单飞约束：同一时间只允许一轮 chat（HTTP 409 busy），interrupt 解除

HTTP API（同源，无跨域）：
  GET  /                        单页 UI
  GET  /api/state               {llm, tools, sessions, current}
  POST /api/chat                {prompt, session_id?} → {ok, result}
  POST /api/interrupt           → {interrupted}
  POST /api/sessions            {title?} → 新建并打开
  POST /api/sessions/open       {id} → {meta, messages}
  POST /api/sessions/close      {id}
  GET  /api/session/messages?id=
  GET  /api/events              SSE
配置：{'host': '127.0.0.1', 'port': 8899}（port 0 = 随机，实际端口看日志/webui 服务）
"""

import asyncio
import json
from http import HTTPStatus
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs

inject = ['agent', 'session']

_PAGE = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>mini-harness</title><style>
:root{--bg:#0f1115;--panel:#171a21;--line:#252a35;--tx:#d7dce5;--dim:#8b93a5;
--acc:#4f8cff;--ok:#3fb26f;--warn:#e0a33e;--user:#22344f}
*{box-sizing:border-box}body{margin:0;font:14px/1.6 system-ui,'Segoe UI',sans-serif;
background:var(--bg);color:var(--tx);display:flex;height:100vh}
#side{width:250px;border-right:1px solid var(--line);display:flex;flex-direction:column}
#side h3{margin:12px 14px 6px;font-size:12px;color:var(--dim);font-weight:600}
#list{flex:1;overflow:auto;padding:0 8px}
.sitem{padding:8px 10px;border-radius:8px;cursor:pointer;margin-bottom:4px;
border:1px solid transparent}
.sitem:hover{background:var(--panel)}.sitem.on{border-color:var(--acc);background:var(--panel)}
.sitem .t{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sitem .m{font-size:11px;color:var(--dim)}
.badge{font-size:10px;padding:1px 6px;border-radius:8px;margin-right:6px}
.active{background:#12331f;color:var(--ok)}.interrupted{background:#3a2c12;color:var(--warn)}
.closed{background:#22262e;color:var(--dim)}
#sbtns{display:flex;gap:6px;padding:10px}
main{flex:1;display:flex;flex-direction:column;min-width:0}
#top{padding:10px 16px;border-bottom:1px solid var(--line);font-size:12px;color:var(--dim)}
#msgs{flex:1;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:78%;padding:8px 12px;border-radius:10px;white-space:pre-wrap;word-break:break-word}
.user{align-self:flex-end;background:var(--user)}
.assistant{align-self:flex-start;background:var(--panel)}
.toolcall{align-self:flex-start;background:#241d33;color:#b9a7ff;font-size:12px}
details.tool{align-self:flex-start;max-width:78%;background:#10131a;border:1px solid var(--line);
border-radius:8px;font:12px/1.5 ui-monospace,monospace;color:#9aa5b8}
details.tool summary{cursor:pointer;padding:4px 10px}
details.tool pre{margin:0;padding:0 12px 8px;overflow:auto;max-height:220px}
#feed{border-top:1px solid var(--line);padding:6px 16px;font-size:11px;color:var(--dim);
max-height:88px;overflow:auto}
#inbar{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--line)}
#in{flex:1;background:var(--panel);border:1px solid var(--line);border-radius:8px;
color:var(--tx);padding:10px 12px;font:14px inherit;outline:none}
#in:focus{border-color:var(--acc)}
button{background:var(--panel);border:1px solid var(--line);color:var(--tx);
border-radius:8px;padding:8px 14px;cursor:pointer}
button:hover{border-color:var(--acc)}button.warn:hover{border-color:#c0564f}
button:disabled{opacity:.4;cursor:default}
</style></head><body>
<div id="side"><h3>会话 SESSIONS</h3><div id="list"></div>
<div id="sbtns"><button onclick="newS()">＋ 新建</button>
<button class="warn" onclick="closeS()">结束</button></div></div>
<main><div id="top">加载中…</div><div id="msgs"></div><div id="feed"></div>
<div id="inbar"><input id="in" placeholder="输入内容，Enter 发送；run: 命令 触发 bash（fake 驱动）"
 onkeydown="if(event.key==='Enter'&&!event.isComposing)send()">
<button id="sendB" onclick="send()">发送</button>
<button id="intB" class="warn" onclick="interrupt()" disabled>中断</button></div></main>
<script>
let cur=null,pending=false;
const $=id=>document.getElementById(id);
const api=(p,b)=>fetch('/api/'+p,{method:b?'POST':'GET',
  headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined})
  .then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||r.status);return j});
function esc(s){return(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function badge(s){return `<span class="badge ${s}">${s}</span>`}
async function refresh(open){
  const st=await api('state');$('top').innerHTML=
   `LLM: <b>${esc(st.llm.provider||st.llm.driver||'?')}</b> · ${esc(st.llm.model||'')} · 工具: ${st.tools.join(', ')||'无'}`;
  $('list').innerHTML=(st.sessions||[]).map(s=>
   `<div class="sitem${s.id===cur?' on':''}" onclick="openS('${s.id}')">
    <div class="t">${esc(s.title||s.id)}</div>
    <div class="m">${badge(s.status)} ${s.messages} 条</div></div>`).join('');
  if(open&&cur)loadMsgs();}
function render(ms){$('msgs').innerHTML=ms.map(m=>{
  if(m.role==='user')return `<div class="msg user">${esc(m.content)}</div>`;
  let h='';
  for(const tc of (m.tool_calls||[])){const f=tc.function||{};let a=f.arguments||'';
    try{a=JSON.parse(a).command||a}catch(e){}
    h+=`<div class="msg toolcall">🔧 ${esc(f.name)}: ${esc(String(a).slice(0,200))}</div>`}
  if(m.content)h+=`<div class="msg assistant">${esc(m.content)}</div>`;
  return h||''}).join('');
  $('msgs').scrollTop=$('msgs').scrollHeight;}
async function loadMsgs(){if(!cur)return;const r=await api('session/messages?id='+cur);
  render(r.messages||[]);$('top').innerHTML+=' · '+badge(r.meta.status)+` ${esc(r.meta.title||cur)}`;}
async function openS(id){cur=id;await refresh(0);loadMsgs();}
async function newS(){const r=await api('sessions',{title:''});cur=r.id;await refresh(0);$('msgs').innerHTML='';}
async function closeS(){if(!cur)return;if(!confirm('结束当前会话？（终态，只读）'))return;
  await api('sessions/close',{id:cur});await refresh(1);}
async function send(){const t=$('in').value.trim();if(!t||pending)return;
  $('in').value='';pend(1);appendLocal(`<div class="msg user">${esc(t)}</div>`);
  try{const r=await api('chat',{prompt:t});
    const res=r.result;
    appendLocal(res.interrupted?'<div class="msg toolcall">⏹ 已中断</div>'
      :`<div class="msg assistant">${esc(res.final)}</div>`
       +`<div class="m" style="font-size:11px;color:var(--dim);align-self:flex-start">${res.turns} 轮</div>`);
  }catch(e){appendLocal(`<div class="msg toolcall">⚠ ${esc(e.message)}</div>`)}
  finally{pend(0);refresh(0);}}
function appendLocal(h){$('msgs').insertAdjacentHTML('beforeend',h);$('msgs').scrollTop=1e9;}
function pend(p){pending=p;$('sendB').disabled=p;$('intB').disabled=!p;}
function interrupt(){api('interrupt').catch(()=>{});}
function feed(s){const d=document.createElement('div');d.textContent=s;
  $('feed').appendChild(d);while($('feed').children.length>40)$('feed').removeChild($('feed').firstChild);}
try{const es=new EventSource('/api/events');es.onmessage=e=>{const x=JSON.parse(e.data);
  if(x.event==='agent/tool')feed('🔧 工具 '+x.args[1]+' 完成');
  else if(x.event==='session/status')feed('◐ 会话状态 → '+x.args[1]);
  else if(x.event==='agent/interrupted')feed('⏹ 对话被中断');
  else if(x.event==='session/closed')feed('■ 会话已结束');};}catch(e){}
refresh(0);
</script></body></html>"""


async def _read_request(reader):
    line = await reader.readline()
    if not line:
        return None, None, None, {}
    parts = line.decode('latin-1').split()
    if len(parts) < 2:
        return None, None, None, {}
    method, target = parts[0], parts[1]
    headers = {}
    while True:
        ln = await reader.readline()
        if ln in (b'\r\n', b'\n', b''):
            break
        k, _, v = ln.decode('latin-1').partition(':')
        headers[k.strip().lower()] = v.strip()
    body = b''
    n = int(headers.get('content-length', 0) or 0)
    if n:
        body = await reader.readexactly(n)
    return method, target, body, headers


async def _respond(writer, status: int, ctype: str, body: bytes):
    head = (f'HTTP/1.1 {status} {HTTPStatus(status).phrase}\r\n'
            f'Content-Type: {ctype}\r\nContent-Length: {len(body)}\r\n'
            'Connection: close\r\nCache-Control: no-store\r\n\r\n')
    writer.write(head.encode('latin-1') + body)
    await writer.drain()


async def _json(writer, obj, status=200):
    await _respond(writer, status, 'application/json; charset=utf-8',
                   json.dumps(obj, ensure_ascii=False, default=str).encode('utf-8'))


def plugin(ctx, config=None):
    cfg = config or {}
    host, port = cfg.get('host', '127.0.0.1'), cfg.get('port', 8899)
    chat_lock = asyncio.Lock()

    # ------------------------------------------------------------ SSE

    async def _sse(writer):
        q: asyncio.Queue = asyncio.Queue()
        offs = []
        for ev in ('session/message', 'agent/tool', 'agent/finished',
                   'agent/interrupted', 'session/status', 'session/closed'):
            offs.append(ctx.on(ev, lambda *a, _e=ev: q.put_nowait(
                {'event': _e, 'args': a})))
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n'
                     b'Cache-Control: no-store\r\nConnection: close\r\n\r\n')
        await writer.drain()
        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), 15)
                    writer.write(f'data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n'
                                 .encode('utf-8'))
                except (TimeoutError, asyncio.TimeoutError):
                    writer.write(b': ping\n\n')
                await writer.drain()
        except (ConnectionError, OSError, asyncio.CancelledError):
            pass
        finally:
            for off in offs:
                try:
                    off()
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------ 路由

    async def _handle_chat(writer, body):
        if chat_lock.locked():
            return await _json(writer, {'error': 'busy：上一轮对话进行中'}, 409)
        async with chat_lock:
            try:
                req = json.loads(body or b'{}')
                prompt = (req.get('prompt') or '').strip()
                if not prompt:
                    return await _json(writer, {'error': '缺少 prompt'}, 400)
                sid = req.get('session_id')
                cur = ctx.session.peek()
                if sid:
                    sess = cur if cur and cur.id == sid else ctx.session.open(sid)
                else:
                    sess = cur if cur and cur.status != 'closed' \
                        else ctx.session.create()
                result = await ctx.agent.chat(prompt, session=sess)
                cur = ctx.session.peek()
                return await _json(writer, {'ok': True, 'result': result,
                                            'session_id': cur.id if cur else None})
            except Exception as e:  # noqa: BLE001
                status = 409 if type(e).__name__ == 'SessionClosed' else 500
                return await _json(writer, {'error': f'{type(e).__name__}: {e}'}, status)

    async def _handle(reader, writer):
        try:
            method, target, body, _h = await _read_request(reader)
            if method is None:
                return
            u = urlparse(target)
            path, qs = u.path, parse_qs(u.query)
            if method == 'GET' and path == '/':
                return await _respond(writer, 200, 'text/html; charset=utf-8',
                                      _PAGE.encode('utf-8'))
            if method == 'GET' and path == '/api/events':
                return await _sse(writer)
            if method == 'GET' and path == '/api/state':
                llm = ctx.get('llm', strict=False)
                return await _json(writer, {
                    'llm': getattr(llm, 'info', {}),
                    'tools': ctx.tools.names() if ctx.get('tools', strict=False) else [],
                    'sessions': ctx.session.list(),
                    'current': ctx.session.peek().id if ctx.session.peek() else None})
            if method == 'GET' and path == '/api/session/messages':
                sid = (qs.get('id') or [''])[0]
                cur = ctx.session.current()
                sess = cur if cur and cur.id == sid else ctx.session.open(sid)
                return await _json(writer, {'meta': sess.meta,
                                            'messages': sess.messages})
            if method == 'POST' and path == '/api/chat':
                return await _handle_chat(writer, body)
            if method == 'POST' and path == '/api/interrupt':
                return await _json(writer, {'interrupted': ctx.agent.interrupt()})
            if method == 'POST' and path == '/api/sessions':
                req = json.loads(body or b'{}')
                sess = ctx.session.create(req.get('title', ''))
                return await _json(writer, {'id': sess.id})
            if method == 'POST' and path == '/api/sessions/open':
                req = json.loads(body or b'{}')
                sess = ctx.session.open(req['id'])
                return await _json(writer, {'meta': sess.meta,
                                            'messages': sess.messages})
            if method == 'POST' and path == '/api/sessions/close':
                req = json.loads(body or b'{}')
                ctx.session.close(req['id'])
                return await _json(writer, {'ok': True})
            return await _json(writer, {'error': 'not found'}, 404)
        except Exception as e:  # noqa: BLE001
            try:
                await _json(writer, {'error': f'{type(e).__name__}: {e}'}, 400)
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                await writer.drain()
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ 启动（协程插件：await 完成后才 ACTIVE）

    async def setup():
        server = await asyncio.start_server(_handle, host, port)
        real = server.sockets[0].getsockname()[1]
        info = SimpleNamespace(server=server, host=host, port=real,
                               url=f'http://{host}:{real}')
        ctx.provide('webui', info)
        ctx.logger('webui').info('mini-harness UI → %s', info.url)
        return lambda: server.close()      # 协程返回值 = 插件 disposer

    return setup()
