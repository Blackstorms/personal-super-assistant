/**
 * SSE 对话状态机：纯函数归并事件，便于单测。
 */

export type ToolCardStatus = 'running' | 'awaiting_confirm' | 'done' | 'error' | 'rejected'

export interface ToolCard {
  tool_call_id: string
  name: string
  arguments?: unknown
  result?: unknown
  status: ToolCardStatus
  is_error?: boolean
  risk?: string
}

export interface ChatStreamState {
  runId: string | null
  streaming: boolean
  assistantText: string
  tools: ToolCard[]
  error: string | null
  done: boolean
  rejected: boolean
}

export function initialChatStreamState(): ChatStreamState {
  return {
    runId: null,
    streaming: false,
    assistantText: '',
    tools: [],
    error: null,
    done: false,
    rejected: false,
  }
}

export function applyStreamEvent(
  state: ChatStreamState,
  event: string,
  data: Record<string, unknown>,
): ChatStreamState {
  const next = { ...state, tools: [...state.tools] }
  switch (event) {
    case 'run_started':
      return {
        ...initialChatStreamState(),
        runId: String(data.run_id || ''),
        streaming: true,
      }
    case 'token':
      return {
        ...next,
        streaming: true,
        assistantText: next.assistantText + String(data.delta || ''),
      }
    case 'tool_start': {
      const id = String(data.tool_call_id || '')
      const card: ToolCard = {
        tool_call_id: id,
        name: String(data.name || ''),
        arguments: data.arguments,
        status: 'running',
      }
      return { ...next, tools: [...next.tools.filter((t) => t.tool_call_id !== id), card] }
    }
    case 'tool_confirm': {
      const id = String(data.tool_call_id || '')
      const tools = next.tools.map((t) =>
        t.tool_call_id === id
          ? { ...t, status: 'awaiting_confirm' as const, risk: String(data.risk || 'high') }
          : t,
      )
      if (!tools.some((t) => t.tool_call_id === id)) {
        tools.push({
          tool_call_id: id,
          name: String(data.name || ''),
          arguments: data.arguments,
          status: 'awaiting_confirm',
          risk: String(data.risk || 'high'),
        })
      }
      return { ...next, tools, streaming: false }
    }
    case 'tool_result': {
      const id = String(data.tool_call_id || '')
      const rejected = Boolean((data.result as { cancelled?: boolean } | undefined)?.cancelled)
      const tools = next.tools.map((t) =>
        t.tool_call_id === id
          ? {
              ...t,
              result: data.result,
              is_error: Boolean(data.is_error),
              status: (rejected ? 'rejected' : data.is_error ? 'error' : 'done') as ToolCardStatus,
            }
          : t,
      )
      return { ...next, tools }
    }
    case 'done':
      return {
        ...next,
        streaming: false,
        done: true,
        rejected: Boolean(data.rejected),
      }
    case 'error':
      return {
        ...next,
        streaming: false,
        error: String(data.message || data.code || 'error'),
        done: true,
      }
    default:
      return next
  }
}
