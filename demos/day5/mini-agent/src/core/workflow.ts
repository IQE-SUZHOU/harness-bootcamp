/**
 * Fan-out / fan-in over subagents, with explicit failure propagation.
 *
 * A workflow runs several branches concurrently and then summarizes the
 * survivors. The failure semantics are the point:
 *
 * | Failure class | Effect |
 * | --- | --- |
 * | Ordinary branch error | that branch becomes `null`; the others complete |
 * | Fatal error (bad spec, cap reached, timeout) | the whole run fails |
 *
 * A fan-in therefore filters out the `null`s. Counting `parts.length` would
 * count failures as successes.
 *
 * @module mini-agent/core/workflow
 */

import os from 'node:os'

/** One branch of a fan-out. */
export interface WorkflowBranch {
  /** The label recorded for this branch. */
  label: string
  /** The task the branch runs. */
  task: string
}

/** One branch's outcome. */
export interface BranchResult {
  /** The label of the branch. */
  label: string
  /** The branch's answer, or null when the branch failed. */
  value: string | null
  /** The failure message when the branch failed. */
  error?: string
  /** The milliseconds the branch took. */
  durationMs: number
}

/** The routing record of one run. */
export interface RunRecord {
  /** The branch label. */
  label: string
  /** When the branch started, as epoch milliseconds. */
  startedAt: number
  /** When the branch ended, as epoch milliseconds. */
  endedAt: number
  /** The branch outcome. */
  outcome: 'ok' | 'failed'
}

/** The limits that bound one workflow run. */
export interface WorkflowLimits {
  /** Maximum branches running at once. `0` means auto. */
  maxConcurrent?: number
  /** Maximum branches one run may start. */
  maxTotal?: number
  /** The timeout of one branch, in milliseconds. */
  branchTimeoutMs?: number
  /** The timeout of the whole run, in milliseconds. */
  runTimeoutMs?: number
}

/** Why a whole run failed. */
export type WorkflowFatal =
  | { kind: 'agent-cap'; message: string }
  | { kind: 'timeout'; message: string }
  | { kind: 'bad-spec'; message: string }

/** The outcome of one workflow run. */
export type WorkflowOutcome =
  | {
    kind: 'completed'
    /** The branch results, in input order; a failed branch is `null`. */
    parts: (string | null)[]
    /** The fan-in summary, when the run declared one. */
    summary: string | undefined
    /** The routing record of every branch. */
    routing: RunRecord[]
    /** The peak number of branches running at once. */
    maxActive: number
  }
  | { kind: 'failed'; fatal: WorkflowFatal }

/** One branch's execution, supplied by the caller. */
export type BranchRunner = (branch: WorkflowBranch) => Promise<string>

/**
 * Run a set of branches concurrently and summarize the survivors.
 *
 * The branches run under a concurrency cap. An ordinary branch failure yields
 * `null` for that branch; a fatal condition fails the whole run and is
 * reported as such, never as a partial success.
 * @param branches - the branches to run.
 * @param run - the function that executes one branch.
 * @param options - the fan-in task and the limits.
 * @returns the run outcome.
 */
