/**
 * The agent loop: drives one session through turn and step boundaries.
 *
 * A turn is one user input. A step is one model request plus the tool calls
 * that request produced. The loop continues stepping while the model asks for
 * tools, and ends the turn when the model answers with text only.
 *
 * @module mini-agent/core/agent
 */

import { BlockAssembler } from './llm.ts'
import type { LlmAdapter } from './llm.ts'
import { Session } from './session.ts'
import type { TurnEndReason } from './session.ts'
import { createStopConditions } from './stop-conditions.ts'
import type { StopConditions, StopConditionsConfig } from './stop-conditions.ts'
import { ToolRegistry, validateAgainstSchema } from './tools.ts'
import type { ContentBlock, GenerateOptions, Message } from './types.ts'

/** Options for one agent run. */
export interface AgentOptions {
  /** Provider route served by the adapter. */
  provider: string
  /** Exact model id. */
  model: string
  /** System prompt sent with every request. */
  systemPrompt: string
  /** Sampling temperature. */
  temperature?: number
  /** Per-request output cap. */
  maxTokens?: number
  /** Maximum tool calls executed concurrently within one step. */
  maxParallelToolCalls?: number
  /** The limits that let a turn brake itself. */
  stopConditions?: StopConditionsConfig
  /** Called for each streamed text delta, for live terminal output. */
  onText?: (text: string) => void
  /** Called when a tool call starts executing. */
  onToolCall?: (name: string, args: Record<string, unknown>) => void
  /** Called when a tool call finishes, successfully or not. */
  onToolResult?: (name: string, isError: boolean, text: string) => void
  /** Called when a stop condition ends the turn. */
  onStopped?: (kind: 'max-steps' | 'timeout' | 'max-tokens', message: string) => void
}

/** The result of one completed turn. */
export interface TurnResult {
  /** Why the turn ended. */
  reason: TurnEndReason
  /** The assistant text produced during the turn. */
  text: string
  /** The number of model requests made. */
  steps: number
}

/** Maximum tool calls executed concurrently within one step. */
const DEFAULT_MAX_PARALLEL_TOOL_CALLS = 4

/**
 * One agent bound to one session, one adapter, and one tool registry.
 */
export class Agent {
  /** The durable log backing this agent. */
  readonly session: Session
  /** The provider route served by the adapter. */
  private readonly adapter: LlmAdapter
  /** The tools available to the model. */
  private readonly registry: ToolRegistry
  /** The run configuration. */
  private readonly options: AgentOptions
  /** The limits that let a turn brake itself. */
  private readonly limits: StopConditions

  constructor(
    adapter: LlmAdapter,
    registry: ToolRegistry,
    options: AgentOptions,
    sessionId = 'mini-session',
  ) {
    this.adapter = adapter
    this.registry = registry
    this.options = options
    this.limits = createStopConditions(options.stopConditions)
    this.session = new Session(sessionId)
  }

  /**
   * Run one turn for the given user input.
   *
   * The turn ends when the model answers with text and no tool calls, when the
   * output cap is reached, or when a model or tool failure ends the turn.
   * @param input - the user text for this turn.
   * @param signal - cancellation signal for the whole turn.
   * @returns the turn outcome.
   */
  async run(input: string, signal?: AbortSignal): Promise<TurnResult> {
    const turn = this.turnNumber() + 1
    this.session.append({ kind: 'turn/start', turn })
    const controller = new AbortController()
    const onAbort = (): void => { controller.abort(signal?.reason) }
    signal?.addEventListener('abort', onAbort, { once: true })
    const startedAt = Date.now()
    let reason: TurnEndReason = { kind: 'completed' }
    let text = ''
    let step = 0
    try {
      if (signal?.aborted === true) {
        reason = { kind: 'aborted', reason: 'cancelled before the first step' }
        return { reason, text, steps: 0 }
      }
      this.session.append({ kind: 'user/message', turn, step: 0, text: input })
      while (true) {
        // The limits are checked before each request, so a tripped limit stops
        // the turn without spending another model call.
        const stop = this.limits.check(step, this.limits.totalTokens, Date.now() - startedAt)
        if (stop !== undefined) {
          reason = { kind: 'stopped', stopKind: stop.kind, message: stop.message }
          this.options.onStopped?.(stop.kind, stop.message)
          break
        }
        step += 1
        this.session.append({ kind: 'step/start', turn, step })
        const outcome = await this.step(turn, step, controller.signal)
        if (outcome.kind === 'error') {
          reason = { kind: 'error', message: outcome.message }
          this.session.append({ kind: 'error', turn, step, message: outcome.message })
          break
        }
        if (outcome.kind === 'aborted') {
          reason = { kind: 'aborted', reason: outcome.message }
          break
        }
        if (outcome.kind === 'max-tokens') {
          reason = { kind: 'max-tokens' }
          text = outcome.text
          // The capped request still consumed tokens, so the budget counts it.
          if (outcome.usage !== undefined) {
            this.limits.addUsage(outcome.usage.inputTokens, outcome.usage.outputTokens)
          }
          break
        }
        text = outcome.text
        if (outcome.usage !== undefined) {
          this.limits.addUsage(outcome.usage.inputTokens, outcome.usage.outputTokens)
        }
        // The assistant message is logged whenever the model produced content:
        // a tool-call-only response carries the call the next request must
        // answer, so dropping it would lose the tool's identity.
        if (outcome.content.length > 0) {
          this.session.append({
            kind: 'assistant/message',
            turn,
            step,
            content: outcome.content,
            ...outcome.usage === undefined ? {} : { usage: outcome.usage },
          })
        }
        // The model asked for tools: run them and request again.
        if (!outcome.hasToolCalls) break
      }
      return { reason, text, steps: step }
    } finally {
      signal?.removeEventListener('abort', onAbort)
      this.session.append({ kind: 'turn/end', turn, reason })
    }
  }

