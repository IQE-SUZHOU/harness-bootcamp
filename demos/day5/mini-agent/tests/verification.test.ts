/**
 * Tests for the Definition-of-Done verifier and the human approval gate
 * (the D3 capability).
 */

import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { mkdtemp, writeFile, mkdir, chmod } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { ApprovalGate, APPROVAL_TOKEN_PREFIX, generateApprovalToken, isApprovalToken } from '../src/core/approval.ts'
import { renderVerifyTable, sha256File, verifyWorkspace } from '../src/core/verify.ts'

/** Create a temporary workspace. */
async function tempWorkspace(): Promise<string> {
  return await mkdtemp(join(tmpdir(), 'mini-agent-verify-'))
}

test('a missing file fails a check that requires it', async () => {
  const workspace = await tempWorkspace()
  const result = await verifyWorkspace({
    workspace,
    files: [{ id: 'F1', item: 'README.md exists', path: 'README.md' }],
  })
  assert.equal(result.allPassed, false)
  assert.deepEqual(result.failed, ['F1'])
  assert.match(result.checks[0]?.evidence ?? '', /missing/)
})

test('a file with the required content passes', async () => {
  const workspace = await tempWorkspace()
  await writeFile(join(workspace, 'README.md'), '# Title\nbody\n', 'utf8')
  const result = await verifyWorkspace({
    workspace,
    files: [{ id: 'F1', item: 'README.md has the title', path: 'README.md', contains: ['# Title'] }],
  })
  assert.equal(result.allPassed, true)
  assert.deepEqual(result.failed, [])
})

test('a file missing a required substring fails', async () => {
  const workspace = await tempWorkspace()
  await writeFile(join(workspace, 'README.md'), 'no title here', 'utf8')
  const result = await verifyWorkspace({
    workspace,
    files: [{ id: 'F1', item: 'README.md has the title', path: 'README.md', contains: ['# Title'] }],
  })
  assert.equal(result.allPassed, false)
  assert.match(result.checks[0]?.evidence ?? '', /missing "# Title"/)
})

test('a forbidden substring fails the check', async () => {
  const workspace = await tempWorkspace()
  await writeFile(join(workspace, 'README.md'), 'contains CANARY_DO_NOT_CREATE', 'utf8')
  const result = await verifyWorkspace({
    workspace,
    files: [{ id: 'F1', item: 'README.md has no canary', path: 'README.md', notContains: ['CANARY_DO_NOT_CREATE'] }],
  })
  assert.equal(result.allPassed, false)
  assert.match(result.checks[0]?.evidence ?? '', /contains/)
})

test('a forbidden path fails when it exists', async () => {
  const workspace = await tempWorkspace()
  await writeFile(join(workspace, 'CANARY_DO_NOT_CREATE'), 'x', 'utf8')
  const result = await verifyWorkspace({
    workspace,
    forbiddenPaths: ['CANARY_DO_NOT_CREATE'],
  })
  assert.equal(result.allPassed, false)
  assert.equal(result.checks[0]?.id, 'forbidden:CANARY_DO_NOT_CREATE')
})

test('a command that exits zero passes', async () => {
  const workspace = await tempWorkspace()
  const result = await verifyWorkspace({
    workspace,
    commands: [{ id: 'C1', item: 'echo works', command: 'echo', args: ['ok'], expectOutput: ['ok'] }],
  })
  assert.equal(result.allPassed, true)
})

test('a command that exits non-zero fails', async () => {
  const workspace = await tempWorkspace()
  const result = await verifyWorkspace({
    workspace,
    commands: [{ id: 'C1', item: 'false fails', command: 'false', args: [] }],
  })
  assert.equal(result.allPassed, false)
  assert.match(result.checks[0]?.evidence ?? '', /exited 1/)
})

test('a command with unexpected output fails', async () => {
  const workspace = await tempWorkspace()
  const result = await verifyWorkspace({
    workspace,
    commands: [{ id: 'C1', item: 'echo says ok', command: 'echo', args: ['nope'], expectOutput: ['ok'] }],
  })
  assert.equal(result.allPassed, false)
  assert.match(result.checks[0]?.evidence ?? '', /missing "ok"/)
})

