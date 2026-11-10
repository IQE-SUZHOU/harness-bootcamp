/**
 * A local mock of the OpenAI-compatible Chat Completions API, for exercising
 * the agent against the OpenAI wire format without an API key.
 *
 * Usage: node --experimental-strip-types tests/mock-openai-server.ts
 */

import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'

let requestCount = 0
const server = createServer((req, res) => {
  const chunks: Buffer[] = []
  req.on('data', chunk => { chunks.push(chunk as Buffer) })
  req.on('end', () => {
    const raw = Buffer.concat(chunks).toString('utf8')
    const body = JSON.parse(raw) as { messages: unknown[]; model: string }
    requestCount += 1
    console.error(`[mock-openai] request ${requestCount}: model=${body.model} messages=${body.messages.length}`)

    res.writeHead(200, { 'content-type': 'text/event-stream' })
    const send = (payload: unknown): void => {
      res.write(`data: ${JSON.stringify(payload)}\n\n`)
    }
    if (requestCount === 1) {
      // Ask for a tool call.
      send({
        id: 'chatcmpl-1',
        object: 'chat.completion.chunk',
        model: body.model,
        choices: [{
          index: 0,
          delta: {
            role: 'assistant',
            tool_calls: [{
              index: 0,
              id: 'call_abc123',
              type: 'function',
              function: { name: 'bash', arguments: '{"command":"echo openai-wire"}' },
            }],
          },
          finish_reason: null,
        }],
      })
      send({
        id: 'chatcmpl-1',
        object: 'chat.completion.chunk',
        model: body.model,
        choices: [{ index: 0, delta: {}, finish_reason: 'tool_calls' }],
        usage: { prompt_tokens: 30, completion_tokens: 12, total_tokens: 42 },
      })
    } else {
      send({
        id: 'chatcmpl-2',
        object: 'chat.completion.chunk',
        model: body.model,
        choices: [{ index: 0, delta: { role: 'assistant', content: 'The tool printed: ' }, finish_reason: null }],
      })
      send({
        id: 'chatcmpl-2',
        object: 'chat.completion.chunk',
        model: body.model,
        choices: [{ index: 0, delta: { content: 'openai-wire' }, finish_reason: null }],
      })
      send({
        id: 'chatcmpl-2',
        object: 'chat.completion.chunk',
        model: body.model,
        choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
        usage: { prompt_tokens: 55, completion_tokens: 9, total_tokens: 64 },
      })
    }
    res.write('data: [DONE]\n\n')
    res.end()
  })
})

server.listen(0, '127.0.0.1', () => {
  const address = server.address() as AddressInfo
  console.log(`http://127.0.0.1:${address.port}`)
})
