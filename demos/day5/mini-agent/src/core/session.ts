/**
 * Durable session log. Every model-visible input is reconstructable from this
 * log, so a session can be replayed or inspected after the fact.
 *
 * Mirrors the event-log approach of `@deepseek-ai/dsh-session` in a single
 * in-memory structure.
 *
 * @module mini-agent/core/session
 */

import type { ContentBlock, Message, TokenUsage } from './types.ts'

/** One recorded session event. */
export type SessionEvent =
  | { kind: 'turn/start'; turn: number }
  | { kind: 'turn/end'; turn: number; reason: TurnEndReason }
  | { kind: 'step/start'; turn: number; step: number }
  | { kind: 'step/end'; turn: number; step: number }
  | { kind: 'user/message'; turn: number; step: number; text: string }
  | { kind: 'assistant/message'; turn: number; step: number; content: ContentBlock[]; usage?: TokenUsage }
  | { kind: 'tool/call'; turn: number; step: number; id: string; name: string; arguments: string }
  | { kind: 'tool/result'; turn: number; step: number; id: string; name: string; isError: boolean; text: string }
  | { kind: 'error'; turn: number; step: number; message: string }

/** Why one turn ended. */
export type TurnEndReason =
  | { kind: 'completed' }
  | { kind: 'max-tokens' }
  | { kind: 'aborted'; reason: string }
  | { kind: 'error'; message: string }

/** One recorded event with its monotonically increasing sequence number. */
export interface StoredEvent {
  seq: number
  event: SessionEvent
}

/**
 * Append-only session log.
 *
 * The log is the single source of truth: {@link Session.deriveMessages}
 * projects it into the request history, so a replayed session produces the
 * same model request as the original run.
 */
export class Session {
  /** The session identity. */
  readonly id: string
  /** Monotonic sequence counter shared by every recorded event. */
  private seq = 0
  private readonly events: StoredEvent[] = []
  /** Cached projection of the derived request messages. */
  private derived: Message[] | undefined

  constructor(id: string) {
    this.id = id
  }

  /**
   * Record one event.
   * @param event - the event to append.
   * @returns the stored event with its assigned sequence number.
   */
  append(event: SessionEvent): StoredEvent {
    const stored: StoredEvent = { seq: this.seq++, event }
    this.events.push(stored)
    // Any append invalidates the derived projection.
    this.derived = undefined
    return stored
  }

  /** Every recorded event, in append order. */
  snapshot(): readonly StoredEvent[] {
    return this.events
  }

  /** The number of recorded events. */
  get size(): number {
    return this.events.length
  }

  /**
   * Project the log into the ordered request history.
   *
   * The provider requires every tool result to directly follow the assistant
   * message that requested it, so the projection walks the log in order and
   * emits one `tool` message per recorded call, immediately after its
   * assistant message. A result without a matching call is dropped, because
   * the provider rejects it.
   * @returns the derived request messages.
   */
  deriveMessages(): Message[] {
    if (this.derived !== undefined) return this.derived
    /** Tool results keyed by call id. */
    const results = new Map<string, { isError: boolean; text: string }>()
    for (const { event } of this.events) {
      if (event.kind !== 'tool/result') continue
      results.set(event.id, { isError: event.isError, text: event.text })
    }
    /** Each assistant message paired with the ids of the calls it requested. */
    const entries: { message: Message; callIds: string[] }[] = []
    for (const { event } of this.events) {
      if (event.kind === 'user/message') {
        entries.push({ message: { role: 'user', content: [{ type: 'text', text: event.text }] }, callIds: [] })
        continue
      }
      if (event.kind !== 'assistant/message') continue
      const callIds = event.content
        .filter((block): block is Extract<typeof block, { type: 'tool-call' }> => block.type === 'tool-call')
        .map(block => block.id)
      entries.push({ message: { role: 'assistant', content: event.content }, callIds })
    }
    // Tool results follow their assistant message, in call order.
    const messages: Message[] = []
    for (const { message, callIds } of entries) {
      messages.push(message)
      for (const id of callIds) {
        const result = results.get(id)
        if (result === undefined) continue
        messages.push({
          role: 'tool',
          content: [{ type: 'tool-result', id, isError: result.isError, text: result.text }],
        })
      }
    }
    this.derived = messages
    return messages
  }
}
