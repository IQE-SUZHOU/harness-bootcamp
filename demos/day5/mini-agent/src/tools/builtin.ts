/**
 * Built-in tools: `bash`, `read_file`, `write_file`, and `edit_file`.
 *
 * Every tool is sandboxed to the agent's workspace root: a path that escapes
 * the root is refused rather than followed.
 *
 * @module mini-agent/tools/builtin
 */

import { exec } from 'node:child_process'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { dirname, resolve, sep } from 'node:path'
import type { ToolDefinition } from '../core/tools.ts'

/** Longest tool output forwarded to the model, in characters. */
const MAX_OUTPUT_CHARS = 30_000

/** Longest single shell command duration, in milliseconds. */
const DEFAULT_TIMEOUT_MS = 120_000

/**
 * Resolve one path inside the workspace root.
 * @param root - the workspace root.
 * @param target - the requested path.
 * @returns the absolute path, or undefined when it escapes the root.
 */
function resolveInside(root: string, target: string): string | undefined {
  const base = resolve(root)
  const absolute = resolve(base, target)
  if (absolute === base) return absolute
  if (absolute.startsWith(base + sep)) return absolute
  return undefined
}

/**
 * Truncate one tool output to the model-facing limit.
 * @param text - the raw output.
 * @returns the truncated output with a marker when it was cut.
 */
function clamp(text: string): string {
  if (text.length <= MAX_OUTPUT_CHARS) return text
  return `${text.slice(0, MAX_OUTPUT_CHARS)}\n... [output truncated at ${MAX_OUTPUT_CHARS} characters]`
}

/**
 * Build the `bash` tool.
 * @param root - the workspace root commands run in.
 * @returns the tool definition.
 */
export function createBashTool(root: string): ToolDefinition {
  return {
    name: 'bash',
    description: 'Run a shell command in the workspace and return its combined stdout and stderr.',
    parameters: {
      type: 'object',
      properties: {
        command: { type: 'string', description: 'The shell command to run.' },
        timeout_ms: { type: 'number', description: 'Optional timeout in milliseconds (default 120000).' },
      },
      required: ['command'],
      additionalProperties: false,
    },
    async execute(args, signal): Promise<string> {
      const command = String(args.command)
      const timeout = typeof args.timeout_ms === 'number' ? args.timeout_ms : DEFAULT_TIMEOUT_MS
      return await new Promise<string>((resolvePromise, rejectPromise) => {
        const child = exec(command, {
          cwd: root,
          maxBuffer: 10 * 1024 * 1024,
          timeout,
          signal,
          encoding: 'utf8',
        }, (error, stdout, stderr) => {
          if (signal.aborted) {
            rejectPromise(new Error('command cancelled'))
            return
          }
          const output = `${stdout}${stderr}`.trim()
          if (error === null) {
            resolvePromise(output.length > 0 ? output : '(no output)')
            return
          }
          // A non-zero exit is a tool failure the model must see.
          rejectPromise(new Error(output.length > 0 ? clamp(output) : error.message))
        })
        child.on('error', rejectPromise)
      })
    },
  }
}

/**
 * Build the `read_file` tool.
 * @param root - the workspace root paths resolve in.
 * @returns the tool definition.
 */
export function createReadFileTool(root: string): ToolDefinition {
  return {
    name: 'read_file',
    description: 'Read a UTF-8 text file from the workspace and return its contents.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'The file path, relative to the workspace root.' },
        offset: { type: 'number', description: 'Optional 1-based line to start reading from.' },
        limit: { type: 'number', description: 'Optional maximum number of lines to read.' },
      },
      required: ['path'],
      additionalProperties: false,
    },
    async execute(args): Promise<string> {
      const target = String(args.path)
      const absolute = resolveInside(root, target)
      if (absolute === undefined) {
        throw new Error(`path "${target}" escapes the workspace root`)
      }
      const content = await readFile(absolute, 'utf8')
      const lines = content.split('\n')
      const offset = typeof args.offset === 'number' ? Math.max(1, Math.floor(args.offset)) : 1
      const limit = typeof args.limit === 'number' ? Math.max(1, Math.floor(args.limit)) : lines.length
      const selected = lines.slice(offset - 1, offset - 1 + limit)
      const body = selected.join('\n')
      if (body.length === 0) return `(file "${target}" has no content at that range)`
      return clamp(body)
    },
  }
}

/**
 * Build the `write_file` tool.
 * @param root - the workspace root paths resolve in.
 * @returns the tool definition.
 */
export function createWriteFileTool(root: string): ToolDefinition {
  return {
    name: 'write_file',
    description: 'Write UTF-8 text to a file in the workspace, creating parent directories as needed.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'The file path, relative to the workspace root.' },
        content: { type: 'string', description: 'The complete file content to write.' },
      },
      required: ['path', 'content'],
      additionalProperties: false,
    },
    async execute(args): Promise<string> {
      const target = String(args.path)
      const absolute = resolveInside(root, target)
      if (absolute === undefined) {
        throw new Error(`path "${target}" escapes the workspace root`)
      }
      const content = String(args.content)
      await mkdir(dirname(absolute), { recursive: true })
      await writeFile(absolute, content, 'utf8')
      return `wrote ${content.length} characters to "${target}"`
    },
  }
}

/**
 * Build the `edit_file` tool.
 * @param root - the workspace root paths resolve in.
 * @returns the tool definition.
 */
export function createEditFileTool(root: string): ToolDefinition {
  return {
    name: 'edit_file',
    description: 'Replace an exact string in a workspace file. The old string must appear exactly once.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'The file path, relative to the workspace root.' },
        old_string: { type: 'string', description: 'The exact text to replace.' },
        new_string: { type: 'string', description: 'The replacement text.' },
      },
      required: ['path', 'old_string', 'new_string'],
      additionalProperties: false,
    },
    async execute(args): Promise<string> {
      const target = String(args.path)
      const absolute = resolveInside(root, target)
      if (absolute === undefined) {
        throw new Error(`path "${target}" escapes the workspace root`)
      }
      const oldString = String(args.old_string)
      const newString = String(args.new_string)
      const content = await readFile(absolute, 'utf8')
      const first = content.indexOf(oldString)
      if (first === -1) {
        throw new Error(`the text to replace was not found in "${target}"`)
      }
      if (content.indexOf(oldString, first + 1) !== -1) {
        throw new Error(`the text to replace appears more than once in "${target}"; include more context`)
      }
      await writeFile(absolute, content.slice(0, first) + newString + content.slice(first + oldString.length), 'utf8')
      return `edited "${target}"`
    },
  }
}

/** Every built-in tool, built for one workspace root. */
export function createBuiltinTools(root: string): ToolDefinition[] {
  return [
    createBashTool(root),
    createReadFileTool(root),
    createWriteFileTool(root),
    createEditFileTool(root),
  ]
}
