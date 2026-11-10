/**
 * Tests for deterministic tool-result pruning.
 */

import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { Agent } from '../src/core/agent.ts'
import { Session } from '../src/core/session.ts'
import {
  codePointLength,
  PRUNE_DEFAULTS,
  PRUNE_MARKER,
  pruneToolResult,
  resolvePruneConfig,
} from '../src/core/prune.ts'
import { ToolRegistry } from '../src/core/tools.ts'
import type { GenerateOptions, StreamChunk } from '../src/core/types.ts'

test('the default budgets are the documented ones', () => {
  assert.equal(PRUNE_DEFAULTS.thresholdChars, 8192)
  assert.equal(PRUNE_DEFAULTS.headChars, 4096)
  assert.equal(PRUNE_DEFAULTS.tailChars, 1024)
})

test('codePointLength counts code points, not UTF-16 units', () => {
  // An emoji outside the basic plane is two UTF-16 units but one code point.
  assert.equal('😀'.length, 2)
  assert.equal(codePointLength('😀'), 1)
  assert.equal(codePointLength('a😀b'), 3)
})

test('an invalid budget is rejected at resolution', () => {
  assert.throws(() => resolvePruneConfig({ thresholdChars: 0 }), /thresholdChars.*positive/)
  assert.throws(() => resolvePruneConfig({ thresholdChars: -1 }), /thresholdChars.*positive/)
  assert.throws(() => resolvePruneConfig({ headChars: -1 }), /headChars.*non-negative/)
  assert.throws(() => resolvePruneConfig({ tailChars: 1.5 }), /tailChars.*non-negative/)
})

test('the emitted size must fit inside the threshold', () => {
  // head 100 + marker + tail 100 exceeds a threshold of 50.
  assert.throws(
    () => resolvePruneConfig({ thresholdChars: 50, headChars: 100, tailChars: 100 }),
    /must be at most thresholdChars/,
  )
})

test('a result within budget is returned unchanged', () => {
  const config = resolvePruneConfig()
  const text = 'short output'
  const result = pruneToolResult(text, config)
  assert.equal(result.pruned, false)
  assert.equal(result.text, text)
  assert.equal(result.charsBefore, result.charsAfter)
})

test('a result exactly at the threshold is not pruned', () => {
  const config = resolvePruneConfig({ thresholdChars: 100, headChars: 40, tailChars: 10 })
  const text = 'x'.repeat(100)
  const result = pruneToolResult(text, config)
  assert.equal(result.pruned, false)
  assert.equal(result.charsAfter, 100)
})

test('an over-budget result keeps its head and tail', () => {
  const config = resolvePruneConfig({ thresholdChars: 100, headChars: 10, tailChars: 5 })
  const text = 'H'.repeat(10) + 'M'.repeat(500) + 'T'.repeat(5)
  const result = pruneToolResult(text, config)
  assert.equal(result.pruned, true)
  assert.ok(result.text.startsWith('H'.repeat(10)))
  assert.ok(result.text.endsWith('T'.repeat(5)))
  assert.ok(result.text.includes(PRUNE_MARKER))
  // The middle is gone.
  assert.ok(!result.text.includes('M'.repeat(500)))
})

test('the marker appears exactly once', () => {
  const config = resolvePruneConfig({ thresholdChars: 100, headChars: 10, tailChars: 5 })
  const result = pruneToolResult('M'.repeat(500), config)
  const occurrences = result.text.split(PRUNE_MARKER).length - 1
  assert.equal(occurrences, 1)
})

test('the pruned result fits inside the threshold', () => {
  const config = resolvePruneConfig({ thresholdChars: 100, headChars: 40, tailChars: 10 })
  const result = pruneToolResult('x'.repeat(10_000), config)
  assert.ok(result.charsAfter <= config.thresholdChars)
  assert.ok(result.charsAfter < result.charsBefore)
})

