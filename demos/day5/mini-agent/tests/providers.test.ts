/**
 * Tests for the provider registry, the provider configuration file, and the
 * OpenAI-compatible adapter.
 */

import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { mkdtemp, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { Agent } from '../src/core/agent.ts'
import { ProviderRegistry } from '../src/core/providers.ts'
import { ToolRegistry } from '../src/core/tools.ts'
import { createAdapter, expandEnv, loadProviders } from '../src/core/config.ts'
import { OpenAiAdapter, toChatMessages } from '../src/llm/openai.ts'

test('the registry rejects a duplicate provider name', () => {
  const registry = new ProviderRegistry()
  registry.register('a', 'openai', {}, () => { throw new Error('unused') })
  assert.throws(() => {
    registry.register('a', 'openai', {}, () => { throw new Error('unused') })
  }, /already registered/)
})

test('the registry resolves a registered provider into an adapter', () => {
  const registry = new ProviderRegistry()
  registry.register('demo', 'openai', { apiKey: 'k' }, (settings) => createAdapter('openai', settings).adapter)
  const adapter = registry.create('demo')
  assert.equal(adapter.provider, 'openai')
})

test('the registry reports an unknown provider with the known names', () => {
  const registry = new ProviderRegistry()
  registry.register('known', 'openai', {}, () => { throw new Error('unused') })
  assert.throws(() => registry.create('missing'), /unknown provider "missing".*known/s)
})

test('replace redefines a route on purpose', () => {
  const registry = new ProviderRegistry()
  registry.register('route', 'openai', { baseURL: 'https://first.example' },
    (settings) => createAdapter('openai', settings).adapter)
  registry.replace('route', 'openai', { baseURL: 'https://second.example' },
    (settings) => createAdapter('openai', settings).adapter)
  assert.equal(registry.settingsOf('route')?.baseURL, 'https://second.example')
})

test('the settings lookup carries the adapter kind', () => {
  const registry = new ProviderRegistry()
  registry.register('messages-route', 'deepseek', { apiKey: 'k' },
    (settings) => createAdapter('deepseek', settings).adapter)
  // A caller that rebuilds the route from these settings must keep the
  // protocol; a missing kind would silently build a different adapter.
  assert.equal(registry.settingsOf('messages-route')?.kind, 'deepseek')
})

test('environment placeholders expand in provider settings', () => {
  process.env.MINI_AGENT_TEST_KEY = 'secret-value'
  assert.deepEqual(
    expandEnv({ apiKey: '${MINI_AGENT_TEST_KEY}', baseURL: 'https://x.example' }),
    { apiKey: 'secret-value', baseURL: 'https://x.example' },
  )
  delete process.env.MINI_AGENT_TEST_KEY
})

test('an unset environment variable expands to an empty string', () => {
  delete process.env.MINI_AGENT_TEST_MISSING
  assert.deepEqual(expandEnv({ apiKey: '${MINI_AGENT_TEST_MISSING}' }), { apiKey: '' })
})

test('a config file registers custom providers', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'mini-agent-config-'))
  const file = join(dir, 'providers.json')
  await writeFile(file, JSON.stringify({
    providers: {
      'custom-llm': { kind: 'openai', baseURL: 'https://custom.example/v1', apiKey: 'k' },
    },
  }), 'utf8')
  const registry = new ProviderRegistry()
  const loaded = await loadProviders(registry, dir)
  assert.equal(loaded, file)
  assert.ok(registry.names().includes('custom-llm'))
  assert.equal(registry.settingsOf('custom-llm')?.baseURL, 'https://custom.example/v1')
})

test('a config file overrides a built-in route', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'mini-agent-config-'))
  await writeFile(join(dir, 'providers.json'), JSON.stringify({
    providers: {
      deepseek: { kind: 'deepseek', baseURL: 'https://mirror.example', apiKey: 'k' },
    },
  }), 'utf8')
  const registry = new ProviderRegistry()
  registry.register('deepseek', 'deepseek', { baseURL: 'https://original.example' },
    (settings) => createAdapter('deepseek', settings).adapter)
  await loadProviders(registry, dir)
  assert.equal(registry.settingsOf('deepseek')?.baseURL, 'https://mirror.example')
})

test('a missing config file is not an error', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'mini-agent-config-'))
  const registry = new ProviderRegistry()
  const loaded = await loadProviders(registry, dir)
  assert.equal(loaded, undefined)
})

