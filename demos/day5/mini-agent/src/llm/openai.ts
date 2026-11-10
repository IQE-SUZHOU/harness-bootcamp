/**
 * OpenAI-compatible Chat Completions adapter.
 *
 * Most providers expose the OpenAI wire format: `POST {baseURL}/chat/completions`
 * with an `Authorization: Bearer` header and an SSE stream of
 * `chat.completion.chunk` frames. This adapter serves all of them:
 * OpenAI, Moonshot, Qwen/DashScope, Together, Groq, vLLM, Ollama, LM Studio,
 * and any local gateway that mimics the same shape.
 *
 * @module mini-agent/llm/openai
 */

import type { LlmAdapter } from '../core/llm.ts'
import type { ContentBlock, FinishReason, GenerateOptions, Message, StreamChunk, TokenUsage } from '../core/types.ts'

/** Connection settings for the OpenAI-compatible adapter. */
export interface OpenAiOptions {
  /** API key sent as `Authorization: Bearer`. */
  apiKey?: string
  /** Endpoint root; `/v1` is appended when absent. */
  baseURL?: string
  /** Provider route key this adapter serves. */
  provider?: string
  /** Extra headers merged into every request. */
  headers?: Record<string, string>
  /**
   * Provider-specific request fields merged into every body.
   *
   * Providers expose parameters the OpenAI schema does not define — MiniMax
   * uses `reasoning_effort` and `thinking`, for example. These fields are
   * merged last, so a provider-specific value wins over the derived one.
   */
  extraBody?: Record<string, unknown>
  /** Send `max_completion_tokens` instead of `max_tokens`. */
  useMaxCompletionTokens?: boolean
}

/** The default OpenAI endpoint root. */
const DEFAULT_BASE_URL = 'https://api.openai.com/v1'

/** One OpenAI chat-completions request body. */
interface WireRequest {
  model: string
  stream: true
  stream_options: { include_usage: true }
  messages: { role: string; content: unknown; tool_calls?: unknown[]; tool_call_id?: string }[]
  tools?: { type: string; function: { name: string; description: string; parameters: unknown } }[]
  temperature?: number
  max_tokens?: number
  max_completion_tokens?: number
  /** Provider-specific fields the OpenAI schema does not define. */
  [key: string]: unknown
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
 * Map one OpenAI finish reason to a finish reason.
 * @param raw - the wire finish reason.
 * @returns the matching finish reason.
 */
function stopReason(raw: unknown): FinishReason {
  switch (raw) {
    case 'tool_calls':
    case 'function_call':
      return { kind: 'tool-calls' }
    case 'length':
      return { kind: 'max-tokens' }
    case 'stop':
      return { kind: 'stop' }
    default:
      return { kind: 'stop' }
  }
}

/**
 * Convert the agent's message history into OpenAI chat messages.
 *
 * Tool results become `tool` messages carrying `tool_call_id`, because the
 * Chat Completions API models a tool result as its own message.
 * @param messages - the derived request history.
 * @returns the wire messages.
 */
export function toChatMessages(messages: readonly Message[]): WireRequest['messages'] {
  const wire: WireRequest['messages'] = []
  for (const message of messages) {
    if (message.role === 'system') {
      const text = message.content
        .filter(block => block.type === 'text')
        .map(block => block.text)
        .join('')
      if (text.length > 0) wire.push({ role: 'system', content: text })
      continue
    }
    if (message.role === 'assistant') {
      const text = message.content
        .filter(block => block.type === 'text')
        .map(block => block.text)
        .join('')
      const calls = message.content.filter((block): block is Extract<typeof block, { type: 'tool-call' }> =>
        block.type === 'tool-call')
      wire.push({
        role: 'assistant',
        content: text.length > 0 ? text : null,
        ...calls.length > 0 ? {
          tool_calls: calls.map(call => ({
            id: call.id,
            type: 'function',
            function: { name: call.name, arguments: call.arguments },
          })),
        } : {},
      })
      continue
    }
    if (message.role === 'tool') {
      for (const block of message.content) {
        if (block.type !== 'tool-result') continue
        wire.push({ role: 'tool', content: block.text, tool_call_id: block.id })
      }
      continue
    }
    const text = message.content
      .filter(block => block.type === 'text')
      .map(block => block.text)
      .join('')
    if (text.length > 0) wire.push({ role: 'user', content: text })
  }
  return wire
}

/**
 * The OpenAI-compatible Chat Completions adapter.
 */
export class OpenAiAdapter implements LlmAdapter {
  /** The provider route key this adapter serves. */
  readonly provider: string
  /** The endpoint root this adapter posts to. */
  readonly baseURL: string
  private readonly apiKey: string | undefined
  private readonly extraHeaders: Record<string, string>
  /** Provider-specific request fields merged into every body. */
  private readonly extraBody: Record<string, unknown>
  /** Send `max_completion_tokens` instead of `max_tokens`. */
  private readonly useMaxCompletionTokens: boolean

  constructor(options: OpenAiOptions = {}) {
    this.apiKey = options.apiKey
    this.baseURL = (options.baseURL ?? DEFAULT_BASE_URL).replace(/\/+$/, '')
    this.provider = options.provider ?? 'openai'
    this.extraHeaders = options.headers ?? {}
    this.extraBody = options.extraBody ?? {}
    this.useMaxCompletionTokens = options.useMaxCompletionTokens === true
  }

