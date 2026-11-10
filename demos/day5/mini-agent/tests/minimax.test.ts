/**
 * Tests for the MiniMax provider route: the request body it sends and the
 * MiniMax-specific response fields it understands.
 */

import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'

import { Agent } from '../src/core/agent.ts'
import { ToolRegistry } from '../src/core/tools.ts'
import { createAdapter } from '../src/core/config.ts'
import { OpenAiAdapter } from '../src/llm/openai.ts'

test('the minimax route sends max_completion_tokens and the extra body fields', async () => {
  let body: Record<string, unknown> = {}
  let auth: string | undefined
  const server = createServer((req, res) => {
    auth = req.headers.authorization
    const chunks: Buffer[] = []
    req.on('data', chunk => { chunks.push(chunk as Buffer) })
    req.on('end', () => {
      body = JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      res.write(`data: ${JSON.stringify({
        choices: [{ index: 0, delta: { role: 'assistant', content: 'ok' }, finish_reason: null }],
      })}\n\n`)
      res.write(`data: ${JSON.stringify({
        choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
        usage: { prompt_tokens: 5, completion_tokens: 2, total_tokens: 7 },
      })}\n\n`)
      res.write('data: [DONE]\n\n')
      res.end()
    })
  })
  await new Promise<void>(resolve => { server.listen(0, '127.0.0.1', resolve) })
  const address = server.address() as AddressInfo
  try {
    const { adapter } = createAdapter('openai', {
      apiKey: 'minimax-key',
      baseURL: `http://127.0.0.1:${address.port}`,
      useMaxCompletionTokens: true,
      extraBody: { reasoning_effort: 'max', thinking: { type: 'adaptive' } },
    })
    const registry = new ToolRegistry()
    const agent = new Agent(adapter, registry, { provider: adapter.provider, model: 'MiniMax-M3.1-Flash', systemPrompt: 'sys' })
    await agent.run('hi')

    assert.equal(auth, 'Bearer minimax-key')
    assert.equal(body.model, 'MiniMax-M3.1-Flash')
    // The output cap uses the field MiniMax recommends.
    assert.equal(body.max_completion_tokens, undefined)
    assert.equal(body.max_tokens, undefined)
    // The provider-specific fields reach the request.
    assert.equal(body.reasoning_effort, 'max')
    assert.deepEqual(body.thinking, { type: 'adaptive' })
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close(error => { error === undefined ? resolve() : reject(error) })
    })
  }
})

test('the max_completion_tokens field carries the output cap', async () => {
  let body: Record<string, unknown> = {}
  const server = createServer((req, res) => {
    const chunks: Buffer[] = []
    req.on('data', chunk => { chunks.push(chunk as Buffer) })
    req.on('end', () => {
      body = JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      res.write(`data: ${JSON.stringify({
        choices: [{ index: 0, delta: { content: 'ok' }, finish_reason: 'stop' }],
      })}\n\n`)
      res.end()
    })
  })
  await new Promise<void>(resolve => { server.listen(0, '127.0.0.1', resolve) })
  const address = server.address() as AddressInfo
  try {
    const adapter = new OpenAiAdapter({
      apiKey: 'k',
      baseURL: `http://127.0.0.1:${address.port}`,
      useMaxCompletionTokens: true,
    })
    const registry = new ToolRegistry()
    const agent = new Agent(adapter, registry, {
      provider: adapter.provider,
      model: 'MiniMax-M3',
      systemPrompt: 'sys',
      maxTokens: 4096,
    })
    await agent.run('hi')
    assert.equal(body.max_completion_tokens, 4096)
    assert.equal(body.max_tokens, undefined)
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close(error => { error === undefined ? resolve() : reject(error) })
    })
  }
})

