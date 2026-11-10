/**
 * Session persistence: durable storage and crash repair.
 *
 * A session that lives only in memory cannot survive the process, so the log
 * is written to disk as append-only JSONL. The store also repairs a log that
 * was cut short by a crash: an open tool call, step, or turn is closed with
 * explicit "outcome unknown" records, so the next run starts from a
 * consistent log instead of a half-finished one.
 *
 * The repair never invents a tool result. It records that the outcome is
 * unknown, which lets the model decide whether a retry is safe.
 *
 * @module mini-agent/core/persistence
 */

import { mkdir, readFile, readdir, writeFile, appendFile, rename } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import type { Session, SessionEvent, StoredEvent } from './session.ts'

/** The version stamped into a persisted session file. */
export const SESSION_FORMAT_VERSION = 1

/** The file name of a persisted session inside its directory. */
export const SESSION_FILE_NAME = 'session.jsonl'

/** The header written at the top of a persisted session file. */
export interface SessionHeader {
  /** The format version. */
  version: number
  /** The session identity. */
  id: string
  /** The epoch milliseconds when the session was created. */
  createdAt: number
  /** The working directory the session belongs to. */
  cwd: string
}

/** One persisted line: the header, or an event. */
type PersistedLine =
  | ({ type: 'session' } & SessionHeader)
  | ({ type: 'event'; seq: number; time: number; data: SessionEvent })

/** Where the sessions live. */
export interface StoreOptions {
  /** The directory holding one subdirectory per session. */
  root: string
}

/**
 * The result of repairing an interrupted log.
 */
export interface RepairReport {
  /** The events appended to close the interrupted work. */
  readonly closers: SessionEvent[]
  /** The number of tool calls that had no result. */
  readonly interruptedToolCalls: number
  /** The number of steps that were left open. */
  readonly interruptedSteps: number
  /** The number of turns that were left open. */
  readonly interruptedTurns: number
}

/** The tool result recorded for a call whose outcome is unknown. */
export const UNKNOWN_OUTCOME_TEXT =
  'The tool call was interrupted before its result was recorded. Its outcome is unknown. '
  + 'Do not retry blindly: check the workspace state first.'

/**
 * Find the events that a crash left open.
 *
 * An open tool call is a `tool/call` with no matching `tool/result`; an open
 * step is a `step/start` with no matching `step/end`; an open turn is a
 * `turn/start` with no matching `turn/end`.
 * @param events - the recorded events.
 * @returns the open calls, steps, and turns.
 */
export function findInterrupted(events: readonly StoredEvent[]): {
  calls: { turn: number; step: number; id: string; name: string }[]
  steps: { turn: number; step: number }[]
  turns: number[]
} {
  /** Tool calls that received a result. */
  const answered = new Set<string>()
  for (const { event } of events) {
    if (event.kind === 'tool/result') answered.add(event.id)
  }
  /** Steps that were closed. */
  const closedSteps = new Set<string>()
  for (const { event } of events) {
    if (event.kind === 'step/end') closedSteps.add(`${event.turn}/${event.step}`)
  }
  /** Turns that were closed. */
  const closedTurns = new Set<number>()
  for (const { event } of events) {
    if (event.kind === 'turn/end') closedTurns.add(event.turn)
  }

  const calls: { turn: number; step: number; id: string; name: string }[] = []
  const steps: { turn: number; step: number }[] = []
  const turns: number[] = []
  const seenSteps = new Set<string>()
  for (const { event } of events) {
    if (event.kind === 'tool/call' && !answered.has(event.id)) {
      calls.push({ turn: event.turn, step: event.step, id: event.id, name: event.name })
    }
    if (event.kind === 'step/start' && !closedSteps.has(`${event.turn}/${event.step}`)) {
      const key = `${event.turn}/${event.step}`
      if (!seenSteps.has(key)) {
        seenSteps.add(key)
        steps.push({ turn: event.turn, step: event.step })
      }
    }
    if (event.kind === 'turn/start' && !closedTurns.has(event.turn)) {
      if (!turns.includes(event.turn)) turns.push(event.turn)
    }
  }
  return { calls, steps, turns }
}

/**
 * Build the events that close an interrupted log.
 *
 * The order matters: each tool call is closed first, then its step, then its
 * turn, so the repaired log reads the way the original run would have.
 * @param events - the recorded events.
 * @param report - the interrupted work.
 * @returns the closing events.
 */
