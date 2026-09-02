import { describe, expect, it } from 'vitest'
import { applyStreamEvent, initialChatStreamState } from './chatStore'

describe('applyStreamEvent', () => {
  it('accumulates tokens after run_started', () => {
    let s = initialChatStreamState()
    s = applyStreamEvent(s, 'run_started', { run_id: 'r1' })
    s = applyStreamEvent(s, 'token', { delta: '你' })
    s = applyStreamEvent(s, 'token', { delta: '好' })
    expect(s.runId).toBe('r1')
    expect(s.assistantText).toBe('你好')
    expect(s.streaming).toBe(true)
  })

  it('moves tool to awaiting_confirm', () => {
    let s = applyStreamEvent(initialChatStreamState(), 'run_started', { run_id: 'r1' })
    s = applyStreamEvent(s, 'tool_start', { tool_call_id: 't1', name: 'fs_write', arguments: {} })
    s = applyStreamEvent(s, 'tool_confirm', { tool_call_id: 't1', name: 'fs_write', risk: 'high' })
    expect(s.tools[0].status).toBe('awaiting_confirm')
    expect(s.streaming).toBe(false)
  })

  it('marks rejected on cancelled tool_result', () => {
    let s = applyStreamEvent(initialChatStreamState(), 'run_started', { run_id: 'r1' })
    s = applyStreamEvent(s, 'tool_start', { tool_call_id: 't1', name: 'fs_write' })
    s = applyStreamEvent(s, 'tool_result', {
      tool_call_id: 't1',
      result: { cancelled: true },
      is_error: false,
    })
    expect(s.tools[0].status).toBe('rejected')
  })

  it('handles done rejected', () => {
    let s = applyStreamEvent(initialChatStreamState(), 'run_started', { run_id: 'r1' })
    s = applyStreamEvent(s, 'done', { rejected: true })
    expect(s.done).toBe(true)
    expect(s.rejected).toBe(true)
    expect(s.streaming).toBe(false)
  })

  it('handles error', () => {
    let s = applyStreamEvent(initialChatStreamState(), 'run_started', { run_id: 'r1' })
    s = applyStreamEvent(s, 'error', { message: 'llm_error' })
    expect(s.error).toBe('llm_error')
    expect(s.done).toBe(true)
  })
})
