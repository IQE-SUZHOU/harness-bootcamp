/**
 * Deterministic tool-result pruning.
 *
 * Tool output is the fastest-growing part of a context: one `ls -la` in a
 * large directory can add tens of thousands of characters, and the agent
 * re-sends the whole history on every request. Pruning keeps a tool result
 * within a character budget by dropping its **middle** and keeping its head
 * and tail, so the model still sees how the output began and ended.
 *
 * The pass is **model-free**: it costs no tokens and no extra request, and it
 * is deterministic, so the same log always prunes to the same request.
 *
 * The durable log is never rewritten. Pruning happens in the projection from
 * the log into the request, so the full-fidelity result stays replayable.
 *
 * @module mini-agent/core/prune
 */

/** The marker substituted for a removed middle span. */
export const PRUNE_MARKER = '\n\n[... tool result middle pruned ...]\n\n'

/** The character-budget policy for pruning. */
export interface PruneConfig {
  /** Prune when a tool result exceeds this many Unicode code points. */
  thresholdChars?: number
  /** Maximum leading Unicode code points retained. */
  headChars?: number
  /** Maximum trailing Unicode code points retained. */
  tailChars?: number
}

/** The validated pruning budgets. */
export interface ResolvedPruneConfig {
  /** Prune when a tool result exceeds this many Unicode code points. */
  readonly thresholdChars: number
  /** Maximum leading Unicode code points retained. */
  readonly headChars: number
  /** Maximum trailing Unicode code points retained. */
  readonly tailChars: number
}

/** The default budgets, sized for coding-agent tool output. */
export const PRUNE_DEFAULTS: ResolvedPruneConfig = Object.freeze({
  thresholdChars: 8192,
  headChars: 4096,
  tailChars: 1024,
})

/**
 * Count Unicode code points without splitting a surrogate pair.
 * @param text - the text to measure.
 * @returns the Unicode code-point count.
 */
export function codePointLength(text: string): number {
  return Array.from(text).length
}

/**
 * Validate one budget value.
 * @param name - the budget name.
 * @param value - the configured value.
 * @param allowZero - whether zero is allowed.
 */
function assertBudget(name: string, value: number, allowZero: boolean): void {
  const ok = allowZero ? value >= 0 : value > 0
  if (!Number.isInteger(value) || !ok) {
    throw new Error(`prune config: ${name} (${value}) must be ${allowZero ? 'a non-negative' : 'a positive'} integer`)
  }
}

/**
 * Resolve and validate the pruning budgets.
 *
 * The emitted size is `headChars + marker + tailChars`, so that sum must fit
 * inside the threshold; otherwise a pruned result could still exceed it.
 * @param config - the raw configuration.
 * @returns the resolved budgets.
 */
export function resolvePruneConfig(config: PruneConfig = {}): ResolvedPruneConfig {
  const resolved: ResolvedPruneConfig = {
    thresholdChars: config.thresholdChars ?? PRUNE_DEFAULTS.thresholdChars,
    headChars: config.headChars ?? PRUNE_DEFAULTS.headChars,
    tailChars: config.tailChars ?? PRUNE_DEFAULTS.tailChars,
  }
  assertBudget('thresholdChars', resolved.thresholdChars, false)
  assertBudget('headChars', resolved.headChars, true)
  assertBudget('tailChars', resolved.tailChars, true)
  const emitted = resolved.headChars + codePointLength(PRUNE_MARKER) + resolved.tailChars
  if (emitted > resolved.thresholdChars) {
    throw new Error(
      `prune config: headChars + marker + tailChars (${emitted}) must be at most thresholdChars (${resolved.thresholdChars})`,
    )
  }
  return Object.freeze(resolved)
}

/** The outcome of one pruning pass. */
export interface PruneResult {
  /** The pruned text, or the original text when it was within budget. */
  readonly text: string
  /** Whether the text was changed. */
  readonly pruned: boolean
  /** The size of the original text in Unicode code points. */
  readonly charsBefore: number
  /** The size of the resulting text in Unicode code points. */
  readonly charsAfter: number
}

/**
 * Prune one tool result to the configured budget.
 *
 * The text is sliced by Unicode code point, so a retained boundary never
 * splits a surrogate pair. The removed middle is replaced by one marker.
 * @param text - the tool result text.
 * @param config - the resolved budgets.
 * @returns the pruned text and its size accounting.
 */
export function pruneToolResult(text: string, config: ResolvedPruneConfig): PruneResult {
  const points = Array.from(text)
  const charsBefore = points.length
  if (charsBefore <= config.thresholdChars) {
    return { text, pruned: false, charsBefore, charsAfter: charsBefore }
  }
  // Keep the head and the tail; replace the middle with one marker.
  const head = points.slice(0, config.headChars).join('')
  const tail = points.slice(Math.max(0, charsBefore - config.tailChars)).join('')
  const pruned = head + PRUNE_MARKER + tail
  return {
    text: pruned,
    pruned: true,
    charsBefore,
    charsAfter: codePointLength(pruned),
  }
}
