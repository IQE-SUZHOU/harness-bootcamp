/**
 * Tests for the stop conditions: the limits that let a turn brake itself.
 */

import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { Agent } from '../src/core/agent.ts'
import { createStopConditions } from '../src/core/stop-conditions.ts'
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
function textResponse(text: string): StreamChunk[] {
  return [
    { type: 'block-start', index: 0, blockType: 'text' },
    { type: 'text-delta', index: 0, text },
    { type: 'block-end', index: 0, block: { type: 'text', text } },
    { type: 'finish', reason: { kind: 'stop' } },
  ]
}

/** Build a tool-call response script that reports the given usage. */
function toolResponse(id: string, usage?: { inputTokens: number; outputTokens: number }): StreamChunk[] {
  const argumentsText = JSON.stringify({ command: 'ls' })
  return [
    { type: 'block-start', index: 0, blockType: 'tool-call' },
    { type: 'tool-call-delta', index: 0, id, name: 'bash', argumentsDelta: argumentsText },
    { type: 'block-end', index: 0, block: { type: 'tool-call', id, name: 'bash', arguments: argumentsText } },
    ...usage === undefined ? [] : [{ type: 'usage' as const, usage }],
    { type: 'finish', reason: { kind: 'tool-calls' as const } },
  ]
}

/** Build a registry with one always-succeeding `bash` tool. */
function bashRegistry(): ToolRegistry {
  const registry = new ToolRegistry()
  registry.register({
    name: 'bash',
    description: 'run a command',
    parameters: { type: 'object', properties: { command: { type: 'string' } }, required: ['command'] },
    async execute() { return 'ok' },
  })
  return registry
}

test('an empty configuration never trips a limit', () => {
  const limits = createStopConditions()
  assert.equal(limits.check(1000, 1_000_000, 1_000_000), undefined)
})

test('a non-positive limit is rejected at construction', () => {
  assert.throws(() => createStopConditions({ maxSteps: 0 }), /maxSteps.*positive/)
  assert.throws(() => createStopConditions({ timeoutMs: -1 }), /timeoutMs.*positive/)
  assert.throws(() => createStopConditions({ maxTotalTokens: 0 }), /maxTotalTokens.*positive/)
  assert.throws(() => createStopConditions({ maxSteps: Number.NaN }), /maxSteps.*positive/)
  assert.throws(() => createStopConditions({ maxSteps: Number.POSITIVE_INFINITY }), /maxSteps.*positive/)
})

test('the step cap trips at the configured count', () => {
  const limits = createStopConditions({ maxSteps: 3 })
  assert.equal(limits.check(0, 0, 0), undefined)
  assert.equal(limits.check(2, 0, 0), undefined)
  const stop = limits.check(3, 0, 0)
  assert.equal(stop?.kind, 'max-steps')
  assert.match(stop?.message ?? '', /limit of 3 steps/)
})

test('the step cap message is singular for one step', () => {
  const limits = createStopConditions({ maxSteps: 1 })
  assert.match(limits.check(1, 0, 0)?.message ?? '', /limit of 1 step$/)
})

test('the time limit trips once the deadline passes', () => {
  const limits = createStopConditions({ timeoutMs: 1000 })
  assert.equal(limits.check(0, 0, 999), undefined)
  const stop = limits.check(0, 0, 1000)
  assert.equal(stop?.kind, 'timeout')
  assert.match(stop?.message ?? '', /time limit of 1000ms/)
})

test('the token budget trips once it is exhausted', () => {
  const limits = createStopConditions({ maxTotalTokens: 100 })
  assert.equal(limits.check(0, 99, 0), undefined)
  const stop = limits.check(0, 100, 0)
  assert.equal(stop?.kind, 'max-tokens')
  assert.match(stop?.message ?? '', /token limit of 100 tokens/)
})

test('the step cap is checked before the other limits', () => {
  const limits = createStopConditions({ maxSteps: 2, timeoutMs: 1, maxTotalTokens: 1 })
  const stop = limits.check(2, 999, 9999)
  assert.equal(stop?.kind, 'max-steps')
})

test('addUsage accumulates the token total', () => {
  const limits = createStopConditions({ maxTotalTokens: 30 })
  limits.addUsage(10, 5)
  limits.addUsage(20, 4)
  assert.equal(limits.totalTokens, 39)
  assert.equal(limits.check(0, 39, 0)?.kind, 'max-tokens')
})