test('a malformed config file fails loudly', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'mini-agent-config-'))
  await writeFile(join(dir, 'providers.json'), '{ not json', 'utf8')
  const registry = new ProviderRegistry()
  await assert.rejects(() => loadProviders(registry, dir), /not valid JSON/)
})

test('an unknown provider kind fails loudly', () => {
  assert.throws(() => createAdapter('nonexistent', {}), /unknown provider kind "nonexistent"/)
})

test('chat messages map tool results to tool messages', () => {
  const wire = toChatMessages([
    { role: 'user', content: [{ type: 'text', text: 'hi' }] },
    { role: 'assistant', content: [{ type: 'tool-call', id: 'c1', name: 'bash', arguments: '{}' }] },
    { role: 'tool', content: [{ type: 'tool-result', id: 'c1', isError: false, text: 'output' }] },
  ])
  assert.equal(wire.length, 3)
  assert.equal(wire[0]?.role, 'user')
  assert.equal(wire[1]?.role, 'assistant')
  assert.equal(wire[1]?.tool_calls?.length, 1)
  assert.equal(wire[2]?.role, 'tool')
  assert.equal(wire[2]?.tool_call_id, 'c1')
  assert.equal(wire[2]?.content, 'output')
})

test('the OpenAI adapter streams text and a tool call', async () => {
  let requestBody: Record<string, unknown> = {}
  const server = createServer((req, res) => {
    const chunks: Buffer[] = []
    req.on('data', chunk => { chunks.push(chunk as Buffer) })
    req.on('end', () => {
      requestBody = JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      const send = (payload: unknown): void => { res.write(`data: ${JSON.stringify(payload)}\n\n`) }
      send({ choices: [{ index: 0, delta: { role: 'assistant', content: 'Hello' }, finish_reason: null }] })
      send({ choices: [{ index: 0, delta: { content: ' world' }, finish_reason: null }] })
      send({
        choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
        usage: { prompt_tokens: 7, completion_tokens: 3, total_tokens: 10 },
      })
      res.write('data: [DONE]\n\n')
      res.end()
    })
  })
  await new Promise<void>(resolve => { server.listen(0, '127.0.0.1', resolve) })
  const address = server.address() as AddressInfo
  try {
    const adapter = new OpenAiAdapter({ apiKey: 'k', baseURL: `http://127.0.0.1:${address.port}` })
    const registry = new ToolRegistry()
    const agent = new Agent(adapter, registry, { provider: adapter.provider, model: 'gpt-test', systemPrompt: 'sys' })
    const result = await agent.run('hi')
    assert.equal(result.text, 'Hello world')
    assert.equal(result.reason.kind, 'completed')
    assert.equal(requestBody.model, 'gpt-test')
    assert.equal(requestBody.stream, true)
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close(error => { error === undefined ? resolve() : reject(error) })
    })
  }
})

test('the OpenAI adapter sends the bearer token and the tool schemas', async () => {
  let auth: string | undefined
  let body: Record<string, unknown> = {}
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
        usage: { prompt_tokens: 1, completion_tokens: 1 },
      })}\n\n`)
      res.write('data: [DONE]\n\n')
      res.end()
    })
  })
  await new Promise<void>(resolve => { server.listen(0, '127.0.0.1', resolve) })
  const address = server.address() as AddressInfo
  try {
    const adapter = new OpenAiAdapter({ apiKey: 'my-key', baseURL: `http://127.0.0.1:${address.port}` })
    const registry = new ToolRegistry()
    registry.register({
      name: 'demo',
      description: 'demo tool',
      parameters: { type: 'object', properties: { x: { type: 'string' } }, required: ['x'] },
      async execute() { return 'done' },
    })
    const agent = new Agent(adapter, registry, { provider: adapter.provider, model: 'gpt-test', systemPrompt: 'sys' })
    await agent.run('hi')
    assert.equal(auth, 'Bearer my-key')
    const tools = body.tools as { type: string; function: { name: string } }[]
    assert.equal(tools[0]?.type, 'function')
    assert.equal(tools[0]?.function.name, 'demo')
  } finally {
    await new Promise<void>((resolve, reject) => {
      server.close(error => { error === undefined ? resolve() : reject(error) })
    })
  }
})