  /**
   * Stream one model response.
   * @param options - the complete request.
   * @returns the response chunk stream.
   */
  async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    const body: WireRequest = {
      model: options.model,
      stream: true,
      stream_options: { include_usage: true },
      messages: toChatMessages(options.messages),
      ...options.temperature === undefined ? {} : { temperature: options.temperature },
      ...options.maxTokens === undefined ? {} : this.useMaxCompletionTokens
        ? { max_completion_tokens: options.maxTokens }
        : { max_tokens: options.maxTokens },
      ...options.tools === undefined || options.tools.length === 0 ? {} : {
        tools: options.tools.map(tool => ({
          type: 'function',
          function: { name: tool.name, description: tool.description, parameters: tool.parameters },
        })),
      },
      // Provider-specific fields win over the derived ones.
      ...this.extraBody,
    }
    const response = await fetch(`${this.baseURL}/chat/completions`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'text/event-stream',
        ...this.apiKey === undefined ? {} : { authorization: `Bearer ${this.apiKey}` },
        ...this.extraHeaders,
      },
      body: JSON.stringify(body),
      ...options.signal === undefined ? {} : { signal: options.signal },
    })
    if (!response.ok) {
      const detail = await response.text().catch(() => '')
      throw new Error(`OpenAI-compatible request failed with HTTP ${response.status}: ${detail.slice(0, 500)}`)
    }
    if (response.body === null) {
      throw new Error('OpenAI-compatible response carried no body')
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
    /** The tool calls of the current completion, keyed by their wire index. */
    const calls = new Map<number, { id: string; name: string; args: string }>()
    let blockStarted = false
    let text = ''

    for await (const event of parseSse(body)) {
      const error = event.error
      if (error !== undefined) {
        throw new Error(`OpenAI-compatible stream error: ${JSON.stringify(error).slice(0, 500)}`)
      }
      const choices = Array.isArray(event.choices) ? event.choices : []
      for (const rawChoice of choices) {
        const choice = rawChoice as {
          delta?: {
            content?: unknown
            reasoning_content?: unknown
            tool_calls?: { index?: number; id?: string; function?: { name?: string; arguments?: string } }[]
          }
          finish_reason?: unknown
        }
        const delta = choice.delta
        if (delta?.content !== undefined && delta.content !== null) {
          const piece = asString(delta.content)
          if (piece.length > 0) {
            if (!blockStarted) {
              blockStarted = true
              yield { type: 'block-start', index: 0, blockType: 'text' }
            }
            text += piece
            yield { type: 'text-delta', index: 0, text: piece }
          }
        }
        // Some providers expose chain-of-thought under `reasoning_content`.
        const reasoning = delta?.reasoning_content
        if (reasoning !== undefined && reasoning !== null) {
          const piece = asString(reasoning)
          if (piece.length > 0) {
            yield { type: 'reasoning-delta', index: 1, text: piece }
          }
        }
        for (const rawCall of delta?.tool_calls ?? []) {
          const index = typeof rawCall.index === 'number' ? rawCall.index : 0
          const existing = calls.get(index)
          const entry = existing ?? { id: '', name: '', args: '' }
          if (typeof rawCall.id === 'string') entry.id = rawCall.id
          if (typeof rawCall.function?.name === 'string') entry.name = rawCall.function.name
          if (typeof rawCall.function?.arguments === 'string') entry.args += rawCall.function.arguments
          calls.set(index, entry)
        }
      }
      if (event.usage !== undefined && event.usage !== null) {
        const raw = event.usage as { prompt_tokens?: unknown; completion_tokens?: unknown; total_tokens?: unknown }
        if (typeof raw.prompt_tokens === 'number') usage.inputTokens = raw.prompt_tokens
        if (typeof raw.completion_tokens === 'number') usage.outputTokens = raw.completion_tokens
        if (typeof raw.total_tokens === 'number') usage.totalTokens = raw.total_tokens
      }
      if (choices.length > 0 && choices[0]?.finish_reason) {
        const reason = stopReason(choices[0].finish_reason)
        // Tool calls arrive after the text blocks; close the text block first.
        if (blockStarted) {
          yield { type: 'block-end', index: 0, block: { type: 'text', text } }
          blockStarted = false
        }
        for (const [index, call] of calls) {
          yield { type: 'block-start', index: index + 10, blockType: 'tool-call' }
          yield {
            type: 'tool-call-delta',
            index: index + 10,
            id: call.id,
            name: call.name,
            argumentsDelta: call.args,
          }
          yield {
            type: 'block-end',
            index: index + 10,
            block: { type: 'tool-call', id: call.id, name: call.name, arguments: call.args },
          }
        }
        usage.totalTokens ??= usage.inputTokens + usage.outputTokens
        yield { type: 'usage', usage }
        yield { type: 'finish', reason }
        return
      }
    }
    // The stream ended without a terminal frame.
    if (blockStarted) {
      yield { type: 'block-end', index: 0, block: { type: 'text', text } }
    }
    usage.totalTokens ??= usage.inputTokens + usage.outputTokens
    yield { type: 'usage', usage }
    yield { type: 'finish', reason: { kind: 'error', reason: 'stream ended before the finish frame' } }
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
          throw new Error('OpenAI-compatible SSE contained invalid JSON')
        }
      }
      boundary = buffer.indexOf('\n\n')
    }
  }
}
