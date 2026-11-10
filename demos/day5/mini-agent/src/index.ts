/**
 * Public entry point of the mini agent.
 *
 * @module mini-agent
 */

export { Agent } from './core/agent.ts'
export type { AgentOptions, TurnResult } from './core/agent.ts'
export { Session } from './core/session.ts'
export type { SessionEvent, StoredEvent, TurnEndReason } from './core/session.ts'
export { ToolRegistry, validateAgainstSchema } from './core/tools.ts'
export type { ToolDefinition } from './core/tools.ts'
export { BlockAssembler } from './core/llm.ts'
export type { LlmAdapter } from './core/llm.ts'
export { ProviderRegistry } from './core/providers.ts'
export type { ProviderDefinition, ProviderSettings } from './core/providers.ts'
export { createAdapter, createAdapterFromSettings, expandEnv, loadProviders, registerProvider } from './core/config.ts'
export { DeepSeekAdapter, DEFAULT_MODEL } from './llm/deepseek.ts'
export type { DeepSeekOptions } from './llm/deepseek.ts'
export { OpenAiAdapter } from './llm/openai.ts'
export type { OpenAiOptions } from './llm/openai.ts'
export { createBuiltinTools } from './tools/builtin.ts'
export type {
  ContentBlock,
  FinishReason,
  GenerateOptions,
  Message,
  StreamChunk,
  TextBlock,
  TokenUsage,
  ToolCallBlock,
  ToolResultBlock,
  ToolSchema,
} from './core/types.ts'