test('pruning never splits a surrogate pair', () => {
  // Each emoji is two UTF-16 units; slicing by code unit would leave a lone
  // surrogate, which corrupts the text the provider receives.
  const config = resolvePruneConfig({ thresholdChars: 50, headChars: 5, tailChars: 5 })
  const text = '😀'.repeat(100)
  const result = pruneToolResult(text, config)
  // No lone surrogate survives.
  assert.ok(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/.test(result.text))
  assert.ok(!/(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(result.text))
})

test('pruning is idempotent', () => {
  const config = resolvePruneConfig({ thresholdChars: 100, headChars: 10, tailChars: 5 })
  const once = pruneToolResult('M'.repeat(500), config)
  const twice = pruneToolResult(once.text, config)
  // The pruned text is already within budget, so it is not pruned again.
  assert.equal(twice.pruned, false)
  assert.equal(twice.text, once.text)
})

test('the durable log keeps the full-fidelity tool result', () => {
  const session = new Session('s1', resolvePruneConfig({ thresholdChars: 100, headChars: 10, tailChars: 5 }))
  session.append({ kind: 'turn/start', turn: 1 })
  session.append({
    kind: 'assistant/message',
    turn: 1,
    step: 1,
    content: [{ type: 'tool-call', id: 'c1', name: 'bash', arguments: '{}' }],
  })
  const full = 'M'.repeat(500)
  session.append({ kind: 'tool/result', turn: 1, step: 1, id: 'c1', name: 'bash', isError: false, text: full })
  // The log keeps the whole result.
  const stored = session.snapshot().find(entry => entry.event.kind === 'tool/result')
  assert.equal(stored?.event.kind, 'tool/result')
  if (stored?.event.kind === 'tool/result') {
    assert.equal(stored.event.text, full)
  }
  // The derived request carries the pruned one.
  const messages = session.deriveMessages()
  const toolMessage = messages.find(message => message.role === 'tool')
  assert.ok(toolMessage)
  const block = toolMessage.content[0]
  assert.equal(block?.type, 'tool-result')
  if (block?.type === 'tool-result') {
    assert.ok(block.text.length < full.length)
    assert.ok(block.text.includes(PRUNE_MARKER))
  }
  assert.equal(session.prunedToolResults, 1)
})

test('the pruned count is zero when every result is within budget', () => {
  const session = new Session('s1')
  session.append({
    kind: 'assistant/message',
    turn: 1,
    step: 1,
    content: [{ type: 'tool-call', id: 'c1', name: 'bash', arguments: '{}' }],
  })
  session.append({ kind: 'tool/result', turn: 1, step: 1, id: 'c1', name: 'bash', isError: false, text: 'small' })
  session.deriveMessages()
  assert.equal(session.prunedToolResults, 0)
})

test('the agent sends the pruned result on the next request', async () => {
  const adapter = {
    provider: 'scripted',
    requests: [] as GenerateOptions[],
    async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
      this.requests.push(options)
      if (this.requests.length === 1) {
        yield { type: 'block-start', index: 0, blockType: 'tool-call' }
        yield { type: 'tool-call-delta', index: 0, id: 'c1', name: 'bash', argumentsDelta: '{}' }
        yield { type: 'block-end', index: 0, block: { type: 'tool-call', id: 'c1', name: 'bash', arguments: '{}' } }
        yield { type: 'finish', reason: { kind: 'tool-calls' } }
        return
      }
      yield { type: 'block-start', index: 0, blockType: 'text' }
      yield { type: 'text-delta', index: 0, text: 'done' }
      yield { type: 'block-end', index: 0, block: { type: 'text', text: 'done' } }
      yield { type: 'finish', reason: { kind: 'stop' } }
    },
  }
  const registry = new ToolRegistry()
  registry.register({
    name: 'bash',
    description: 'run a command',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
    async execute() { return 'M'.repeat(5000) },
  })
  const agent = new Agent(adapter, registry, {
    provider: 'scripted',
    model: 'm',
    systemPrompt: 'sys',
    prune: { thresholdChars: 200, headChars: 50, tailChars: 20 },
  })
  await agent.run('run it')
  // The second request carries the pruned tool result.
  const second = adapter.requests[1]
  const toolMessage = second?.messages.find(message => message.role === 'tool')
  assert.ok(toolMessage)
  const block = toolMessage.content[0]
  if (block?.type === 'tool-result') {
    assert.ok(block.text.length < 5000)
    assert.ok(block.text.includes(PRUNE_MARKER))
  }
  // The durable log still holds the full result.
  const stored = agent.session.snapshot().find(entry => entry.event.kind === 'tool/result')
  if (stored?.event.kind === 'tool/result') {
    assert.equal(stored.event.text.length, 5000)
  }
})
