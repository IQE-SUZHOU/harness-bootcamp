/**
 * Tests for session persistence and crash repair (the D2 capability).
 */

import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { SessionRepository } from '../src/core/repository.ts'
import { SessionStore, findInterrupted, buildRepairClosers } from '../src/core/persistence.ts'
import { Session } from '../src/core/session.ts'

/** Create a temporary store root. */
async function tempRoot(): Promise<string> {
  return await mkdtemp(join(tmpdir(), 'mini-agent-store-'))
}

test('a session survives a save and reload', async () => {
  const root = await tempRoot()
  const repository = new SessionRepository(new SessionStore({ root }))
  const session = await repository.create('s1', '/work')
  session.append({ kind: 'turn/start', turn: 1 })
  session.append({ kind: 'user/message', turn: 1, step: 0, text: 'hello' })
  await repository.save(session, '/work')

  const resumed = await repository.resume('s1')
  assert.ok(resumed)
  assert.equal(resumed.header.cwd, '/work')
  const messages = resumed.session.deriveMessages()
  assert.equal(messages.length, 1)
  assert.equal(messages[0]?.role, 'user')
})

test('the store lists the sessions it holds', async () => {
  const root = await tempRoot()
  const repository = new SessionRepository(new SessionStore({ root }))
  await repository.create('alpha', '/work')
  await repository.create('beta', '/work')
  assert.deepEqual(await repository.store.list(), ['alpha', 'beta'])
})

test('resuming an absent session returns undefined', async () => {
  const root = await tempRoot()
  const repository = new SessionRepository(new SessionStore({ root }))
  assert.equal(await repository.resume('missing'), undefined)
})

test('an interrupted tool call is closed with an unknown outcome', async () => {
  const root = await tempRoot()
  const store = new SessionStore({ root })
  const repository = new SessionRepository(store)
  const session = await repository.create('s1', '/work')
  session.append({ kind: 'turn/start', turn: 1 })
  session.append({ kind: 'step/start', turn: 1, step: 1 })
  session.append({
    kind: 'assistant/message',
    turn: 1,
    step: 1,
    content: [{ type: 'tool-call', id: 'c1', name: 'bash', arguments: '{}' }],
  })
  session.append({ kind: 'tool/call', turn: 1, step: 1, id: 'c1', name: 'bash', arguments: '{}' })
  // The process dies here: no tool result, no step end, no turn end.
  await repository.save(session, '/work')

  const resumed = await repository.resume('s1')
  assert.ok(resumed)
  assert.equal(resumed.repair.interruptedToolCalls, 1)
  assert.equal(resumed.repair.interruptedSteps, 1)
  assert.equal(resumed.repair.interruptedTurns, 1)

  const kinds = resumed.session.snapshot().map(stored => stored.event.kind)
  // The repair closes the call, then the step, then the turn.
  assert.deepEqual(kinds.slice(-3), ['tool/result', 'step/end', 'turn/end'])

  const result = resumed.session.snapshot().find(stored => stored.event.kind === 'tool/result')
  assert.equal(result?.event.kind, 'tool/result')
  if (result?.event.kind === 'tool/result') {
    assert.equal(result.event.isError, true)
    assert.match(result.event.text, /outcome is unknown/i)
    assert.match(result.event.text, /do not retry blindly/i)
  }
})

test('a repaired log leaves no open turn, step, or tool call', async () => {
  const root = await tempRoot()
  const repository = new SessionRepository(new SessionStore({ root }))
  const session = await repository.create('s1', '/work')
  session.append({ kind: 'turn/start', turn: 1 })
  session.append({ kind: 'step/start', turn: 1, step: 1 })
  session.append({ kind: 'tool/call', turn: 1, step: 1, id: 'c1', name: 'bash', arguments: '{}' })
  await repository.save(session, '/work')

  const resumed = await repository.resume('s1')
  assert.ok(resumed)
  // Repairing again finds nothing left open.
  const second = await repository.inspect('s1')
  assert.equal(second?.interruptedToolCalls, 0)
  assert.equal(second?.interruptedSteps, 0)
  assert.equal(second?.interruptedTurns, 0)
})