export async function runWorkflow(
  branches: readonly WorkflowBranch[],
  run: BranchRunner,
  options: {
    /** The fan-in task; omitted means no fan-in. */
    fanIn?: string
    /** The function that produces the fan-in summary. */
    summarize?: (task: string, survivors: string[]) => Promise<string>
    /** The limits that bound the run. */
    limits?: WorkflowLimits
  } = {},
): Promise<WorkflowOutcome> {
  const limits = options.limits ?? {}
  const maxTotal = limits.maxTotal ?? 1000
  if (branches.length > maxTotal) {
    return {
      kind: 'failed',
      fatal: { kind: 'agent-cap', message: `total agent cap (${maxTotal})` },
    }
  }
  if (branches.length === 0) {
    return { kind: 'completed', parts: [], summary: undefined, routing: [], maxActive: 0 }
  }

  const maxConcurrent = resolveConcurrency(limits.maxConcurrent)
  const results: (BranchResult | undefined)[] = new Array(branches.length)
  const routing: RunRecord[] = []
  let active = 0
  let maxActive = 0

  /** The index of the next branch to start. */
  let next = 0
  /** The workers pull branches from the queue. */
  const worker = async (): Promise<void> => {
    for (;;) {
      const index = next++
      if (index >= branches.length) return
      const branch = branches[index]
      if (branch === undefined) return
      active += 1
      maxActive = Math.max(maxActive, active)
      const startedAt = Date.now()
      try {
        const value = await withTimeout(
          run(branch),
          limits.branchTimeoutMs,
          `${branch.label} timed out after ${limits.branchTimeoutMs}ms`,
        )
        results[index] = { label: branch.label, value, durationMs: Date.now() - startedAt }
        routing.push({ label: branch.label, startedAt, endedAt: Date.now(), outcome: 'ok' })
      } catch (error: unknown) {
        // An ordinary branch failure nulls its slot; the run continues.
        const message = error instanceof Error ? error.message : String(error)
        results[index] = { label: branch.label, value: null, error: message, durationMs: Date.now() - startedAt }
        routing.push({ label: branch.label, startedAt, endedAt: Date.now(), outcome: 'failed' })
      } finally {
        active -= 1
      }
    }
  }

  try {
    await withTimeout(
      Promise.all(Array.from({ length: Math.min(maxConcurrent, branches.length) }, () => worker())),
      limits.runTimeoutMs,
      `the run timed out after ${limits.runTimeoutMs}ms`,
    )
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error)
    return { kind: 'failed', fatal: { kind: 'timeout', message } }
  }

  const parts = results.map(result => result?.value ?? null)
  const survivors = parts.filter((part): part is string => part !== null)

  let summary: string | undefined
  if (options.fanIn !== undefined && options.summarize !== undefined) {
    try {
      summary = await withTimeout(
        options.summarize(options.fanIn, survivors),
        limits.branchTimeoutMs,
        `the fan-in timed out after ${limits.branchTimeoutMs}ms`,
      )
    } catch (error: unknown) {
      // A failed fan-in is an ordinary failure of the run's own branch.
      summary = undefined
    }
  }
  return { kind: 'completed', parts, summary, routing, maxActive }
}

/**
 * Resolve the concurrency of one run.
 *
 * `0` and an omitted value mean auto, which the engine computes as
 * `min(16, max(1, parallelism - 2))`. It does not mean "no concurrency".
 * @param configured - the configured cap.
 * @returns the number of branches to run at once.
 */
export function resolveConcurrency(configured: number | undefined): number {
  if (configured !== undefined && configured > 0) return configured
  const parallelism = availableParallelism()
  return Math.min(16, Math.max(1, parallelism - 2))
}

/**
 * The number of available CPUs, defaulting to four.
 * @returns the parallelism.
 */
function availableParallelism(): number {
  return os.availableParallelism?.() ?? 4
}

/**
 * Reject a value that is not plain JSON.
 *
 * A workflow result must survive serialization, so sparse arrays, functions,
 * and non-finite numbers are refused.
 * @param value - the value to check.
 * @returns undefined when the value is plain JSON, or the reason it is not.
 */
export function checkPlainJson(value: unknown): string | undefined {
  if (value === null) return undefined
  if (typeof value === 'number') {
    return Number.isFinite(value) ? undefined : 'a non-finite number'
  }
  if (typeof value === 'string' || typeof value === 'boolean') return undefined
  if (typeof value === 'function' || typeof value === 'symbol' || typeof value === 'undefined') {
    return `a ${typeof value} value`
  }
  if (Array.isArray(value)) {
    if (value.some(item => item === undefined)) return 'a sparse array'
    for (const item of value) {
      const reason = checkPlainJson(item)
      if (reason !== undefined) return reason
    }
    return undefined
  }
  if (typeof value === 'object') {
    const prototype = Object.getPrototypeOf(value)
    if (prototype !== Object.prototype && prototype !== null) return 'a class instance'
    for (const [key, item] of Object.entries(value)) {
      if (item === undefined) return `the property "${key}"`
      const reason = checkPlainJson(item)
      if (reason !== undefined) return reason
    }
    return undefined
  }
  return `a ${typeof value} value`
}

/**
 * Race an operation against a timeout.
 * @param operation - the operation to run.
 * @param timeoutMs - the timeout; an omitted or non-positive value disables it.
 * @param message - the failure message used on timeout.
 * @returns the operation's value.
 */
async function withTimeout<T>(operation: Promise<T>, timeoutMs: number | undefined, message: string): Promise<T> {
  if (timeoutMs === undefined || timeoutMs <= 0) return await operation
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      operation,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => { reject(new Error(message)) }, timeoutMs)
      }),
    ])
  } finally {
    if (timer !== undefined) clearTimeout(timer)
  }
}