test('the adapter reads the reasoning_content field MiniMax streams', async () => {  const server = createServer((req, res) => {
    res.writeHead(200, { 'content-type': 'text/event-stream' })
    res.write(`data: ${JSON.stringify({
      choices: [{ index: 0, delta: { reasoning_content: 'thinking about it' }, finish_reason: null }],
    })}\n\n`)
    res.write(`data: ${JSON.stringify({
      choices: [{ index: 0, delta: { content: 'the answer' }, finish_reason: null }],
    })}\n\n`)
    res.write(`data: ${JSON.stringify({
      choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
      usage: { prompt_tokens: 5, completion_tokens: 2 },
    })}\n\n`)
    res.end()
  })
  await new Promise<void>(resolve => { server.listen(0, '127.0.0.1', resolve) })
  const address = server.address() as AddressInfo
  try {
    const adapter = new OpenAiAdapter({ apiKey: 'k', baseURL: `http://127.0.0.1:${address.port}` })
    const registry = new ToolRegistry()
    const agent = new Agent(adapter, registry, { provider: adapter.provider, model: 'MiniMax-M3.1-Flash', systemPrompt: 'sys' })
    const result = await agent.run('hi')
    // The thinking content is reasoning, not the visible answer.
    assert.equal(result.text, 'the answer')
    const messages = agent.session.deriveMessages()
    const assistant = messages[messages.length - 1]
    assert.equal(assistant?.role, 'assistant')
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close(error => { error === undefined ? resolve() : reject(error) })
    })
  }
})

test('the minimax routes target the two regional platforms', async () => {
  // The two platforms issue separate keys, so each route must point at the
  // endpoint where its key was created. Both speak the OpenAI protocol, so
  // the route kind is the same and only the endpoint differs.
  const china = createAdapter('openai', { apiKey: 'k', baseURL: 'https://api.minimaxi.com/v1' })
  const international = createAdapter('openai', { apiKey: 'k', baseURL: 'https://api.minimax.io/v1' })
  assert.equal(china.provider, 'openai')
  assert.equal(international.provider, 'openai')
  assert.equal(china.adapter.baseURL, 'https://api.minimaxi.com/v1')
  assert.equal(international.adapter.baseURL, 'https://api.minimax.io/v1')
})

test('a MiniMax tool call split across chunks is assembled into one call', async () => {
  // MiniMax sends the tool name in one chunk and the arguments in a later
  // chunk that already carries the finish reason.
  let requestCount = 0
  const server = createServer((req, res) => {
    requestCount += 1
    res.writeHead(200, { 'content-type': 'text/event-stream' })
    if (requestCount === 1) {
      res.write(`data: ${JSON.stringify({
        choices: [{
          index: 0,
          delta: { content: '', role: 'assistant', tool_calls: [{ id: 'chatcmpl-tool-1', type: 'function', function: { name: 'bash', arguments: '' }, index: 0 }] },
          finish_reason: null,
        }],
      })}\n\n`)
      res.write(`data: ${JSON.stringify({
        choices: [{
          index: 0,
          delta: { role: 'assistant', tool_calls: [{ id: 'chatcmpl-tool-1', function: { arguments: '{"command":"ls"}' }, index: 0 }] },
          finish_reason: 'tool_calls',
        }],
      })}\n\n`)
    } else {
      res.write(`data: ${JSON.stringify({
        choices: [{ index: 0, delta: { role: 'assistant', content: 'done' }, finish_reason: null }],
      })}\n\n`)
      res.write(`data: ${JSON.stringify({
        choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
        usage: { prompt_tokens: 5, completion_tokens: 2 },
      })}\n\n`)
    }
    res.write('data: [DONE]\n\n')
    res.end()
  })
  await new Promise<void>(resolve => { server.listen(0, '127.0.0.1', resolve) })
  const address = server.address() as AddressInfo
  try {
    const adapter = new OpenAiAdapter({ apiKey: 'k', baseURL: `http://127.0.0.1:${address.port}` })
    const registry = new ToolRegistry()
    let executed = ''
    registry.register({
      name: 'bash',
      description: 'run a command',
      parameters: { type: 'object', properties: { command: { type: 'string' } }, required: ['command'] },
      async execute(args) { executed = String(args.command); return 'listed' },
    })
    const agent = new Agent(adapter, registry, { provider: adapter.provider, model: 'MiniMax-M3.1-Flash', systemPrompt: 'sys' })
    const result = await agent.run('list files')
    assert.equal(executed, 'ls')
    assert.equal(result.text, 'done')
    const calls = agent.session.snapshot().filter(stored => stored.event.kind === 'tool/call')
    assert.equal(calls.length, 1)
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close(error => { error === undefined ? resolve() : reject(error) })
    })
  }
})
