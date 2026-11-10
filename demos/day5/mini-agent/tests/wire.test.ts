/**
 * End-to-end test against a local HTTP server that speaks the DeepSeek
 * Messages API wire protocol (SSE frames).
 *
 * This exercises the real fetch path, the SSE decoder, the wire
 * serialization, and the tool-call round trip without needing an API key.
 */

import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'

import { Agent } from '../src/core/agent.ts'
import { ToolRegistry } from '../src/core/tools.ts'
import { DeepSeekAdapter } from '../src/llm/deepseek.ts'
import { createBuiltinTools } from '../src/tools/builtin.ts'

/** One captured request body. */
interface Captured {
  path: string
  headers: Record<string, string | string[] | undefined>
  body: Record<string, unknown>
}

/**
 * Start a mock DeepSeek server that replies with the given SSE frames.
 * @param frames - the SSE data payload for the single response.
 * @returns the base URL, the captured requests, and the stop function.
 */
async function startMock(frames: string[]): Promise<{
  baseURL: string
  requests: Captured[]
  stop: () => Promise<void>
}> {
  const requests: Captured[] = []
  const server = createServer((req, res) => {
    const chunks: Buffer[] = []
    req.on('data', chunk => { chunks.push(chunk as Buffer) })
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8')
      let body: Record<string, unknown> = {}
      try { body = JSON.parse(raw) as Record<string, unknown> } catch (_invalidJson) { body = {} }
      requests.push({ path: req.url ?? '', headers: req.headers, body })
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      for (const frame of frames) {
        res.write(`event: ${frame.event}\ndata: ${frame.data}\n\n`)
      }
      res.end()
    })
  })
  await new Promise<void>(resolve => { server.listen(0, '127.0.0.1', resolve) })
  const address = server.address() as AddressInfo
  return {
    baseURL: `http://127.0.0.1:${address.port}`,
    requests,
    stop: () => new Promise<void>((resolve, reject) => {
      server.close(error => { error === undefined ? resolve() : reject(error) })
    }),
  }
}

test('adapter streams a text response from the wire protocol', async () => {
  const mock = await startMock([
    {
      event: 'message_start',
      data: JSON.stringify({ type: 'message_start', message: { usage: { input_tokens: 12, output_tokens: 0 } } }),
    },
    {
      event: 'content_block_start',
      data: JSON.stringify({ type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }),
    },
    {
      event: 'content_block_delta',
      data: JSON.stringify({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'Hello ' } }),
    },
    {
      event: 'content_block_delta',
      data: JSON.stringify({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'world' } }),
    },
    {
      event: 'content_block_stop',
      data: JSON.stringify({ type: 'content_block_stop', index: 0 }),
    },
    {
      event: 'message_delta',
      data: JSON.stringify({ type: 'message_delta', delta: { stop_reason: 'end_turn' }, usage: { output_tokens: 5 } }),
    },
    { event: 'message_stop', data: JSON.stringify({ type: 'message_stop' }) },
  ])
  try {
    const adapter = new DeepSeekAdapter({ apiKey: 'test-key', baseURL: mock.baseURL })
    const registry = new ToolRegistry()
    const agent = new Agent(adapter, registry, { provider: adapter.provider, model: 'm', systemPrompt: 'sys' })
    const result = await agent.run('hi')
    assert.equal(result.text, 'Hello world')
    assert.equal(result.reason.kind, 'completed')

    const captured = mock.requests[0]
    assert.ok(captured)
    assert.equal(captured.path, '/v1/messages')
    assert.equal(captured.headers['x-api-key'], 'test-key')
    assert.equal(captured.body.model, 'm')
    assert.equal(captured.body.system, 'sys')
    assert.equal(captured.body.stream, true)
    const messages = captured.body.messages as { role: string; content: unknown }[]
    assert.equal(messages[0]?.role, 'user')
  } finally {
    await mock.stop()
  }
})

