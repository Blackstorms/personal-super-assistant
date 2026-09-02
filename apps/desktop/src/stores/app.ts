import { create } from 'zustand'

export type ChatMessage = {
  id?: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  /** 模型原生推理 / 深度思考文本（与正文分离） */
  reasoning?: string
  toolCalls?: unknown[]
  pendingConfirm?: { run_id: string; tool_call_id: string; name: string; arguments: unknown }
}

type AppState = {
  backendHealthy: boolean
  workspaceId: string | null
  /** 已选本地文件夹、尚未创建工作空间（首条消息时落库） */
  pendingFolderPath: string | null
  sessionId: string | null
  messageCache: Record<string, ChatMessage[]>
  messages: ChatMessage[]
  /** 各会话进行中的 run_id，支持多会话并行 */
  activeRuns: Record<string, string>
  /** 侧栏会话列表刷新计数 */
  sessionListTick: number
  /** 侧栏空间列表刷新计数 */
  workspaceListTick: number
  /** 新建会话后 ChatPage 应继承工作空间 composer 默认 */
  pendingApplyWorkspaceDefaults: boolean
  /** 侧栏「任务 / 空间」视图 */
  sidebarViewMode: 'group' | 'space'
  setBackendHealthy: (v: boolean) => void
  bumpSessionList: () => void
  bumpWorkspaceList: () => void
  removeSession: (sessionId: string) => void
  setWorkspaceId: (id: string | null) => void
  setPendingFolderPath: (path: string | null) => void
  clearWorkspaceSelection: () => void
  setSessionId: (id: string | null) => void
  /** forSessionId：写入指定会话缓存；仅当仍是当前会话时更新右侧消息列表 */
  setMessages: (msgs: ChatMessage[], forSessionId?: string) => void
  appendMessage: (msg: ChatMessage, forSessionId?: string) => void
  patchLastAssistant: (delta: string, forSessionId?: string) => void
  /** 追加模型推理文本（reasoning_content）到最近一条助手消息 */
  patchLastReasoning: (delta: string, forSessionId?: string) => void
  setSessionRun: (sessionId: string, runId: string | null) => void
  setSidebarViewMode: (mode: 'group' | 'space') => void
  requestApplyWorkspaceDefaults: () => void
  consumeApplyWorkspaceDefaults: () => boolean
}

