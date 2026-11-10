/**
 * Session repository: the durable lifecycle around a session.
 *
 * The repository owns three things the bare {@link Session} does not:
 *
 * - **Persistence** — the log survives the process.
 * - **Crash repair** — a log cut short by a crash is closed with explicit
 *   "outcome unknown" records before it is used again.
 * - **Resumption** — a stored log is replayed into a fresh session, so the
 *   model still sees the earlier turns.
 *
 * @module mini-agent/core/repository
 */

import { SessionStore } from './persistence.ts'
import type { RepairReport, SessionHeader } from './persistence.ts'
import { buildRepairClosers, findInterrupted } from './persistence.ts'
import { Session } from './session.ts'
import type { SessionEvent } from './session.ts'

/** The outcome of resuming a stored session. */
export interface ResumeResult {
  /** The session, seeded with the stored events and any repair closers. */
  readonly session: Session
  /** The header of the stored session. */
  readonly header: SessionHeader
  /** What the repair closed, if anything. */
  readonly repair: RepairReport
}

/**
 * A durable session repository.
 */
export class SessionRepository {
  /** The underlying durable store. */
  readonly store: SessionStore

  constructor(store: SessionStore) {
    this.store = store
  }

  /**
   * Create a fresh session and persist it.
   * @param id - the session id.
   * @param cwd - the working directory the session belongs to.
   * @returns the new session.
   */
  async create(id: string, cwd: string): Promise<Session> {
    const session = new Session(id)
    await this.store.save(session, cwd)
    return session
  }

  /**
   * Persist a session's current log.
   * @param session - the session to save.
   * @param cwd - the working directory the session belongs to.
   */
  async save(session: Session, cwd: string): Promise<void> {
    await this.store.save(session, cwd)
  }

  /**
   * Resume a stored session, repairing it first when a crash left it open.
   *
   * The repair closes an interrupted tool call, step, and turn with explicit
   * records. A tool call whose outcome is unknown is recorded as an error
   * that says so, never as a fabricated success.
   * @param id - the session id.
   * @returns the resumed session and what the repair closed.
   */
  async resume(id: string): Promise<ResumeResult | undefined> {
    const stored = await this.store.read(id)
    if (stored === undefined) return undefined

    const session = new Session(id)
    for (const { event } of stored.events) {
      session.append(event)
    }

    const interrupted = findInterrupted(stored.events)
    const closers = buildRepairClosers(stored.events, interrupted)
    for (const closer of closers) {
      session.append(closer)
    }
    if (closers.length > 0) {
      await this.store.save(session, stored.header.cwd)
    }
    return {
      session,
      header: stored.header,
      repair: {
        closers,
        interruptedToolCalls: interrupted.calls.length,
        interruptedSteps: interrupted.steps.length,
        interruptedTurns: interrupted.turns.length,
      },
    }
  }

  /**
   * The events a stored session would need to close, without applying them.
   * @param id - the session id.
   * @returns the repair report, or undefined when the session is absent.
   */
  async inspect(id: string): Promise<RepairReport | undefined> {
    const stored = await this.store.read(id)
    if (stored === undefined) return undefined
    const interrupted = findInterrupted(stored.events)
    return {
      closers: buildRepairClosers(stored.events, interrupted),
      interruptedToolCalls: interrupted.calls.length,
      interruptedSteps: interrupted.steps.length,
      interruptedTurns: interrupted.turns.length,
    }
  }
}

/** One recorded event as stored on disk. */
export type StoredSessionEvent = SessionEvent