test('a completed session needs no repair', async () => {
  const root = await tempRoot()
  const repository = new SessionRepository(new SessionStore({ root }))
  const session = await repository.create('s1', '/work')
  session.append({ kind: 'turn/start', turn: 1 })
  session.append({ kind: 'step/start', turn: 1, step: 1 })
  session.append({ kind: 'tool/call', turn: 1, step: 1, id: 'c1', name: 'bash', arguments: '{}' })
  session.append({ kind: 'tool/result', turn: 1, step: 1, id: 'c1', name: 'bash', isError: false, text: 'ok' })
  session.append({ kind: 'step/end', turn: 1, step: 1 })
  session.append({ kind: 'turn/end', turn: 1, reason: { kind: 'completed' } })
  await repository.save(session, '/work')

  const resumed = await repository.resume('s1')
  assert.ok(resumed)
  assert.equal(resumed.repair.closers.length, 0)
})

test('the repair never invents a successful tool result', async () => {
  const root = await tempRoot()
  const repository = new SessionRepository(new SessionStore({ root }))
  const session = await repository.create('s1', '/work')
  session.append({ kind: 'turn/start', turn: 1 })
  session.append({ kind: 'tool/call', turn: 1, step: 1, id: 'c1', name: 'bash', arguments: '{}' })
  await repository.save(session, '/work')

  const resumed = await repository.resume('s1')
  assert.ok(resumed)
  for (const stored of resumed.session.snapshot()) {
    if (stored.event.kind !== 'tool/result') continue
    assert.equal(stored.event.isError, true)
  }
})

test('a torn last line is dropped and the rest of the log survives', async () => {
  const root = await tempRoot()
  const store = new SessionStore({ root })
  const repository = new SessionRepository(store)
  const session = await repository.create('s1', '/work')
  session.append({ kind: 'turn/start', turn: 1 })
  session.append({ kind: 'user/message', turn: 1, step: 0, text: 'kept' })
  await repository.save(session, '/work')

  // Simulate a crash mid-write: append a partial JSON line.
  const path = store.fileOf('s1')
  const content = await readFile(path, 'utf8')
  await writeFile(path, `${content}{"type":"event","seq":99,"da`, 'utf8')

  const resumed = await repository.resume('s1')
  assert.ok(resumed)
  const messages = resumed.session.deriveMessages()
  assert.equal(messages.length, 1)
  assert.equal(messages[0]?.content[0]?.type, 'text')
})

test('findInterrupted reports the open work', () => {
  const session = new Session('s1')
  session.append({ kind: 'turn/start', turn: 1 })
  session.append({ kind: 'step/start', turn: 1, step: 1 })
  session.append({ kind: 'tool/call', turn: 1, step: 1, id: 'c1', name: 'bash', arguments: '{}' })
  const interrupted = findInterrupted(session.snapshot())
  assert.equal(interrupted.calls.length, 1)
  assert.equal(interrupted.calls[0]?.id, 'c1')
  assert.equal(interrupted.steps.length, 1)
  assert.deepEqual(interrupted.turns, [1])
})

test('the repair closers close the call, then the step, then the turn', () => {
  const session = new Session('s1')
  session.append({ kind: 'turn/start', turn: 1 })
  session.append({ kind: 'step/start', turn: 1, step: 1 })
  session.append({ kind: 'tool/call', turn: 1, step: 1, id: 'c1', name: 'bash', arguments: '{}' })
  const interrupted = findInterrupted(session.snapshot())
  const closers = buildRepairClosers(session.snapshot(), interrupted)
  assert.deepEqual(closers.map(closer => closer.kind), ['tool/result', 'step/end', 'turn/end'])
})
