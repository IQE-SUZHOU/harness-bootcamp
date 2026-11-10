/**
 * Shared vocabulary for the mini agent: content blocks, tool schemas, and the
 * LLM request/response types.
 *
 * The shapes mirror `@deepseek-ai/dsh-llm` so the agent loop, the tool
 * registry, and the provider adapter speak the same language as the full
 * harness, while staying dependency-free.
 *
 * @module mini-agent/core/types
 */

/** Plain text visible to the end user. */
export interface TextBlock {
  type: 'text'
  text: string
}

/** Reasoning / thinking content, distinct from visible text. */
export interface ReasoningBlock {
  type: 'reasoning'
  text: string
}

/** A tool invocation requested by the model. */
export interface ToolCallBlock {
  type: 'tool-call'
  /** Provider-issued call id; correlates with the matching tool result. */
  id: string
  /** Registered tool name. */
  name: string
  /** Raw JSON string as produced by the model. */
  arguments: string
}

/** The result of one executed tool call. */
export interface ToolResultBlock {
  type: 'tool-result'
  /** Correlates with the originating {@link ToolCallBlock.id}. */
  id: string
  /** Whether the call failed. */
  isError: boolean
  /** Model-facing result text. */
  text: string
}

/** Every block kind the agent can carry. */
export type ContentBlock =
  | TextBlock
  | ReasoningBlock
  | ToolCallBlock
  | ToolResultBlock

/** Why a model response stopped. */
export type FinishReason =
  | { kind: 'stop' }
  | { kind: 'tool-calls' }
  | { kind: 'max-tokens' }
  | { kind: 'aborted'; reason: string }
  | { kind: 'error'; reason: string }

/** Token accounting for one model call. */
export interface TokenUsage {
  inputTokens: number
  outputTokens: number
  totalTokens?: number
  reasoningTokens?: number
}

/** JSON-schema description of a tool, as sent to the model. */
export interface ToolSchema {
  /** Tool name; unique within one registry. */
  name: string
  /** Human-readable description sent to the model. */
  description: string
  /** JSON Schema object for the arguments. */
  parameters: Record<string, unknown>
}

/** One conversation message. */
export interface Message {
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: ContentBlock[]
}

/** A complete model request. */
export interface GenerateOptions {
  /** Registered provider route selecting the adapter instance. */
  provider: string
  /** Exact model id. */
  model: string
  /** Ordered conversation history, exactly as the provider sees it. */
  messages: Message[]
  /** Tool schemas available to the model. */
  tools?: ToolSchema[]
  /** System prompt text, mapped to the provider's system slot. */
  system?: string
  /** Sampling temperature. */
  temperature?: number
  /** Per-request output cap. */
  maxTokens?: number
  /** Cancellation signal for the whole request. */
  signal?: AbortSignal
}

/** One streamed chunk of a model response. */
export type StreamChunk =
  | { type: 'block-start'; index: number; blockType: 'text' | 'reasoning' | 'tool-call' }
  | { type: 'text-delta'; index: number; text: string }
  | { type: 'reasoning-delta'; index: number; text: string }
  | { type: 'tool-call-delta'; index: number; id: string; name?: string; argumentsDelta: string }
  | { type: 'block-end'; index: number; block: ContentBlock }
  | { type: 'usage'; usage: TokenUsage }
  | { type: 'finish'; reason: FinishReason }
