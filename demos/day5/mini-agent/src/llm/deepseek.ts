/**
 * DeepSeek Messages API adapter.
 *
 * Speaks the Anthropic-style Messages wire format that the DeepSeek endpoint
 * exposes: `POST {baseURL}/v1/messages` with an SSE response streamed back.
 *
 * @module mini-agent/llm/deepseek
 */

import type { LlmAdapter } from '../core/llm.ts'
import type { ContentBlock, FinishReason, GenerateOptions, Message, StreamChunk, TokenUsage } from '../core/types.ts'

/** Connection settings for the DeepSeek adapter. */
export interface DeepSeekOptions {
  /** API key sent as `x-api-key`. */
  apiKey: string
  /** Endpoint root; `/v1` is appended when absent. */
  baseURL?: string
  /** Provider route key this adapter serves. */
  provider?: string
  /** Anthropic-style version header. */
  apiVersion?: string
}

/** The default DeepSeek endpoint root. */
const DEFAULT_BASE_URL = 'https://api.deepseek.com'

/** The default model used when none is configured. */
export const DEFAULT_MODEL = 'deepseek-chat'

/** One wire content block. */
interface WireBlock {
  type: string
  text?: string
  thinking?: string
  id?: string
  name?: string
  input?: unknown
  tool_use_id?: string
  content?: unknown
  is_error?: boolean
}

/** One wire message. */
interface WireMessage {
  role: 'user' | 'assistant' | 'system'
  content: WireBlock[]
}

/** The request body sent to the Messages endpoint. */
interface WireRequest {
  model: string
  stream: true
  messages: WireMessage[]
  max_tokens: number
  system?: string
  temperature?: number
  tools?: { name: string; description: string; input_schema: Record<string, unknown> }[]
}

/**
 * Read one JSON object field as a string.
 * @param value - the raw field value.
 * @param fallback - the value used when the field is absent.
 * @returns the string field value.
 */
function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

/**
 * Read one value as a plain object.
 * @param value - the raw field value.
 * @returns the object, or an empty object.
 */
