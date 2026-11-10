/**
 * Behavior tests for the mini agent core: the session log projection, the tool
 * registry validation, and the agent loop's turn/step behaviour.
 *
 * Run with: node --experimental-strip-types --test tests/*.test.ts
 */

import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { mkdtemp, readFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { Agent } from '../src/core/agent.ts'
import { BlockAssembler } from '../src/core/llm.ts'
import { Session } from '../src/core/session.ts'
import { ToolRegistry, validateAgainstSchema } from '../src/core/tools.ts'
import { createBuiltinTools } from '../src/tools/builtin.ts'
import type { GenerateOptions, StreamChunk } from '../src/core/types.ts'

/** A scripted adapter that replays prepared chunk sequences. */
class ScriptedAdapter {
  /** The provider route key this adapter serves. */
  readonly provider = 'scripted'
  /** The recorded requests, one per call. */
  readonly requests: GenerateOptions[] = []
  private readonly scripts: StreamChunk[][]

  constructor(scripts: StreamChunk[][]) {
    this.scripts = scripts
  }

  async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    this.requests.push(options)
    const script = this.scripts.shift() ?? []
    for (const chunk of script) {
      if (options.signal?.aborted === true) return
      yield chunk
    }
  }
}

/** Build a text-only response script. */
function textResponse(text: string): StreamChunk[] {
  return [
    { type: 'block-start', index: 0, blockType: 'text' },
    { type: 'text-delta', index: 0, text },
    { type: 'block-end', index: 0, block: { type: 'text', text } },
    { type: 'usage', usage: { inputTokens: 10, outputTokens: 5 } },
    { type: 'finish', reason: { kind: 'stop' } },
  ]
}

/** Build a tool-call response script. */
function toolResponse(id: string, name: string, args: unknown): StreamChunk[] {
  const argumentsText = JSON.stringify(args)
  return [
    { type: 'block-start', index: 0, blockType: 'tool-call' },
    { type: 'tool-call-delta', index: 0, id, name, argumentsDelta: argumentsText },
    { type: 'block-end', index: 0, block: { type: 'tool-call', id, name, arguments: argumentsText } },
    { type: 'finish', reason: { kind: 'tool-calls' } },
  ]
}

test('session log derives the request history', () => {
  const session = new Session('s1')
  session.append({ kind: 'turn/start', turn: 1 })
  session.append({ kind: 'user/message', turn: 1, step: 0, text: 'hello' })
  session.append({
    kind: 'assistant/message',
    turn: 1,
    step: 1,
    content: [{ type: 'tool-call', id: 'c1', name: 'bash', arguments: '{}' }],
  })
  session.append({ kind: 'tool/result', turn: 1, step: 1, id: 'c1', name: 'bash', isError: false, text: 'ok' })
  const messages = session.deriveMessages()
  assert.equal(messages.length, 3)
  assert.equal(messages[0]?.role, 'user')
  assert.equal(messages[1]?.role, 'assistant')
  assert.equal(messages[2]?.role, 'tool')
  assert.equal(messages[2]?.content[0]?.type, 'tool-result')
})

test('schema validation reports required and type violations', () => {
  const schema = {
    type: 'object',
    properties: { path: { type: 'string' }, count: { type: 'number' } },
    required: ['path'],
    additionalProperties: false,
  }
  assert.deepEqual(validateAgainstSchema(schema, { path: 'a.txt' }), [])
  assert.equal(validateAgainstSchema(schema, {}).length, 1)
  assert.equal(validateAgainstSchema(schema, { path: 1 }).length, 1)
  assert.equal(validateAgainstSchema(schema, { path: 'a', extra: 1 }).length, 1)
  assert.equal(validateAgainstSchema(schema, 'not an object').length, 1)
})

test('block assembler joins deltas into one block', () => {
  const assembler = new BlockAssembler()
  assembler.push({ type: 'block-start', index: 0, blockType: 'text' })
  assembler.push({ type: 'text-delta', index: 0, text: 'Hel' })
  assembler.push({ type: 'text-delta', index: 0, text: 'lo' })
  assembler.push({ type: 'block-end', index: 0, block: { type: 'text', text: 'Hello' } })
  assembler.push({ type: 'finish', reason: { kind: 'stop' } })
  assert.deepEqual(assembler.blocks(), [{ type: 'text', text: 'Hello' }])
  assert.equal(assembler.finish?.kind, 'stop')
})