test('a protected file that changed fails', async () => {
  const workspace = await tempWorkspace()
  const path = join(workspace, 'dod.md')
  await writeFile(path, 'original', 'utf8')
  const digest = await sha256File(path)
  assert.ok(digest)
  await writeFile(path, 'tampered', 'utf8')
  const result = await verifyWorkspace({
    workspace,
    protectedFiles: [{ path: 'dod.md', sha256: digest }],
  })
  assert.equal(result.allPassed, false)
  assert.match(result.checks[0]?.evidence ?? '', /changed/)
})

test('an unchanged protected file passes', async () => {
  const workspace = await tempWorkspace()
  const path = join(workspace, 'dod.md')
  await writeFile(path, 'original', 'utf8')
  const digest = await sha256File(path)
  const result = await verifyWorkspace({
    workspace,
    protectedFiles: [{ path: 'dod.md', sha256: digest! }],
  })
  assert.equal(result.allPassed, true)
})

test('the verifier never consults a model report', async () => {
  // A file that claims completion but is wrong still fails.
  const workspace = await tempWorkspace()
  await writeFile(join(workspace, 'MAKER_REPORT.md'), '全部完成 (7/7)', 'utf8')
  await writeFile(join(workspace, 'answer.txt'), '41', 'utf8')
  const result = await verifyWorkspace({
    workspace,
    files: [{ id: 'F1', item: 'answer is 42', path: 'answer.txt', contains: ['42'] }],
  })
  assert.equal(result.allPassed, false)
})

test('the verifier renders a table', async () => {
  const workspace = await tempWorkspace()
  const result = await verifyWorkspace({
    workspace,
    files: [{ id: 'F1', item: 'README exists', path: 'README.md' }],
  })
  const table = renderVerifyTable(result)
  assert.match(table, /\| ID \| Item \| Result \| Evidence \|/)
  assert.match(table, /FAIL/)
})

test('a gate with no approver refuses', async () => {
  const gate = new ApprovalGate()
  const decision = await gate.request({ action: 'write file', reason: 'needed' })
  assert.equal(decision.kind, 'unavailable')
})

test('a gate whose approver throws refuses', async () => {
  const gate = new ApprovalGate(() => { throw new Error('approver exploded') })
  const decision = await gate.request({ action: 'write file', reason: 'needed' })
  assert.equal(decision.kind, 'unavailable')
  assert.match(decision.kind === 'unavailable' ? decision.reason : '', /approver failed/)
})

test('an approver can reject', async () => {
  const gate = new ApprovalGate(() => ({ kind: 'rejected', reason: 'not now' }))
  const decision = await gate.request({ action: 'write file', reason: 'needed' })
  assert.equal(decision.kind, 'rejected')
})

test('an approved request carries a token the gate remembers', async () => {
  const gate = new ApprovalGate(() => ({ kind: 'approved', token: 'APPROVED-BY-HUMAN-abc' }))
  const decision = await gate.request({ action: 'write file', reason: 'needed' })
  assert.equal(decision.kind, 'approved')
  if (decision.kind === 'approved') {
    assert.ok(decision.token.startsWith(APPROVAL_TOKEN_PREFIX))
    assert.ok(gate.hasToken(decision.token))
  }
  assert.equal(gate.grantedTokens.length, 1)
})

test('an approval without a token still gets one', async () => {
  const gate = new ApprovalGate(() => ({ kind: 'approved', token: '' }))
  const decision = await gate.request({ action: 'write file', reason: 'needed' })
  assert.equal(decision.kind, 'approved')
  if (decision.kind === 'approved') {
    assert.ok(decision.token.length > 0)
    assert.ok(isApprovalToken(decision.token))
  }
})

test('a generated token has the expected shape', () => {
  const token = generateApprovalToken()
  assert.ok(isApprovalToken(token))
  assert.ok(!isApprovalToken('APPROVED-BY-HUMAN-'))
  assert.ok(!isApprovalToken('forged'))
})

test('two generated tokens differ', () => {
  assert.notEqual(generateApprovalToken(), generateApprovalToken())
})
