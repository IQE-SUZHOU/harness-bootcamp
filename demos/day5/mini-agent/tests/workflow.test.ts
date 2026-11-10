/**
 * Tests for fan-out / fan-in and the failure-propagation semantics
 * (the D4 capability).
 */

import { strict as assert } from 'node:assert'
import { test } from 'node:test'

import { checkPlainJson, resolveConcurrency, runWorkflow } from '../src/core/workflow.ts'

test('a fan-out returns one part per branch, in input order', async () => {
  const outcome = await runWorkflow(
    [{ label: 'ci', task: 'a' }, { label: 'cd', task: 'b' }, { label: 'iac', task: 'c' }],
    async branch => `result-${branch.label}`,
  )
  assert.equal(outcome.kind, 'completed')
  if (outcome.kind !== 'completed') return
  assert.deepEqual(outcome.parts, ['result-ci', 'result-cd', 'result-iac'])
})

test('an ordinary branch failure yields null and the others complete', async () => {
  const outcome = await runWorkflow(
    [{ label: 'ok1', task: 'a' }, { label: 'boom', task: 'b' }, { label: 'ok2', task: 'c' }],
    async branch => {
      if (branch.label === 'boom') throw new Error('branch failed')
      return `OK-${branch.label}`
    },
  )
  assert.equal(outcome.kind, 'completed')
  if (outcome.kind !== 'completed') return
  assert.deepEqual(outcome.parts, ['OK-ok1', null, 'OK-ok2'])
})

test('the fan-in receives only the survivors', async () => {
  let received: string[] = []
  const outcome = await runWorkflow(
    [{ label: 'ok1', task: 'a' }, { label: 'boom', task: 'b' }],
    async branch => {
      if (branch.label === 'boom') throw new Error('branch failed')
      return 'survivor'
    },
    {
      fanIn: 'summarize',
      summarize: async (_task, survivors) => {
        received = survivors
        return 'summary'
      },
    },
  )
  assert.equal(outcome.kind, 'completed')
  if (outcome.kind !== 'completed') return
  assert.deepEqual(received, ['survivor'])
  assert.equal(outcome.summary, 'summary')
})

test('the total agent cap fails the whole run', async () => {
  const outcome = await runWorkflow(
    [{ label: 'a', task: 'a' }, { label: 'b', task: 'b' }, { label: 'c', task: 'c' }],
    async () => 'never',
    { limits: { maxTotal: 2 } },
  )
  assert.equal(outcome.kind, 'failed')
  if (outcome.kind !== 'failed') return
  assert.equal(outcome.fatal.kind, 'agent-cap')
  assert.match(outcome.fatal.message, /total agent cap \(2\)/)
})

test('a branch timeout nulls that branch', async () => {
  const outcome = await runWorkflow(
    [{ label: 'slow', task: 'a' }, { label: 'fast', task: 'b' }],
    async branch => {
      if (branch.label === 'slow') await new Promise(resolve => { setTimeout(resolve, 200) })
      return 'done'
    },
    { limits: { branchTimeoutMs: 30 } },
  )
  assert.equal(outcome.kind, 'completed')
  if (outcome.kind !== 'completed') return
  assert.equal(outcome.parts[0], null)
  assert.equal(outcome.parts[1], 'done')
})

test('a run timeout fails the whole run', async () => {
  const outcome = await runWorkflow(
    [{ label: 'slow', task: 'a' }],
    async () => await new Promise(resolve => { setTimeout(() => { resolve('late') }, 500) }),
    { limits: { runTimeoutMs: 30 } },
  )
  assert.equal(outcome.kind, 'failed')
  if (outcome.kind !== 'failed') return
  assert.equal(outcome.fatal.kind, 'timeout')
})

test('the concurrency cap is observed', async () => {
  let active = 0
  let maxActive = 0
  const branches = Array.from({ length: 6 }, (_value, index) => ({ label: `b${index}`, task: 'x' }))
  const outcome = await runWorkflow(branches, async () => {
    active += 1
    maxActive = Math.max(maxActive, active)
    await new Promise(resolve => { setTimeout(resolve, 20) })
    active -= 1
    return 'ok'
  }, { limits: { maxConcurrent: 2 } })
  assert.equal(outcome.kind, 'completed')
  assert.equal(maxActive, 2)
  if (outcome.kind !== 'completed') return
  assert.equal(outcome.maxActive, 2)
})

test('the routing record pairs every branch with its outcome', async () => {
  const outcome = await runWorkflow(
    [{ label: 'ok1', task: 'a' }, { label: 'boom', task: 'b' }],
    async branch => {
      if (branch.label === 'boom') throw new Error('nope')
      return 'fine'
    },
  )
  assert.equal(outcome.kind, 'completed')
  if (outcome.kind !== 'completed') return
  assert.equal(outcome.routing.length, 2)
  const ok = outcome.routing.find(record => record.label === 'ok1')
  const failed = outcome.routing.find(record => record.label === 'boom')
  assert.equal(ok?.outcome, 'ok')
  assert.equal(failed?.outcome, 'failed')
  assert.ok((ok?.endedAt ?? 0) >= (ok?.startedAt ?? 0))
})

test('an empty fan-out completes with no parts', async () => {
  const outcome = await runWorkflow([], async () => 'never')
  assert.equal(outcome.kind, 'completed')
  if (outcome.kind !== 'completed') return
  assert.deepEqual(outcome.parts, [])
  assert.equal(outcome.maxActive, 0)
})

test('an explicit concurrency cap is used verbatim', () => {
  assert.equal(resolveConcurrency(3), 3)
  assert.equal(resolveConcurrency(1), 1)
})

test('an omitted or zero concurrency means auto, not disabled', () => {
  // The engine computes min(16, max(1, parallelism - 2)); it never means
  // "no concurrency".
  assert.ok(resolveConcurrency(0) >= 1)
  assert.ok(resolveConcurrency(undefined) >= 1)
  assert.ok(resolveConcurrency(undefined) <= 16)
})

test('the branch runner receives the branch task, not the branch object', async () => {
  // The runner receives the whole branch, so it must read `.task` itself.
  // Passing the object as the prompt sends the model JSON it cannot answer.
  const seen: string[] = []
  await runWorkflow(
    [{ label: 'a', task: 'the actual task' }],
    async branch => {
      seen.push(branch.task)
      return 'ok'
    },
  )
  assert.deepEqual(seen, ['the actual task'])
})

test('a plain JSON value passes the serializability check', () => {
  assert.equal(checkPlainJson({ a: 1, b: ['x', null, true] }), undefined)
  assert.equal(checkPlainJson([]), undefined)
  assert.equal(checkPlainJson(null), undefined)
  assert.equal(checkPlainJson('text'), undefined)
  assert.equal(checkPlainJson(42), undefined)
})

test('a non-JSON value fails the serializability check', () => {
  assert.ok(checkPlainJson(undefined) !== undefined)
  assert.ok(checkPlainJson(Number.NaN) !== undefined)
  assert.ok(checkPlainJson(() => 1) !== undefined)
  assert.ok(checkPlainJson([undefined]) !== undefined)
  assert.ok(checkPlainJson({ a: undefined }) !== undefined)
  assert.ok(checkPlainJson(new Map()) !== undefined)
})
