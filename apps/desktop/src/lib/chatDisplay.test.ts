/**
 * 思考过程分组：推理与工具步骤分离。
 */
import { describe, expect, it } from 'vitest'
import { formatHistoryMessages, groupChatMessages } from './chatDisplay'
import type { ChatMessage } from '../stores/app'

describe('groupChatMessages reasoning', () => {
  it('keeps reasoning-only assistant in thinkingStreaming', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: '', reasoning: '先想一步' },
    ]
    const blocks = groupChatMessages(messages, true)
    expect(blocks).toHaveLength(2)
    const turn = blocks[1]
    expect(turn.type).toBe('turn')
    if (turn.type !== 'turn') return
    expect(turn.turn.thinkingStreaming).toBe(true)
    expect(turn.turn.answerStreaming).toBe(false)
    expect(turn.turn.answer).toBeUndefined()
    expect(turn.turn.items.some((i) => i.type === 'reasoning')).toBe(true)
  })

  it('does not render reasoning as answer body while streaming', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: '写攻略' },
      { role: 'assistant', content: '', reasoning: '先规划行程结构……' },
    ]
    const blocks = groupChatMessages(messages, true)
    const turn = blocks[1]
    expect(turn.type).toBe('turn')
    if (turn.type !== 'turn') return
    expect(turn.turn.answer?.content).toBeFalsy()
    expect(turn.turn.items).toEqual([{ type: 'reasoning', content: '先规划行程结构……' }])
  })

  it('shows answer body only after content tokens arrive', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: '你好', reasoning: '礼貌回复' },
    ]
    const blocks = groupChatMessages(messages, true)
    const turn = blocks[1]
    expect(turn.type).toBe('turn')
    if (turn.type !== 'turn') return
    expect(turn.turn.thinkingStreaming).toBe(false)
    expect(turn.turn.answerStreaming).toBe(true)
    expect(turn.turn.answer?.content).toBe('你好')
    expect(turn.turn.items.some((i) => i.type === 'reasoning')).toBe(true)
  })

  it('shows pending thinking when only user message while streaming', () => {
    const messages: ChatMessage[] = [{ role: 'user', content: 'hi' }]
    const blocks = groupChatMessages(messages, true)
    expect(blocks).toHaveLength(2)
    const turn = blocks[1]
    expect(turn.type).toBe('turn')
    if (turn.type !== 'turn') return
    expect(turn.turn.thinkingStreaming).toBe(true)
  })

  it('hides leaked thinking stub from answer body while streaming', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: '写攻略' },
      { role: 'assistant', content: '我先', reasoning: '我先规划行程结构，再决定要不要搜索。' },
    ]
    const blocks = groupChatMessages(messages, true)
    const turn = blocks[1]
    expect(turn.type).toBe('turn')
    if (turn.type !== 'turn') return
    expect(turn.turn.thinkingStreaming).toBe(true)
    expect(turn.turn.answerStreaming).toBe(false)
    expect(turn.turn.answer).toBeUndefined()
    expect(turn.turn.items.some((i) => i.type === 'reasoning')).toBe(true)
  })

  it('peels think tags out of assistant content into thinking panel', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: '<think>先想一步</think>\n\n你好' },
    ]
    const blocks = groupChatMessages(messages, true)
    const turn = blocks[1]
    expect(turn.type).toBe('turn')
    if (turn.type !== 'turn') return
    expect(turn.turn.answer?.content.trim()).toBe('你好')
    expect(turn.turn.items.some((i) => i.type === 'reasoning' && i.content.includes('先想一步'))).toBe(true)
  })

  it('formatHistoryMessages maps reasoning_content', () => {
    const out = formatHistoryMessages([
      {
        id: '1',
        role: 'assistant',
        content: '答案',
        reasoning_content: '推理过程',
      },
    ])
    expect(out[0].reasoning).toBe('推理过程')
    expect(out[0].content).toBe('答案')
  })

  it('hides short stub body when long reasoning exists', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: '写攻略' },
      {
        role: 'assistant',
        content: '基本齐全马上',
        reasoning: '用户没给出具体人数和日期。我按记忆默认两人，先搜索门票价格，再编写 HTML 攻略。'.repeat(3),
      },
    ]
    const blocks = groupChatMessages(messages, false)
    const turn = blocks[1]
    expect(turn.type).toBe('turn')
    if (turn.type !== 'turn') return
    expect(turn.turn.answer).toBeUndefined()
    expect(turn.turn.items.some((i) => i.type === 'reasoning')).toBe(true)
  })

  it('hides garbled stub from real travel session', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: '写攻略' },
      {
        role: 'assistant',
        content: '给出写的把下的 `` 文件夹试试不被我再下面先生',
        reasoning: '用户没给出具体人数。我按记忆默认，做一轮搜索确认票价，然后编写 HTML。'.repeat(5),
      },
    ]
    const blocks = groupChatMessages(messages, false)
    const turn = blocks[1]
    expect(turn.type).toBe('turn')
    if (turn.type !== 'turn') return
    expect(turn.turn.answer).toBeUndefined()
  })
})
