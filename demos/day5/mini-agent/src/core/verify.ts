/**
 * Definition-of-Done verification.
 *
 * An agent's claim that a task is done is not evidence. A verifier is: it
 * re-reads the workspace and re-runs the acceptance commands, so a claim that
 * skips the work fails.
 *
 * The verifier is **independent and non-LLM**: it decides every item from the
 * workspace, never from a model report. That makes it cheap, reproducible, and
 * impossible to persuade.
 *
 * @module mini-agent/core/verify
 */

import { readFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { join } from 'node:path'

/** One decidable acceptance item. */
export interface Check {
  /** The stable identifier of the item. */
  id: string
  /** What the item requires. */
  item: string
  /** Whether the item passed. */
  passed: boolean
  /** The evidence the decision rests on. */
  evidence: string
}

/** The outcome of one verification pass. */
export interface VerifyResult {
  /** Every check, in declaration order. */
  readonly checks: readonly Check[]
  /** Whether every check passed. */
  readonly allPassed: boolean
  /** The ids of the failed checks. */
  readonly failed: readonly string[]
}

/** One file-based acceptance rule. */
export interface FileCheck {
  /** The stable identifier of the item. */
  id: string
  /** What the item requires. */
  item: string
  /** The path, relative to the workspace root. */
  path: string
  /** Whether the file must exist. */
  mustExist?: boolean
  /** Required substrings; all must be present. */
  contains?: string[]
  /** Forbidden substrings; none may be present. */
  notContains?: string[]
  /** The exact file content, compared byte for byte. */
  equals?: string
}

/** One command-based acceptance rule. */
export interface CommandCheck {
  /** The stable identifier of the item. */
  id: string
  /** What the item requires. */
  item: string
  /** The command to run. */
  command: string
  /** The arguments of the command. */
  args: string[]
  /** The expected exit code. */
  expectExit?: number
  /** Substrings the output must contain. */
  expectOutput?: string[]
  /** The timeout in milliseconds. */
  timeoutMs?: number
}

/** One rule that a file must not change. */
export interface ProtectedFile {
  /** The path, relative to the workspace root. */
  path: string
  /** The digest the file must keep. */
  sha256: string
}

/** The complete acceptance specification. */
export interface VerifySpec {
  /** The workspace root the rules are checked against. */
  workspace: string
  /** The file-based rules. */
  files?: FileCheck[]
  /** The command-based rules. */
  commands?: CommandCheck[]
  /** Files that must not change. */
  protectedFiles?: ProtectedFile[]
  /** A file that must not exist. */
  forbiddenPaths?: string[]
}

/**
 * Compute the digest of one file's bytes.
 * @param path - the file path.
 * @returns the hex digest, or undefined when the file is absent.
 */
export async function sha256File(path: string): Promise<string | undefined> {
  try {
    const bytes = await readFile(path)
    return createHash('sha256').update(bytes).digest('hex')
  } catch (_missing) {
    return undefined
  }
}

/**
 * Run one command and capture its outcome.
 * @param command - the executable.
 * @param args - the arguments.
 * @param cwd - the working directory.
 * @param timeoutMs - the timeout in milliseconds.
 * @returns the exit code and the combined output.
 */
async function runCommand(
  command: string,
  args: string[],
  cwd: string,
  timeoutMs: number,
): Promise<{ code: number; output: string }> {
  const { spawn } = await import('node:child_process')
  return await new Promise(resolve => {
    const child = spawn(command, args, { cwd, timeout: timeoutMs })
    let output = ''
    child.stdout?.on('data', chunk => { output += String(chunk) })
    child.stderr?.on('data', chunk => { output += String(chunk) })
    child.on('error', error => { resolve({ code: 127, output: output + String(error) }) })
    child.on('close', code => { resolve({ code: code ?? -1, output }) })
  })
}

/**
 * Check one file-based rule.
 * @param workspace - the workspace root.
 * @param rule - the rule.
 * @returns the check result.
 */
async function checkFile(workspace: string, rule: FileCheck): Promise<Check> {
  const path = join(workspace, rule.path)
  if (!existsSync(path)) {
    return {
      id: rule.id,
      item: rule.item,
      passed: rule.mustExist === false,
      evidence: rule.mustExist === false ? `${rule.path} is absent` : `${rule.path} is missing`,
    }
  }
  let content: string
  try {
    content = await readFile(path, 'utf8')
  } catch (error: unknown) {
    return { id: rule.id, item: rule.item, passed: false, evidence: `${rule.path} is unreadable: ${String(error)}` }
  }
  if (rule.equals !== undefined && content !== rule.equals) {
    return { id: rule.id, item: rule.item, passed: false, evidence: `${rule.path} does not match the expected content` }
  }
  const missing = (rule.contains ?? []).filter(needle => !content.includes(needle))
  if (missing.length > 0) {
    return { id: rule.id, item: rule.item, passed: false, evidence: `${rule.path} is missing ${missing.map(m => JSON.stringify(m)).join(', ')}` }
  }
  const forbidden = (rule.notContains ?? []).filter(needle => content.includes(needle))
  if (forbidden.length > 0) {
    return { id: rule.id, item: rule.item, passed: false, evidence: `${rule.path} contains ${forbidden.map(m => JSON.stringify(m)).join(', ')}` }
  }
  return { id: rule.id, item: rule.item, passed: true, evidence: `${rule.path} satisfies the rule` }
}

/**
 * Check one command-based rule.
 * @param workspace - the workspace root.
 * @param rule - the rule.
 * @returns the check result.
 */
async function checkCommand(workspace: string, rule: CommandCheck): Promise<Check> {
  const expected = rule.expectExit ?? 0
  const { code, output } = await runCommand(rule.command, rule.args, workspace, rule.timeoutMs ?? 30_000)
  if (code !== expected) {
    return {
      id: rule.id,
      item: rule.item,
      passed: false,
      evidence: `\`${rule.command} ${rule.args.join(' ')}\` exited ${code}, expected ${expected}`,
    }
  }
  const missing = (rule.expectOutput ?? []).filter(needle => !output.includes(needle))
  if (missing.length > 0) {
    return {
      id: rule.id,
      item: rule.item,
      passed: false,
      evidence: `\`${rule.command} ${rule.args.join(' ')}\` output is missing ${missing.map(m => JSON.stringify(m)).join(', ')}`,
    }
  }
  return {
    id: rule.id,
    item: rule.item,
    passed: true,
    evidence: `\`${rule.command} ${rule.args.join(' ')}\` exited ${code}`,
  }
}

/**
 * Verify a workspace against an acceptance specification.
 *
 * Every item is decided by reading the workspace or by running the
 * acceptance command. No model is consulted, so the result is reproducible.
 * @param spec - the acceptance specification.
 * @returns the check results.
 */
export async function verifyWorkspace(spec: VerifySpec): Promise<VerifyResult> {
  const checks: Check[] = []
  for (const rule of spec.files ?? []) {
    checks.push(await checkFile(spec.workspace, rule))
  }
  for (const rule of spec.commands ?? []) {
    checks.push(await checkCommand(spec.workspace, rule))
  }
  for (const rule of spec.protectedFiles ?? []) {
    const path = join(spec.workspace, rule.path)
    const digest = await sha256File(path)
    const passed = digest === rule.sha256
    checks.push({
      id: `protected:${rule.path}`,
      item: `${rule.path} must not change`,
      passed,
      evidence: passed ? `${rule.path} is unchanged` : `${rule.path} changed`,
    })
  }
  for (const path of spec.forbiddenPaths ?? []) {
    const exists = existsSync(join(spec.workspace, path))
    checks.push({
      id: `forbidden:${path}`,
      item: `${path} must not exist`,
      passed: !exists,
      evidence: exists ? `${path} exists` : `${path} is absent`,
    })
  }
  const failed = checks.filter(check => !check.passed).map(check => check.id)
  return { checks, allPassed: failed.length === 0, failed }
}

/**
 * Render a verification result as a markdown table.
 * @param result - the verification result.
 * @returns the table.
 */
export function renderVerifyTable(result: VerifyResult): string {
  const lines = ['| ID | Item | Result | Evidence |', '| --- | --- | --- | --- |']
  for (const check of result.checks) {
    lines.push(`| ${check.id} | ${check.item} | ${check.passed ? 'PASS' : 'FAIL'} | ${check.evidence} |`)
  }
  return lines.join('\n')
}
