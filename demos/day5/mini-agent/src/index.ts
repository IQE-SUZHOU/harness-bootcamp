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
export { createStopConditions } from './core/stop-conditions.ts'
export type { StopConditions, StopConditionsConfig, StopReason, StopReasonKind } from './core/stop-conditions.ts'
export { codePointLength, PRUNE_DEFAULTS, PRUNE_MARKER, pruneToolResult, resolvePruneConfig } from './core/prune.ts'
export type { PruneConfig, PruneResult, ResolvedPruneConfig } from './core/prune.ts'
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
export { SessionStore, buildRepairClosers, findInterrupted, SESSION_FORMAT_VERSION, UNKNOWN_OUTCOME_TEXT } from './core/persistence.ts'
export type { RepairReport, SessionHeader, StoreOptions } from './core/persistence.ts'
export { SessionRepository } from './core/repository.ts'
export type { ResumeResult } from './core/repository.ts'
export { renderVerifyTable, sha256File, verifyWorkspace } from './core/verify.ts'
export type { Check, CommandCheck, FileCheck, ProtectedFile, VerifyResult, VerifySpec } from './core/verify.ts'
export { ApprovalGate, APPROVAL_TOKEN_PREFIX, generateApprovalToken, isApprovalToken } from './core/approval.ts'
export type { ApprovalDecision, ApprovalRequest, Approver } from './core/approval.ts'
export { checkPlainJson, resolveConcurrency, runWorkflow } from './core/workflow.ts'
export type { BranchResult, BranchRunner, RunRecord, WorkflowBranch, WorkflowFatal, WorkflowLimits, WorkflowOutcome } from './core/workflow.ts'
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
