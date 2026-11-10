/**
 * Tests for how the agent decides that a task is complete.
 *
 * The agent has no separate verification layer: completion is decided by the
 * shape of the model's response, not by inspecting the task or the result.
 */

import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { Agent } from '../src/core/agent.ts'
import { ToolRegistry } from '../src/core/tools.ts'
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
function textResponse(text: string, finishKind: 'stop' | 'max-tokens' = 'stop'): StreamChunk[] {
  return [
    { type: 'block-start', index: 0, blockType: 'text' },
    { type: 'text-delta', index: 0, text },
    { type: 'block-end', index: 0, block: { type: 'text', text } },
    { type: 'finish', reason: { kind: finishKind } },
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

test('a text-only response ends the turn as completed', async () => {
  const adapter = new ScriptedAdapter([textResponse('all done')])
  const agent = new Agent(adapter, new ToolRegistry(), { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('do the thing')
  assert.equal(result.reason.kind, 'completed')
  assert.equal(result.steps, 1)
  assert.equal(adapter.requests.length, 1)
})

test('the turn continues while the model asks for tools', async () => {
  const adapter = new ScriptedAdapter([
    toolResponse('c1', 'bash', { command: 'ls' }),
    toolResponse('c2', 'bash', { command: 'pwd' }),
    textResponse('finished after two tools'),
  ])
  const registry = new ToolRegistry()
  registry.register({
    name: 'bash',
    description: 'run a command',
    parameters: { type: 'object', properties: { command: { type: 'string' } }, required: ['command'] },
    async execute() { return 'ok' },
  })
  const agent = new Agent(adapter, registry, { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('do the thing')
  assert.equal(result.reason.kind, 'completed')
  assert.equal(result.steps, 3)
  assert.equal(adapter.requests.length, 3)
})

test('a tool failure does not end the turn; the model can recover', async () => {
  const adapter = new ScriptedAdapter([
    toolResponse('c1', 'boom', {}),
    textResponse('recovered'),
  ])
  const registry = new ToolRegistry()
  registry.register({
    name: 'boom',
    description: 'always fails',
    parameters: { type: 'object', properties: {} },
    async execute() { throw new Error('tool exploded') },
  })
  const agent = new Agent(adapter, registry, { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('do the thing')
  assert.equal(result.reason.kind, 'completed')
  assert.equal(result.text, 'recovered')
  // The failure is reported to the model, not to the caller.
  const results = agent.session.snapshot().filter(stored => stored.event.kind === 'tool/result')
  const event = results[0]?.event
  if (event?.kind === 'tool/result') {
    assert.equal(event.isError, true)
    assert.match(event.text, /tool exploded/)
  }
})

test('reaching the output cap ends the turn as max-tokens', async () => {
  const adapter = new ScriptedAdapter([textResponse('partial answer', 'max-tokens')])
  const agent = new Agent(adapter, new ToolRegistry(), { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('do the thing')
  assert.equal(result.reason.kind, 'max-tokens')
  assert.equal(result.text, 'partial answer')
})

test('a stream that ends without a finish frame still completes', async () => {
  const adapter = new ScriptedAdapter([])
  // An empty script yields no finish frame at all. The loop treats a missing
  // finish frame as a completed turn with empty text, not as a failure.
  const agent = new Agent(adapter, new ToolRegistry(), { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('do the thing')
  assert.equal(result.reason.kind, 'completed')
  assert.equal(result.text, '')
})

test('the turn end reason is recorded in the session log', async () => {
  const adapter = new ScriptedAdapter([textResponse('done')])
  const agent = new Agent(adapter, new ToolRegistry(), { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  await agent.run('do the thing')
  const events = agent.session.snapshot()
  const turnEnd = events.find(stored => stored.event.kind === 'turn/end')
  assert.ok(turnEnd)
  const event = turnEnd?.event
  assert.equal(event?.kind, 'turn/end')
  if (event?.kind === 'turn/end') {
    assert.deepEqual(event.reason, { kind: 'completed' })
  }
})

test('completion is decided by the response shape, not by the task text', async () => {
  // A task that asks for no work still completes when the model answers with
  // text: the loop has no notion of what the task required.
  const adapter = new ScriptedAdapter([textResponse('I did nothing in particular')])
  const agent = new Agent(adapter, new ToolRegistry(), { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('please do absolutely nothing')
  assert.equal(result.reason.kind, 'completed')
  assert.equal(result.steps, 1)
})

test('an empty response with no tool calls still ends the turn', async () => {
  const adapter = new ScriptedAdapter([
    [{ type: 'finish', reason: { kind: 'stop' } }],
  ])
  const agent = new Agent(adapter, new ToolRegistry(), { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('do the thing')
  assert.equal(result.reason.kind, 'completed')
  assert.equal(result.text, '')
})