test('agent runs a text-only turn', async () => {
  const adapter = new ScriptedAdapter([textResponse('done')])
  const registry = new ToolRegistry()
  const agent = new Agent(adapter, registry, { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('hi')
  assert.equal(result.text, 'done')
  assert.equal(result.reason.kind, 'completed')
  assert.equal(result.steps, 1)
  assert.equal(adapter.requests.length, 1)
  assert.equal(adapter.requests[0]?.system, 'sys')
})

test('agent executes a tool call and requests the model again', async () => {
  const adapter = new ScriptedAdapter([
    toolResponse('c1', 'echo', { value: 'hi' }),
    textResponse('the tool said hi'),
  ])
  const registry = new ToolRegistry()
  registry.register({
    name: 'echo',
    description: 'echo',
    parameters: { type: 'object', properties: { value: { type: 'string' } }, required: ['value'] },
    async execute(args) { return `echo: ${String(args.value)}` },
  })
  const agent = new Agent(adapter, registry, { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('go')
  assert.equal(result.text, 'the tool said hi')
  assert.equal(result.steps, 2)
  // The second request carries the tool result.
  const second = adapter.requests[1]
  const toolMessage = second?.messages.find(message => message.role === 'tool')
  assert.ok(toolMessage)
  assert.equal(toolMessage.content[0]?.type, 'tool-result')
})

test('agent reports an unknown tool as a tool error, not a turn failure', async () => {
  const adapter = new ScriptedAdapter([
    toolResponse('c1', 'missing', {}),
    textResponse('recovered'),
  ])
  const registry = new ToolRegistry()
  const agent = new Agent(adapter, registry, { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('go')
  assert.equal(result.text, 'recovered')
  const results = agent.session.snapshot().filter(stored => stored.event.kind === 'tool/result')
  assert.equal(results.length, 1)
  const event = results[0]?.event
  assert.equal(event?.kind, 'tool/result')
  if (event?.kind === 'tool/result') {
    assert.equal(event.isError, true)
    assert.match(event.text, /unknown tool/)
  }
})

test('agent rejects arguments that violate the schema', async () => {
  const adapter = new ScriptedAdapter([
    toolResponse('c1', 'typed', { count: 'not a number' }),
    textResponse('recovered'),
  ])
  const registry = new ToolRegistry()
  registry.register({
    name: 'typed',
    description: 'typed',
    parameters: { type: 'object', properties: { count: { type: 'number' } }, required: ['count'] },
    async execute() { return 'never' },
  })
  const agent = new Agent(adapter, registry, { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  await agent.run('go')
  const results = agent.session.snapshot().filter(stored => stored.event.kind === 'tool/result')
  const event = results[0]?.event
  if (event?.kind === 'tool/result') {
    assert.equal(event.isError, true)
    assert.match(event.text, /invalid tool arguments/)
  }
})

test('builtin tools read, write, and edit inside the workspace', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mini-agent-'))
  const tools = createBuiltinTools(root)
  const write = tools.find(tool => tool.name === 'write_file')
  const read = tools.find(tool => tool.name === 'read_file')
  const edit = tools.find(tool => tool.name === 'edit_file')
  assert.ok(write && read && edit)
  const signal = new AbortController().signal
  await write.execute({ path: 'a.txt', content: 'hello' }, signal)
  assert.equal(await read.execute({ path: 'a.txt' }, signal), 'hello')
  await edit.execute({ path: 'a.txt', old_string: 'hello', new_string: 'world' }, signal)
  assert.equal(await read.execute({ path: 'a.txt' }, signal), 'world')
  assert.equal(await read.execute({ path: 'a.txt' }, signal), 'world')
  const onDisk = await readFile(join(root, 'a.txt'), 'utf8')
  assert.equal(onDisk, 'world')
})

test('builtin tools refuse paths that escape the workspace', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mini-agent-'))
  const read = createBuiltinTools(root).find(tool => tool.name === 'read_file')
  assert.ok(read)
  const signal = new AbortController().signal
  await assert.rejects(
    () => read.execute({ path: '../../etc/passwd' }, signal),
    /escapes the workspace root/,
  )
})

test('bash tool runs a command in the workspace', async () => {
  const root = await mkdtemp(join(tmpdir(), 'mini-agent-'))
  const bash = createBuiltinTools(root).find(tool => tool.name === 'bash')
  assert.ok(bash)
  const signal = new AbortController().signal
  const output = await bash.execute({ command: 'echo mini' }, signal)
  assert.equal(output, 'mini')
})