export function buildRepairClosers(
  events: readonly StoredEvent[],
  report: { calls: { turn: number; step: number; id: string; name: string }[]; steps: { turn: number; step: number }[]; turns: number[] },
): SessionEvent[] {
  const closers: SessionEvent[] = []
  for (const call of report.calls) {
    closers.push({
      kind: 'tool/result',
      turn: call.turn,
      step: call.step,
      id: call.id,
      name: call.name,
      isError: true,
      text: UNKNOWN_OUTCOME_TEXT,
    })
  }
  for (const step of report.steps) {
    closers.push({ kind: 'step/end', turn: step.turn, step: step.step })
  }
  for (const turn of report.turns) {
    closers.push({ kind: 'turn/end', turn, reason: { kind: 'aborted', reason: 'interrupted before the process ended' } })
  }
  return closers
}

/**
 * A durable store of sessions.
 *
 * One directory per session holds one append-only JSONL file. The file is
 * rewritten atomically on save, so a crash during a save leaves the previous
 * complete file rather than a truncated one.
 */
export class SessionStore {
  /** The directory holding one subdirectory per session. */
  readonly root: string

  constructor(options: StoreOptions) {
    this.root = options.root
  }

  /** The directory of one session. */
  directoryOf(id: string): string {
    return join(this.root, id)
  }

  /** The path of one session's log file. */
  fileOf(id: string): string {
    return join(this.directoryOf(id), SESSION_FILE_NAME)
  }

  /** Every session id in the store. */
  async list(): Promise<string[]> {
    if (!existsSync(this.root)) return []
    const entries = await readdir(this.root, { withFileTypes: true })
    return entries
      .filter(entry => entry.isDirectory() && existsSync(this.fileOf(entry.name)))
      .map(entry => entry.name)
      .sort()
  }

  /**
   * Read one persisted session.
   * @param id - the session id.
   * @returns the header and the recorded events, or undefined when absent.
   */
  async read(id: string): Promise<{ header: SessionHeader; events: StoredEvent[] } | undefined> {
    let raw: string
    try {
      raw = await readFile(this.fileOf(id), 'utf8')
    } catch (_missing) {
      return undefined
    }
    const header = { version: SESSION_FORMAT_VERSION, id, createdAt: 0, cwd: '' }
    const events: StoredEvent[] = []
    for (const line of raw.split('\n')) {
      if (line.trim().length === 0) continue
      let parsed: PersistedLine
      try {
        parsed = JSON.parse(line) as PersistedLine
      } catch (_invalidJson) {
        // A torn last line is expected after a crash: the rest of the log is
        // still valid, so the partial line is dropped rather than failing the
        // whole read.
        continue
      }
      if (parsed.type === 'session') {
        header.version = parsed.version
        header.createdAt = parsed.createdAt
        header.cwd = parsed.cwd
        continue
      }
      events.push({ seq: parsed.seq, event: parsed.data })
    }
    return { header, events }
  }

  /**
   * Write one session, replacing any previous file.
   *
   * The content is written to a temporary file and renamed, so an interrupted
   * save leaves the previous complete log in place.
   * @param session - the session to save.
   * @param cwd - the working directory the session belongs to.
   */
  async save(session: Session, cwd: string): Promise<void> {
    await mkdir(this.directoryOf(session.id), { recursive: true })
    const header: PersistedLine = {
      type: 'session',
      version: SESSION_FORMAT_VERSION,
      id: session.id,
      createdAt: Date.now(),
      cwd,
    }
    const lines = [JSON.stringify(header)]
    for (const { seq, event } of session.snapshot()) {
      const line: PersistedLine = { type: 'event', seq, time: Date.now(), data: event }
      lines.push(JSON.stringify(line))
    }
    const target = this.fileOf(session.id)
    const temporary = `${target}.tmp`
    await writeFile(temporary, `${lines.join('\n')}\n`, 'utf8')
    await rename(temporary, target)
  }

  /**
   * Append events to a persisted session without rewriting the file.
   * @param id - the session id.
   * @param events - the events to append.
   */
  async append(id: string, events: readonly SessionEvent[]): Promise<void> {
    if (events.length === 0) return
    await mkdir(this.directoryOf(id), { recursive: true })
    const lines = events.map(event => JSON.stringify({
      type: 'event',
      seq: -1,
      time: Date.now(),
      data: event,
    } satisfies PersistedLine))
    await appendFile(this.fileOf(id), `${lines.join('\n')}\n`, 'utf8')
  }
}