test('the step cap ends a turn that keeps asking for tools', async () => {
  const adapter = new ScriptedAdapter([
    toolResponse('c1'),
    toolResponse('c2'),
    toolResponse('c3'),
    toolResponse('c4'),
  ])
  const agent = new Agent(adapter, bashRegistry(), {
    provider: 'scripted',
    model: 'm',
    systemPrompt: 'sys',
    stopConditions: { maxSteps: 2 },
  })
  const result = await agent.run('loop forever')
  assert.equal(result.reason.kind, 'stopped')
  if (result.reason.kind === 'stopped') {
    assert.equal(result.reason.stopKind, 'max-steps')
    assert.match(result.reason.message, /limit of 2 steps/)
  }
  // The cap stops the turn before another model request is spent.
  assert.equal(result.steps, 2)
  assert.equal(adapter.requests.length, 2)
})

test('the stop reason is recorded in the session log', async () => {
  const adapter = new ScriptedAdapter([toolResponse('c1'), toolResponse('c2')])
  const agent = new Agent(adapter, bashRegistry(), {
    provider: 'scripted',
    model: 'm',
    systemPrompt: 'sys',
    stopConditions: { maxSteps: 1 },
  })
  await agent.run('loop forever')
  const turnEnd = agent.session.snapshot().find(stored => stored.event.kind === 'turn/end')
  const event = turnEnd?.event
  if (event?.kind === 'turn/end') {
    assert.equal(event.reason.kind, 'stopped')
    if (event.reason.kind === 'stopped') {
      assert.equal(event.reason.stopKind, 'max-steps')
    }
  } else {
    assert.fail('the turn end event is missing')
  }
})

test('the onStopped callback reports the limit that tripped', async () => {
  const adapter = new ScriptedAdapter([toolResponse('c1'), toolResponse('c2')])
  const stopped: { kind: string; message: string }[] = []
  const agent = new Agent(adapter, bashRegistry(), {
    provider: 'scripted',
    model: 'm',
    systemPrompt: 'sys',
    stopConditions: { maxSteps: 1 },
    onStopped: (kind, message) => { stopped.push({ kind, message }) },
  })
  await agent.run('loop forever')
  assert.equal(stopped.length, 1)
  assert.equal(stopped[0]?.kind, 'max-steps')
})

test('the token budget ends a turn that keeps asking for tools', async () => {
  const adapter = new ScriptedAdapter([
    toolResponse('c1', { inputTokens: 40, outputTokens: 10 }),
    toolResponse('c2', { inputTokens: 40, outputTokens: 10 }),
  ])
  const agent = new Agent(adapter, bashRegistry(), {
    provider: 'scripted',
    model: 'm',
    systemPrompt: 'sys',
    stopConditions: { maxTotalTokens: 100 },
  })
  const result = await agent.run('loop forever')
  assert.equal(result.reason.kind, 'stopped')
  if (result.reason.kind === 'stopped') {
    assert.equal(result.reason.stopKind, 'max-tokens')
  }
  // The first response used 50 tokens, so the second request is allowed and
  // the budget trips after it.
  assert.equal(result.steps, 2)
})

test('the time limit ends a turn that overruns its deadline', async () => {
  // The adapter stalls on the first request so the turn outlives the
  // deadline; the second request must never be sent.
  let requests = 0
  const stalling = {
    provider: 'scripted',
    async *stream(): AsyncIterable<StreamChunk> {
      requests += 1
      await new Promise(resolve => { setTimeout(resolve, 60) })
      yield* toolResponse('c1')
    },
  }
  const agent = new Agent(stalling, bashRegistry(), {
    provider: 'scripted',
    model: 'm',
    systemPrompt: 'sys',
    stopConditions: { timeoutMs: 20 },
  })
  const result = await agent.run('loop forever')
  assert.equal(result.reason.kind, 'stopped')
  if (result.reason.kind === 'stopped') {
    assert.equal(result.reason.stopKind, 'timeout')
    assert.match(result.reason.message, /time limit of 20ms/)
  }
  assert.equal(requests, 1)
})

test('a turn under the limits still completes normally', async () => {
  const adapter = new ScriptedAdapter([toolResponse('c1'), textResponse('all done')])
  const agent = new Agent(adapter, bashRegistry(), {
    provider: 'scripted',
    model: 'm',
    systemPrompt: 'sys',
    stopConditions: { maxSteps: 10, timeoutMs: 60_000, maxTotalTokens: 100_000 },
  })
  const result = await agent.run('do the thing')
  assert.equal(result.reason.kind, 'completed')
  assert.equal(result.text, 'all done')
  assert.equal(result.steps, 2)
})

test('a turn without limits is unchanged', async () => {
  const adapter = new ScriptedAdapter([toolResponse('c1'), textResponse('all done')])
  const agent = new Agent(adapter, bashRegistry(), { provider: 'scripted', model: 'm', systemPrompt: 'sys' })
  const result = await agent.run('do the thing')
  assert.equal(result.reason.kind, 'completed')
  assert.equal(result.steps, 2)
})