function asObject(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

/**
 * Map one wire stop reason to a finish reason.
 * @param raw - the wire stop reason.
 * @returns the matching finish reason.
 */
function stopReason(raw: unknown): FinishReason {
  switch (raw) {
    case 'end_turn':
    case 'stop_sequence':
      return { kind: 'stop' }
    case 'tool_use':
      return { kind: 'tool-calls' }
    case 'max_tokens':
      return { kind: 'max-tokens' }
    default:
      return { kind: 'stop' }
  }
}

/**
 * Convert the agent's message history into the Messages wire format.
 *
 * Tool results become `user` messages carrying `tool_result` blocks, because
 * the Messages API models a tool result as a user turn.
 * @param messages - the derived request history.
 * @param system - the system prompt text.
 * @returns the wire messages and the system prompt.
 */
export function toWireMessages(messages: readonly Message[], system: string | undefined): {
  messages: WireMessage[]
  system: string | undefined
} {
  const wire: WireMessage[] = []
  for (const message of messages) {
    if (message.role === 'system') continue
    if (message.role === 'assistant') {
      const content: WireBlock[] = []
      for (const block of message.content) {
        if (block.type === 'text') {
          if (block.text.length > 0) content.push({ type: 'text', text: block.text })
          continue
        }
        if (block.type === 'reasoning') continue
        if (block.type === 'tool-call') {
          content.push({
            type: 'tool_use',
            id: block.id,
            name: block.name,
            input: parseToolInput(block.arguments),
          })
        }
      }
      if (content.length > 0) wire.push({ role: 'assistant', content })
      continue
    }
    if (message.role === 'tool') {
      const content: WireBlock[] = []
      for (const block of message.content) {
        if (block.type !== 'tool-result') continue
        content.push({
          type: 'tool_result',
          tool_use_id: block.id,
          content: [{ type: 'text', text: block.text }],
          ...block.isError ? { is_error: true } : {},
        })
      }
      if (content.length > 0) wire.push({ role: 'user', content })
      continue
    }
    const content: WireBlock[] = []
    for (const block of message.content) {
      if (block.type === 'text' && block.text.length > 0) content.push({ type: 'text', text: block.text })
    }
    if (content.length > 0) wire.push({ role: 'user', content })
  }
  return { messages: wire, system: system !== undefined && system.length > 0 ? system : undefined }
}

/**
 * Parse one tool-call argument payload.
 * @param raw - the raw JSON string produced by the model.
 * @returns the parsed value, or an empty object when the JSON is invalid.
 */
function parseToolInput(raw: string): unknown {
  try {
    const parsed: unknown = JSON.parse(raw === '' ? '{}' : raw)
    return parsed !== null && typeof parsed === 'object' ? parsed : {}
  } catch (_invalidToolJson) {
    return {}
  }
}

/**
 * The DeepSeek Messages API adapter.
 */
export class DeepSeekAdapter implements LlmAdapter {
  /** The provider route key this adapter serves. */
  readonly provider: string
  private readonly apiKey: string
  private readonly baseURL: string
  private readonly apiVersion: string

  constructor(options: DeepSeekOptions) {
    this.apiKey = options.apiKey
    this.baseURL = (options.baseURL ?? DEFAULT_BASE_URL).replace(/\/+$/, '')
    this.provider = options.provider ?? 'deepseek'
    this.apiVersion = options.apiVersion ?? '2023-06-01'
  }

  /**
   * Stream one model response.
   * @param options - the complete request.
   * @returns the response chunk stream.
   */
  async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    const { messages, system } = toWireMessages(options.messages, options.system)
    const body: WireRequest = {
      model: options.model,
      stream: true,
      messages,
      max_tokens: options.maxTokens ?? 4096,
      ...system === undefined ? {} : { system },
      ...options.temperature === undefined ? {} : { temperature: options.temperature },
      ...options.tools === undefined || options.tools.length === 0 ? {} : {
        tools: options.tools.map(tool => ({
          name: tool.name,
          description: tool.description,
          input_schema: tool.parameters,
        })),
      },
    }
    const response = await fetch(`${this.baseURL}/v1/messages`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'accept': 'text/event-stream',
        'x-api-key': this.apiKey,
        'anthropic-version': this.apiVersion,
      },
      body: JSON.stringify(body),
      ...options.signal === undefined ? {} : { signal: options.signal },
    })
    if (!response.ok) {
      const detail = await response.text().catch(() => '')
      throw new Error(`DeepSeek request failed with HTTP ${response.status}: ${detail.slice(0, 500)}`)
    }
    if (response.body === null) {
      throw new Error('DeepSeek response carried no body')
    }
    yield* this.readStream(response.body)
  }

  /**
   * Decode the SSE response into the harness chunk protocol.
   * @param body - the response body stream.
   * @returns the chunk stream.
   */
  private async *readStream(body: ReadableStream<Uint8Array>): AsyncIterable<StreamChunk> {
    const usage: TokenUsage = { inputTokens: 0, outputTokens: 0 }
    let started = false
    let reason: FinishReason | undefined
    const blocks = new Map<number, {
      type: 'text' | 'reasoning' | 'tool-call'
      closed: boolean
      text: string
      id?: string
      name?: string
      json: string
    }>()

    for await (const event of parseSse(body)) {
      if (event.type === 'error') {
        throw new Error(`DeepSeek stream error: ${JSON.stringify(event).slice(0, 500)}`)
      }
      if (event.type === 'message_start') {
        started = true
        this.applyUsage(usage, asObject(asObject(event.message).usage))
        continue
      }
      if (!started) continue
      if (event.type === 'content_block_start') {
        const wireIndex = typeof event.index === 'number' ? event.index : blocks.size
        const content = asObject(event.content_block)
        const type = content.type === 'thinking'
          ? 'reasoning'
          : content.type === 'tool_use'
            ? 'tool-call'
            : 'text'
        const initialText = type === 'text'
          ? asString(content.text)
          : type === 'reasoning'
            ? asString(content.thinking)
            : ''
        blocks.set(wireIndex, {
          type,
          closed: false,
          text: initialText,
          ...type === 'tool-call' ? { id: asString(content.id), name: asString(content.name), json: '' } : {},
        })
        yield { type: 'block-start', index: wireIndex, blockType: type }
        if (initialText.length > 0) {
          yield { type: type === 'text' ? 'text-delta' : 'reasoning-delta', index: wireIndex, text: initialText }
        } else if (type === 'tool-call') {
          yield { type: 'tool-call-delta', index: wireIndex, id: asString(content.id), name: asString(content.name), argumentsDelta: '' }
        }
        continue
      }
      if (event.type === 'content_block_delta') {
        const wireIndex = typeof event.index === 'number' ? event.index : 0
        const block = blocks.get(wireIndex)
        if (block === undefined) continue
        const delta = asObject(event.delta)
        if (delta.type === 'text_delta' && block.type === 'text') {
          const text = asString(delta.text)
          block.text += text
          yield { type: 'text-delta', index: wireIndex, text }
          continue
        }
        if (delta.type === 'thinking_delta' && block.type === 'reasoning') {
          const text = asString(delta.thinking)
          block.text += text
          yield { type: 'reasoning-delta', index: wireIndex, text }
          continue
        }
        if (delta.type === 'input_json_delta' && block.type === 'tool-call') {
          const argumentsDelta = asString(delta.partial_json)
          block.json += argumentsDelta
          yield { type: 'tool-call-delta', index: wireIndex, id: block.id ?? '', argumentsDelta }
        }
        continue
      }
      if (event.type === 'content_block_stop') {
        const wireIndex = typeof event.index === 'number' ? event.index : 0
        const block = blocks.get(wireIndex)
        if (block === undefined || block.closed) continue
        block.closed = true
        let final: ContentBlock
        if (block.type === 'text') {
          final = { type: 'text', text: block.text }
        } else if (block.type === 'reasoning') {
          final = { type: 'reasoning', text: block.text }
        } else {
          final = { type: 'tool-call', id: block.id ?? '', name: block.name ?? '', arguments: block.json }
        }
        yield { type: 'block-end', index: wireIndex, block: final }
        continue
      }
      if (event.type === 'message_delta') {
        const delta = asObject(event.delta)
        if (delta.stop_reason != null) reason = stopReason(delta.stop_reason)
        if (event.usage !== undefined) this.applyUsage(usage, asObject(event.usage))
        continue
      }
      if (event.type === 'message_stop') {
        if (reason === undefined) reason = { kind: 'stop' }
        usage.totalTokens = usage.inputTokens + usage.outputTokens
        yield { type: 'usage', usage }
        yield { type: 'finish', reason }
        return
      }
    }
    // The stream ended without a terminal event.
    if (reason === undefined) reason = { kind: 'error', reason: 'DeepSeek stream ended before message_stop' }
    usage.totalTokens = usage.inputTokens + usage.outputTokens
    yield { type: 'usage', usage }
    yield { type: 'finish', reason }
  }

  /**
   * Merge one wire usage object into the running totals.
   * @param usage - the running totals.
   * @param raw - the wire usage object.
   */
  private applyUsage(usage: TokenUsage, raw: Record<string, unknown>): void {
    const input = raw.input_tokens
    const output = raw.output_tokens
    if (typeof input === 'number') usage.inputTokens = input
    if (typeof output === 'number') usage.outputTokens = output
  }
}

/**
 * Decode an SSE byte stream into JSON events.
 * @param body - the response body stream.
 * @returns the decoded events, in arrival order.
 */
async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<Record<string, unknown>> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      const data = frame
        .split('\n')
        .filter(line => line.startsWith('data:'))
        .map(line => line.slice(5).trim())
        .join('\n')
      if (data.length > 0 && data !== '[DONE]') {
        try {
          yield JSON.parse(data) as Record<string, unknown>
        } catch (_invalidSseJson) {
          throw new Error('DeepSeek SSE contained invalid JSON')
        }
      }
      boundary = buffer.indexOf('\n\n')
    }
  }
}