export const useAppStore = create<AppState>((set, get) => ({
  backendHealthy: false,
  workspaceId: null,
  pendingFolderPath: null,
  sessionId: null,
  messageCache: {},
  messages: [],
  activeRuns: {},
  sessionListTick: 0,
  workspaceListTick: 0,
  pendingApplyWorkspaceDefaults: false,
  sidebarViewMode: 'group',
  setBackendHealthy: (v) => set({ backendHealthy: v }),
  bumpSessionList: () => set((s) => ({ sessionListTick: s.sessionListTick + 1 })),
  bumpWorkspaceList: () => set((s) => ({ workspaceListTick: s.workspaceListTick + 1 })),
  setSidebarViewMode: (mode) => set({ sidebarViewMode: mode }),
  removeSession: (sessionId) =>
    set((s) => {
      const messageCache = { ...s.messageCache }
      delete messageCache[sessionId]
      const activeRuns = { ...s.activeRuns }
      delete activeRuns[sessionId]
      const isCurrent = s.sessionId === sessionId
      return {
        messageCache,
        activeRuns,
        sessionId: isCurrent ? null : s.sessionId,
        messages: isCurrent ? [] : s.messages,
        sessionListTick: s.sessionListTick + 1,
      }
    }),
  setWorkspaceId: (id) =>
    set({
      workspaceId: id,
      ...(id != null ? { pendingFolderPath: null } : {}),
    }),
  setPendingFolderPath: (path) =>
    set({
      pendingFolderPath: path,
      ...(path ? { workspaceId: null } : {}),
    }),
  clearWorkspaceSelection: () => set({ workspaceId: null, pendingFolderPath: null }),
  setSessionId: (id) =>
    set((s) => {
      if (s.sessionId === id) return s
      return {
        sessionId: id,
        messages: id ? (s.messageCache[id] ?? []) : [],
      }
    }),
  setMessages: (msgs, forSessionId) =>
    set((s) => {
      const target = forSessionId ?? s.sessionId
      if (!target) {
        // 无会话（新建空态）：只更新展示列表
        return { messages: msgs }
      }
      // 流式进行中禁止用外部快照覆盖该会话缓存
      if (s.activeRuns[target]) {
        const keep = s.messageCache[target] ?? s.messages
        return {
          messageCache: { ...s.messageCache, [target]: keep },
          messages: s.sessionId === target ? keep : s.messages,
        }
      }
      return {
        messageCache: { ...s.messageCache, [target]: msgs },
        messages: s.sessionId === target ? msgs : s.messages,
      }
    }),
  appendMessage: (msg, forSessionId) =>
    set((s) => {
      const target = forSessionId ?? s.sessionId
      if (!target) return s
      const next = [...(s.messageCache[target] ?? []), msg]
      return {
        messageCache: { ...s.messageCache, [target]: next },
        messages: s.sessionId === target ? next : s.messages,
      }
    }),
  patchLastAssistant: (delta, forSessionId) =>
    set((s) => {
      const target = forSessionId ?? s.sessionId
      if (!target) return s
      const msgs = [...(s.messageCache[target] ?? [])]
      const idx = findPatchAssistantIndex(msgs)
      if (idx >= 0) {
        const last = msgs[idx]
        msgs[idx] = { ...last, content: last.content + delta }
      } else {
        msgs.push({ role: 'assistant', content: delta })
      }
      return {
        messageCache: { ...s.messageCache, [target]: msgs },
        messages: s.sessionId === target ? msgs : s.messages,
      }
    }),
  patchLastReasoning: (delta, forSessionId) =>
    set((s) => {
      const target = forSessionId ?? s.sessionId
      if (!target) return s
      const msgs = [...(s.messageCache[target] ?? [])]
      const idx = findPatchAssistantIndex(msgs)
      if (idx >= 0) {
        const last = msgs[idx]
        msgs[idx] = {
          ...last,
          reasoning: (last.reasoning || '') + delta,
        }
      } else {
        msgs.push({ role: 'assistant', content: '', reasoning: delta })
      }
      return {
        messageCache: { ...s.messageCache, [target]: msgs },
        messages: s.sessionId === target ? msgs : s.messages,
      }
    }),
  setSessionRun: (sessionId, runId) =>
    set((s) => {
      const activeRuns = { ...s.activeRuns }
      if (runId) activeRuns[sessionId] = runId
      else delete activeRuns[sessionId]
      return { activeRuns }
    }),
  requestApplyWorkspaceDefaults: () => set({ pendingApplyWorkspaceDefaults: true }),
  consumeApplyWorkspaceDefaults: (): boolean => {
    const pending = get().pendingApplyWorkspaceDefaults
    if (pending) set({ pendingApplyWorkspaceDefaults: false })
    return pending
  },
}))

/** 找到应承接流式增量的助手消息：已被 tool 打断的轮次不再写入 */
function findPatchAssistantIndex(msgs: ChatMessage[]): number {
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role !== 'assistant') continue
    // 该助手之后已有 tool → 本轮已结束，应新开助手气泡
    if (msgs.slice(i + 1).some((m) => m.role === 'tool')) return -1
    return i
  }
  return -1
}

/** 当前查看的会话是否正在流式输出 */
export function useCurrentSessionStreaming() {
  const sessionId = useAppStore((s) => s.sessionId)
  const activeRuns = useAppStore((s) => s.activeRuns)
  return sessionId ? Boolean(activeRuns[sessionId]) : false
}