  /** The number of turns already recorded. */
  private turnNumber(): number {
    let last = 0
    for (const { event } of this.session.snapshot()) {
      if (event.kind === 'turn/start') last = event.turn
    }
    return last
  }

  /** The outcome of one model request plus its tool executions. */
  private async step(
    turn: number,
    step: number,
    signal: AbortSignal,
  ): Promise<
    | { kind: 'ok'; text: string; content: ContentBlock[]; hasToolCalls: boolean; usage?: { inputTokens: number; outputTokens: number } }
    | { kind: 'error'; message: string }
    | { kind: 'aborted'; message: string }
    | { kind: 'max-tokens'; text: string; usage?: { inputTokens: number; outputTokens: number } }
  > {
    const request = this.buildRequest(signal)
    const assembler = new BlockAssembler()
    let text = ''
    try {
      for await (const chunk of this.adapter.stream(request)) {
        if (signal.aborted) return { kind: 'aborted', message: 'cancelled' }
        if (chunk.type === 'text-delta') {
          text += chunk.text
          this.options.onText?.(chunk.text)
        }
        assembler.push(chunk)
      }
    } catch (error: unknown) {
      if (signal.aborted) return { kind: 'aborted', message: 'cancelled' }
      const message = error instanceof Error ? error.message : String(error)
      return { kind: 'error', message }
    }
    const finish = assembler.finish
    if (finish?.kind === 'error') return { kind: 'error', message: finish.reason }
    if (finish?.kind === 'aborted') return { kind: 'aborted', message: finish.reason }

    const blocks = assembler.blocks()
    const toolCalls = blocks.filter((block): block is Extract<ContentBlock, { type: 'tool-call' }> =>
      block.type === 'tool-call')

    if (toolCalls.length > 0) {
      await this.executeToolCalls(turn, step, toolCalls, signal)
      return {
        kind: 'ok',
        text,
        content: blocks,
        hasToolCalls: true,
        ...assembler.usage === undefined ? {} : { usage: assembler.usage },
      }
    }
    if (finish?.kind === 'max-tokens') {
      return {
        kind: 'max-tokens',
        text,
        ...assembler.usage === undefined ? {} : { usage: assembler.usage },
      }
    }
    return {
      kind: 'ok',
      text,
      content: blocks,
      hasToolCalls: false,
      ...assembler.usage === undefined ? {} : { usage: assembler.usage },
    }
  }

  /** Build the model request from the session log. */
  private buildRequest(signal: AbortSignal): GenerateOptions {
    const messages: Message[] = this.session.deriveMessages()
    const tools = this.registry.schemas()
    return {
      provider: this.options.provider,
      model: this.options.model,
      system: this.options.systemPrompt,
      messages,
      ...tools.length > 0 ? { tools } : {},
      ...this.options.temperature === undefined ? {} : { temperature: this.options.temperature },
      ...this.options.maxTokens === undefined ? {} : { maxTokens: this.options.maxTokens },
      signal,
    }
  }

  /** Execute the tool calls of one step, in batches bounded by the parallelism limit. */
  private async executeToolCalls(
    turn: number,
    step: number,
    toolCalls: readonly Extract<ContentBlock, { type: 'tool-call' }>[],
    signal: AbortSignal,
  ): Promise<void> {
    const limit = Math.max(1, this.options.maxParallelToolCalls ?? DEFAULT_MAX_PARALLEL_TOOL_CALLS)
    for (let index = 0; index < toolCalls.length; index += limit) {
      const batch = toolCalls.slice(index, index + limit)
      await Promise.all(batch.map(call => this.executeToolCall(turn, step, call, signal)))
    }
  }

  /** Execute one tool call and record its result in the session log. */
  private async executeToolCall(
    turn: number,
    step: number,
    call: Extract<ContentBlock, { type: 'tool-call' }>,
    signal: AbortSignal,
  ): Promise<void> {
    this.session.append({ kind: 'tool/call', turn, step, id: call.id, name: call.name, arguments: call.arguments })
    const definition = this.registry.get(call.name)
    if (definition === undefined) {
      this.recordToolResult(turn, step, call, true, `unknown tool "${call.name}"`)
      return
    }
    let args: Record<string, unknown>
    try {
      const parsed: unknown = JSON.parse(call.arguments === '' ? '{}' : call.arguments)
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('arguments must be a JSON object')
      }
      args = parsed as Record<string, unknown>
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error)
      this.recordToolResult(turn, step, call, true, `invalid tool arguments: ${message}`)
      return
    }
    const violations = validateAgainstSchema(definition.parameters, args)
    if (violations.length > 0) {
      this.recordToolResult(turn, step, call, true, `invalid tool arguments: ${violations.join('; ')}`)
      return
    }
    this.options.onToolCall?.(call.name, args)
    try {
      const text = await definition.execute(args, signal)
      this.recordToolResult(turn, step, call, false, text)
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error)
      this.recordToolResult(turn, step, call, true, message)
    }
  }

  /** Record one tool result in the session log and notify the caller. */
  private recordToolResult(
    turn: number,
    step: number,
    call: Extract<ContentBlock, { type: 'tool-call' }>,
    isError: boolean,
    text: string,
  ): void {
    this.session.append({ kind: 'tool/result', turn, step, id: call.id, name: call.name, isError, text })
    this.options.onToolResult?.(call.name, isError, text)
  }
}