test('the request carries the registered tool schemas', async () => {
  const mock = await startMock([
    {
      event: 'message_start',
      data: JSON.stringify({ type: 'message_start', message: { usage: { input_tokens: 5, output_tokens: 0 } } }),
    },
    {
      event: 'content_block_start',
      data: JSON.stringify({
        type: 'content_block_start',
        index: 0,
        content_block: { type: 'tool_use', id: 'toolu_1', name: 'bash', input: {} },
      }),
    },
    {
      event: 'content_block_delta',
      data: JSON.stringify({
        type: 'content_block_delta',
        index: 0,
        delta: { type: 'input_json_delta', partial_json: '{"command":"echo hi"}' },
      }),
    },
    { event: 'content_block_stop', data: JSON.stringify({ type: 'content_block_stop', index: 0 }) },
    {
      event: 'message_delta',
      data: JSON.stringify({ type: 'message_delta', delta: { stop_reason: 'tool_use' }, usage: { output_tokens: 3 } }),
    },
    { event: 'message_stop', data: JSON.stringify({ type: 'message_stop' }) },
  ])
  try {
    const adapter = new DeepSeekAdapter({ apiKey: 'test-key', baseURL: mock.baseURL })
    const registry = new ToolRegistry()
    for (const tool of createBuiltinTools(process.cwd())) {
      registry.register(tool)
    }
    // The adapter is driven directly here, so the agent loop cannot loop on
    // the mock's repeated tool call.
    const chunks: string[] = []
    for await (const chunk of adapter.stream({
      provider: adapter.provider,
      model: 'm',
      system: 'sys',
      messages: [{ role: 'user', content: [{ type: 'text', text: 'run echo hi' }] }],
      tools: registry.schemas(),
    })) {
      if (chunk.type === 'tool-call-delta') chunks.push(chunk.argumentsDelta)
    }
    assert.equal(chunks.join(''), '{"command":"echo hi"}')

    const captured = mock.requests[0]
    assert.ok(captured)
    const tools = captured.body.tools as { name: string; input_schema: unknown }[]
    assert.ok(tools.some(tool => tool.name === 'bash'))
    assert.ok(tools.some(tool => tool.name === 'read_file'))
    assert.ok(tools.some(tool => tool.name === 'write_file'))
    assert.ok(tools.some(tool => tool.name === 'edit_file'))
  } finally {
    await mock.stop()
  }
})

test('the agent sends a tool_result block on the request after a tool call', async () => {
  // The mock answers the first request with a tool call and the second with text.
  const requests: Captured[] = []
  const server = createServer((req, res) => {
    const chunks: Buffer[] = []
    req.on('data', chunk => { chunks.push(chunk as Buffer) })
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8')
      requests.push({ path: req.url ?? '', headers: req.headers, body: JSON.parse(raw) as Record<string, unknown> })
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      if (requests.length === 1) {
        const frames = [
          { event: 'message_start', data: JSON.stringify({ type: 'message_start', message: { usage: { input_tokens: 5, output_tokens: 0 } } }) },
          { event: 'content_block_start', data: JSON.stringify({ type: 'content_block_start', index: 0, content_block: { type: 'tool_use', id: 'toolu_1', name: 'bash', input: {} } }) },
          { event: 'content_block_delta', data: JSON.stringify({ type: 'content_block_delta', index: 0, delta: { type: 'input_json_delta', partial_json: '{"command":"echo hi"}' } }) },
          { event: 'content_block_stop', data: JSON.stringify({ type: 'content_block_stop', index: 0 }) },
          { event: 'message_delta', data: JSON.stringify({ type: 'message_delta', delta: { stop_reason: 'tool_use' }, usage: { output_tokens: 3 } }) },
          { event: 'message_stop', data: JSON.stringify({ type: 'message_stop' }) },
        ]
        for (const frame of frames) res.write(`event: ${frame.event}\ndata: ${frame.data}\n\n`)
      } else {
        const frames = [
          { event: 'message_start', data: JSON.stringify({ type: 'message_start', message: { usage: { input_tokens: 9, output_tokens: 0 } } }) },
          { event: 'content_block_start', data: JSON.stringify({ type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }) },
          { event: 'content_block_delta', data: JSON.stringify({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'all done' } }) },
          { event: 'content_block_stop', data: JSON.stringify({ type: 'content_block_stop', index: 0 }) },
          { event: 'message_delta', data: JSON.stringify({ type: 'message_delta', delta: { stop_reason: 'end_turn' }, usage: { output_tokens: 4 } }) },
          { event: 'message_stop', data: JSON.stringify({ type: 'message_stop' }) },
        ]
        for (const frame of frames) res.write(`event: ${frame.event}\ndata: ${frame.data}\n\n`)
      }
      res.end()
    })
  })
  await new Promise<void>(resolve => { server.listen(0, '127.0.0.1', resolve) })
  const address = server.address() as AddressInfo
  try {
    const adapter = new DeepSeekAdapter({ apiKey: 'test-key', baseURL: `http://127.0.0.1:${address.port}` })
    const registry = new ToolRegistry()
    for (const tool of createBuiltinTools(process.cwd())) {
      registry.register(tool)
    }
    const agent = new Agent(adapter, registry, { provider: adapter.provider, model: 'm', systemPrompt: 'sys' })
    const result = await agent.run('run echo hi')
    assert.equal(result.text, 'all done')
    assert.equal(result.steps, 2)

    // The second request carries the tool result.
    const second = requests[1]
    assert.ok(second)
    const messages = second.body.messages as { role: string; content: { type: string; tool_use_id?: string; content?: unknown }[] }[]
    const toolMessage = messages.find(message => message.role === 'user'
      && message.content.some(block => block.type === 'tool_result'))
    assert.ok(toolMessage, 'the second request carries a tool_result block')
    const resultBlock = toolMessage.content.find(block => block.type === 'tool_result')
    assert.equal(resultBlock?.tool_use_id, 'toolu_1')
    const body = resultBlock?.content as { type: string; text: string }[]
    assert.equal(body[0]?.text, 'hi')
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close(error => { error === undefined ? resolve() : reject(error) })
    })
  }
})
