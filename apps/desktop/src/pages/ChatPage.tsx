/**
 * 新建任务：SSE 流式对话；可选模型 / 专家 / 资料库。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { apiRequest, apiStream, StreamAbortedError } from '../lib/api'
import { useAppStore } from '../stores/app'
import SkillSlashMenu from '../components/SkillSlashMenu'
import ChatLog from '../components/ChatLog'
import WorkspacePicker from '../components/WorkspacePicker'
import { formatHistoryMessages } from '../lib/chatDisplay'
import { useSkillSlashMenu, type SkillOption } from '../lib/skillSlashMenu'
import {
  emptyComposerBindings,
  fetchSessionComposerDefaults,
  fetchWorkspaceComposerDefaults,
  type ComposerBindingDefaults,
} from '../lib/composerDefaults'
import { ensureFolderWorkspace } from '../lib/folderWorkspace'
import ContextUsageMeter from '../components/ContextUsageMeter'
import { parseContextUsage, type ContextUsage } from '../lib/contextUsage'
import BuddyMascot, { resolveBuddyMood } from '../components/BuddyMascot'
import ComposerAttachMenu, { ComposerChips, type AttachedFile } from '../components/ComposerAttachMenu'

type Session = { id: string; title: string; workspace_id?: string }
type Profile = { id: string; name: string; model: string; is_default: boolean }
type Expert = { id: string; name: string }
type Knowledge = { id: string; name?: string | null; path?: string }
type Mcp = { id: string; name: string }

const CAPS = ['文档处理', '记忆检索', '资料库', '技能调用', 'MCP 工具', '任务清单']

const SCHEDULE_DRAFT = `请帮我创建一个定时任务，并调用 schedule_task 工具完成：
- 任务名称：
- 触发时间：（例如：每天 9 点 / 每 30 分钟 / 1 小时后）
- 执行内容：

说明：触发时 Agent 会执行「执行内容」里的指令。`

/** 确认条只展示短预览，避免整份 HTML/大文件卡死界面 */
function formatConfirmArgs(name: string, args: unknown): string {
  if (!args || typeof args !== 'object') return String(args ?? '')
  const raw = args as Record<string, unknown>
  const lines: string[] = [`工具：${name}`]
  if (typeof raw.path === 'string') lines.push(`路径：${raw.path}`)
  if (typeof raw.content_chars === 'number') {
    lines.push(`内容：约 ${raw.content_chars} 字`)
  }
  if (typeof raw.content_preview === 'string') {
    lines.push(raw.content_preview)
  } else if (typeof raw.content === 'string') {
    const c = raw.content
    lines.push(c.length > 200 ? `${c.slice(0, 160)}…（共 ${c.length} 字）` : c)
  }
  const rest: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(raw)) {
    if (['path', 'content', 'content_chars', 'content_preview'].includes(k)) continue
    rest[k] = typeof v === 'string' && v.length > 200 ? `${v.slice(0, 120)}…` : v
  }
  if (Object.keys(rest).length) lines.push(JSON.stringify(rest, null, 2))
  return lines.join('\n')
}

export default function ChatPage() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const {
    sessionId,
    setSessionId,
    messages,
    setMessages,
    appendMessage,
    patchLastAssistant,
    patchLastReasoning,
    activeRuns,
    setSessionRun,
    bumpSessionList,
    bumpWorkspaceList,
    sessionListTick,
    workspaceId,
    setWorkspaceId,
    pendingFolderPath,
    setPendingFolderPath,
    consumeApplyWorkspaceDefaults,
  } = useAppStore()
  const currentStreaming = sessionId ? Boolean(activeRuns[sessionId]) : false
  const currentRunId = sessionId ? activeRuns[sessionId] : undefined
  /** 定时任务等 headless run：本机无 SSE，靠轮询刷新并保持「思考中」态 */
  const [remoteRunning, setRemoteRunning] = useState(false)
  const [remoteRunId, setRemoteRunId] = useState<string | null>(null)
  const viewStreaming = currentStreaming || remoteRunning
  const effectiveRunId = currentRunId || remoteRunId || undefined
  const [input, setInput] = useState('')
  const [scheduleCompose, setScheduleCompose] = useState(false)
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [experts, setExperts] = useState<Expert[]>([])
  const [knowledge, setKnowledge] = useState<Knowledge[]>([])
  const [mcps, setMcps] = useState<Mcp[]>([])
  const [skills, setSkills] = useState<SkillOption[]>([])
  const [modelProfileId, setModelProfileId] = useState('')
  const [expertId, setExpertId] = useState('')
  const [skillIds, setSkillIds] = useState<string[]>([])
  const [mcpIds, setMcpIds] = useState<string[]>([])
  const [knowledgeIds, setKnowledgeIds] = useState<string[]>([])
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([])
  const [enableMemory, setEnableMemory] = useState(true)
  const [enableSkills, setEnableSkills] = useState(true)
  const [enableMcp, setEnableMcp] = useState(true)
  const [inheritWorkspaceDefaults, setInheritWorkspaceDefaults] = useState(true)
  const [bindingsTouched, setBindingsTouched] = useState(false)
  const [confirm, setConfirm] = useState<{
    run_id: string
    tool_call_id: string
    name: string
    arguments: unknown
  } | null>(null)
  const [error, setError] = useState('')
  const [streamHint, setStreamHint] = useState('')
  const lastStreamEventAt = useRef(0)
  const [sessionTitle, setSessionTitle] = useState('')
  const [llmReady, setLlmReady] = useState(true)
  const [contextUsage, setContextUsage] = useState<ContextUsage | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const streamAbortRef = useRef<AbortController | null>(null)
  const empty = !sessionId

  const slashMenu = useSkillSlashMenu(input, setInput, skills, enableSkills)

  const syncTextareaHeight = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    const min = empty ? 120 : 52
    const max = empty ? 320 : 180
    el.style.height = `${Math.min(max, Math.max(min, el.scrollHeight))}px`
  }, [empty])

  useEffect(() => {
    syncTextareaHeight()
  }, [input, syncTextareaHeight, attachedFiles.length])

  useEffect(() => {
    if (params.get('compose') !== 'schedule') return
    setScheduleCompose(true)
    setInput(SCHEDULE_DRAFT)
    const next = new URLSearchParams(params)
    next.delete('compose')
    next.delete('mode')
    setParams(next, { replace: true })
    window.setTimeout(() => textareaRef.current?.focus(), 50)
  }, [params, setParams])

  const loadMeta = async () => {
    const [p, e, k, sk, mcp, llm] = await Promise.all([
      apiRequest<{ items: Profile[] }>('GET', '/api/v1/settings/llm/profiles'),
      apiRequest<{ items: Expert[] }>('GET', '/api/v1/experts'),
      apiRequest<{ items: Knowledge[] }>('GET', '/api/v1/knowledge/bases'),
      apiRequest<{ items: SkillOption[] }>('GET', '/api/v1/skills'),
      apiRequest<{ items: Mcp[] }>('GET', '/api/v1/mcp/servers'),
      apiRequest<{ model: string; api_key_masked: string }>('GET', '/api/v1/settings/llm'),
    ])
    setProfiles(p.items)
    setExperts(e.items)
    setKnowledge(k.items)
    // 合并 Hermes slash 命令到斜杠菜单
    let skillItems = sk.items || []
    try {
      const hx = await apiRequest<{ items: Array<{ id: string; name: string; description: string }> }>(
        'GET',
        '/api/v1/skills/hermes/slash-commands',
      )
      const seen = new Set(skillItems.map((x) => x.id))
      for (const h of hx.items || []) {
        if (!seen.has(h.id)) {
          skillItems.push({
            id: h.id,
            name: h.name,
            description: h.description,
            enabled: true,
          } as SkillOption)
        }
      }
    } catch {
      /* hermes 未就绪时忽略 */
    }
    setSkills(skillItems)
    setMcps(mcp.items)
    setLlmReady(Boolean(llm.model))
    if (!modelProfileId) {
      const def = p.items.find((x) => x.is_default) || p.items[0]
      if (def) setModelProfileId(def.id)
    }
  }

  const loadMessages = async (sid: string) => {
    const data = await apiRequest<{
      items: Array<{
        id: string
        role: string
        content: string
        reasoning_content?: string | null
        tool_calls?: Array<{ id: string; function?: { name?: string; arguments?: string } }>
        tool_call_id?: string
      }>
    }>('GET', `/api/v1/sessions/${sid}/messages`)
    const msgs = formatHistoryMessages(data.items)
    useAppStore.setState((s) => {
      // 流式进行中：禁止用历史快照覆盖本地增量（含思考过程）
      if (s.activeRuns[sid]) return s
      // 非流式：始终以服务端历史为准，避免串会话脏缓存粘住错误内容
      return {
        messageCache: { ...s.messageCache, [sid]: msgs },
        messages: s.sessionId === sid ? msgs : s.messages,
      }
    })
  }

  const loadPendingConfirm = async (sid: string) => {
    try {
      const data = await apiRequest<{
        pending: {
          run_id: string
          tool_call_id: string
          name: string
          arguments: unknown
        } | null
      }>('GET', `/api/v1/sessions/${sid}/pending-confirm`)
      if (useAppStore.getState().sessionId !== sid) return
      if (data.pending) {
        setConfirm({
          run_id: data.pending.run_id,
          tool_call_id: data.pending.tool_call_id,
          name: data.pending.name,
          arguments: data.pending.arguments,
        })
      } else {
        setConfirm(null)
      }
    } catch {
      // 忽略：旧后端无此接口时不挡对话
    }
  }

  useEffect(() => {
    loadMeta().catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    const fromUrl = params.get('session')
    if (fromUrl && fromUrl !== sessionId) {
      setSessionId(fromUrl)
    }
  }, [params])

  useEffect(() => {
    if (!sessionId) {
      setConfirm(null)
      return
    }
    const state = useAppStore.getState()
    const sid = sessionId
    const cached = state.messageCache[sid]
    // 进行中的会话：只恢复本地缓存，绝不再拉历史覆盖流式内容
    if (state.activeRuns[sid]) {
      if (cached?.length) setMessages(cached, sid)
      return
    }
    if (cached?.length) {
      setMessages(cached, sid)
    }
    loadMessages(sid).catch((e) => setError(String(e)))
    void loadPendingConfirm(sid)
  }, [sessionId])

  useEffect(() => {
    setAttachedFiles([])
    setRemoteRunning(false)
    setRemoteRunId(null)
  }, [sessionId])

  // 打开定时任务会话时：若后端仍在跑，轮询消息直到结束（避免工具跑完后像卡住）
  useEffect(() => {
    if (!sessionId || currentStreaming) {
      if (currentStreaming) {
        setRemoteRunning(false)
        setRemoteRunId(null)
      }
      return
    }
    const sid = sessionId
    let cancelled = false
    let timer: number | undefined
    let wasActive = false

    const poll = async () => {
      try {
        const st = await apiRequest<{
          active: boolean
          run?: { id: string; status: string } | null
        }>('GET', `/api/v1/sessions/${sid}/active-run`)
        if (cancelled || useAppStore.getState().sessionId !== sid) return
        if (useAppStore.getState().activeRuns[sid]) return

        if (st.active) {
          wasActive = true
          setRemoteRunning(true)
          setRemoteRunId(st.run?.id || null)
          lastStreamEventAt.current = Date.now()
          setStreamHint((prev) => prev || '后台任务执行中（完成后会自动刷新）…')
          await loadMessages(sid)
          if (!cancelled) timer = window.setTimeout(() => void poll(), 1600)
          return
        }

        setRemoteRunning(false)
        setRemoteRunId(null)
        if (wasActive) {
          wasActive = false
          setStreamHint('')
          await loadMessages(sid)
          void loadPendingConfirm(sid)
          bumpSessionList()
        }
      } catch {
        if (!cancelled) timer = window.setTimeout(() => void poll(), 3200)
      }
    }

    void poll()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [sessionId, currentStreaming])

  useEffect(() => {
    if (!viewStreaming) {
      if (!remoteRunning) setStreamHint('')
      return
    }
    const tick = window.setInterval(() => {
      const idle = Date.now() - lastStreamEventAt.current
      if (idle > 20000) {
        setStreamHint((prev) =>
          prev ||
          (remoteRunning
            ? '后台仍在生成（长思考或联网搜索中）…'
            : '模型仍在生成（长思考中，可点停止）…'),
        )
      }
    }, 4000)
    return () => window.clearInterval(tick)
  }, [viewStreaming, remoteRunning])

  useEffect(() => {
    let cancelled = false
    if (!sessionId) {
      setContextUsage(null)
      return
    }
    ;(async () => {
      try {
        const u = await apiRequest<ContextUsage>('GET', `/api/v1/sessions/${sessionId}/context`)
        if (!cancelled) setContextUsage(parseContextUsage(u as Record<string, unknown>))
      } catch {
        if (!cancelled) setContextUsage(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  const refreshContextUsage = useCallback(async (sid: string) => {
    try {
      const u = await apiRequest<ContextUsage>('GET', `/api/v1/sessions/${sid}/context`)
      if (useAppStore.getState().sessionId === sid) {
        setContextUsage(parseContextUsage(u as Record<string, unknown>))
      }
    } catch {
      /* 用量展示失败不阻断对话 */
    }
  }, [])

  useEffect(() => {
    if (!sessionId) {
      setSessionTitle('')
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const s = await apiRequest<Session>('GET', `/api/v1/sessions/${sessionId}`)
        if (!cancelled) setSessionTitle(s.title || '新任务')
      } catch {
        if (!cancelled) setSessionTitle('')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sessionId, sessionListTick])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [messages, viewStreaming])

  const applyComposerBindings = useCallback((defaults: ComposerBindingDefaults) => {
    setExpertId(defaults.expertId)
    setSkillIds(defaults.skillIds)
    setMcpIds(defaults.mcpIds)
    setKnowledgeIds(defaults.knowledgeIds)
    if (defaults.modelProfileId) setModelProfileId(defaults.modelProfileId)
  }, [])

  const clearComposerBindings = useCallback(() => {
    applyComposerBindings(emptyComposerBindings())
  }, [applyComposerBindings])

  const loadWorkspaceDefaultsIntoComposer = useCallback(async () => {
    if (!workspaceId) return
    const defaults = await fetchWorkspaceComposerDefaults(workspaceId)
    applyComposerBindings(defaults)
    setBindingsTouched(true)
  }, [workspaceId, applyComposerBindings])

  // 打开已有会话：优先反填上次发送时的绑定（MCP/技能等）
  useEffect(() => {
    let cancelled = false
    if (!sessionId) {
      // 回到「新建任务」空态时清空芯片，避免脏状态串会话
      clearComposerBindings()
      setBindingsTouched(false)
      return
    }
    ;(async () => {
      try {
        const saved = await fetchSessionComposerDefaults(sessionId)
        if (cancelled) return
        if (saved) {
          applyComposerBindings(saved)
          setBindingsTouched(true)
          return
        }
        // 首轮发送中：保留当前芯片，勿清空
        if (useAppStore.getState().activeRuns[sessionId]) {
          return
        }
        // 无会话绑定：若本轮标记了继承工作空间默认，则回填工作空间
        if (workspaceId && inheritWorkspaceDefaults && consumeApplyWorkspaceDefaults()) {
          await loadWorkspaceDefaultsIntoComposer()
          return
        }
        // 切换到无绑定记忆的会话：清空芯片，避免从上个会话串过来
        clearComposerBindings()
        setBindingsTouched(false)
      } catch (e) {
        if (!cancelled) setError(String(e))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  useEffect(() => {
    if (!workspaceId) return
    if (sessionId) return // 已有会话走上面的会话反填逻辑
    if (!consumeApplyWorkspaceDefaults()) return
    if (!inheritWorkspaceDefaults) return
    loadWorkspaceDefaultsIntoComposer().catch((e) => setError(String(e)))
  }, [sessionId, workspaceId, inheritWorkspaceDefaults, consumeApplyWorkspaceDefaults, loadWorkspaceDefaultsIntoComposer])

  const resolveBindingPayload = () => {
    if (bindingsTouched) {
      return {
        expert_id: expertId || null,
        skill_ids: skillIds,
        mcp_ids: mcpIds,
        knowledge_ids: knowledgeIds,
      }
    }
    return {
      expert_id: expertId || null,
      skill_ids: skillIds.length ? skillIds : null,
      mcp_ids: mcpIds.length ? mcpIds : null,
      knowledge_ids: knowledgeIds.length ? knowledgeIds : null,
    }
  }

  const ensureSession = async () => {
    if (sessionId) return sessionId

    let wsId = workspaceId
    if (!wsId && pendingFolderPath) {
      const ws = await ensureFolderWorkspace(pendingFolderPath)
      wsId = ws.id
      setWorkspaceId(ws.id)
      setPendingFolderPath(null)
      bumpWorkspaceList()
    }

    const bindingPayload = resolveBindingPayload()
    const s = await apiRequest<Session>('POST', '/api/v1/sessions', {
      title: wsId ? '项目会话' : '新任务',
      workspace_id: wsId,
    })
    // 先写入当前芯片，避免 setSessionId 触发反填时把 MCP 等冲掉
    try {
      await apiRequest('PATCH', `/api/v1/sessions/${s.id}`, {
        composer_bindings: {
          expert_id: bindingPayload.expert_id,
          skill_ids: bindingPayload.skill_ids,
          mcp_ids: bindingPayload.mcp_ids,
          knowledge_ids: bindingPayload.knowledge_ids,
          model_profile_id: modelProfileId || null,
        },
      })
    } catch {
      /* 绑定持久化失败不阻断开聊；stream 时会再写一次 */
    }
    setSessionId(s.id)
    // 立刻占位，避免 navigate 后 loadMessages 用空历史冲掉即将写入的首轮消息
    setSessionRun(s.id, 'pending')
    // 独立任务进「任务」侧栏；有工作空间则进「空间」并展开
    useAppStore.getState().setSidebarViewMode(wsId ? 'space' : 'group')
    bumpSessionList()
    navigate(
      wsId ? `/tasks?session=${s.id}&from=workspace` : `/tasks?session=${s.id}`,
      { replace: true },
    )
    return s.id
  }

  const uploadAttachments = async (sid: string, pending: AttachedFile[]) => {
    const toUpload = pending.filter((f) => !f.attachmentId)
    if (!toUpload.length) return pending

    const paths = toUpload.filter((f) => f.localPath).map((f) => f.localPath!)
    const files = toUpload
      .filter((f) => !f.localPath)
      .map((f) => ({
        name: f.name,
        content: f.base64 || f.textContent || '',
        encoding: f.base64 ? 'base64' : 'utf-8',
      }))

    const body: { paths?: string[]; files?: typeof files } = {}
    if (paths.length) body.paths = paths
    if (files.length) body.files = files

    const res = await apiRequest<{ items: Array<{ id: string; name: string }> }>(
      'POST',
      `/api/v1/sessions/${sid}/attachments`,
      body,
    )

    const uploadedNames = new Set(res.items.map((x) => x.name))
    const merged = pending.map((f) => {
      if (f.attachmentId) return f
      const hit = res.items.find((x) => x.name === f.name || x.name.endsWith(f.name))
      return hit ? { ...f, attachmentId: hit.id } : f
    })
    for (const item of res.items) {
      if (!merged.some((m) => m.attachmentId === item.id)) {
        merged.push({ id: item.id, name: item.name, attachmentId: item.id })
      }
    }
    void uploadedNames
    return merged
  }

  const toggleId = (list: string[], id: string, setter: (v: string[]) => void) => {
    setter(list.includes(id) ? list.filter((x) => x !== id) : [...list, id])
  }

  const send = async () => {
    if (!input.trim()) return
    if (viewStreaming) return
    if (!llmReady) {
      setError('请先在设置中配置模型')
      return
    }
    setError('')
    setConfirm(null)
    setStreamHint('')
    lastStreamEventAt.current = Date.now()
    const content = input.trim()
    setInput('')
    slashMenu.close()
    let sid = sessionId
    let filesForTurn = attachedFiles
    try {
      sid = await ensureSession()
      // 已有会话也要先占位，挡住 session 切换触发的 loadMessages 竞态
      setSessionRun(sid, 'pending')
      filesForTurn = await uploadAttachments(sid, attachedFiles)
      setAttachedFiles([])
    } catch (e) {
      if (sid) setSessionRun(sid, null)
      setError(String(e))
      return
    }
    const useAttachments = filesForTurn.length > 0
    const displayContent = useAttachments
      ? `${content}\n\n[附件: ${filesForTurn.map((f) => f.name).join(', ')}]`
      : content
    appendMessage({ role: 'user', content: displayContent }, sid)
    // 立即占位：不等 run_started，避免「只有用户气泡、无思考区」
    appendMessage({ role: 'assistant', content: '', reasoning: '' }, sid)
    const bindingPayload = resolveBindingPayload()
    streamAbortRef.current?.abort()
    const abort = new AbortController()
    streamAbortRef.current = abort
    try {
      await apiStream(
        '/api/v1/chat/stream',
        {
          session_id: sid,
          content,
          enable_skills: enableSkills,
          enable_mcp: enableMcp || bindingPayload.mcp_ids !== null,
          enable_memory: enableMemory,
          enable_knowledge:
            !useAttachments &&
            (bindingPayload.knowledge_ids !== null || (!bindingsTouched && Boolean(workspaceId))),
          model_profile_id: modelProfileId || null,
          expert_id: bindingPayload.expert_id,
          skill_ids: bindingPayload.skill_ids,
          mcp_ids: bindingPayload.mcp_ids,
          knowledge_ids: useAttachments ? null : bindingPayload.knowledge_ids,
          use_attachments: useAttachments,
        },
        (event, data) => {
          const d = data as Record<string, unknown>
          lastStreamEventAt.current = Date.now()
          if (event === 'status') {
            const msg = typeof d.message === 'string' ? d.message : ''
            if (msg && useAppStore.getState().sessionId === sid) setStreamHint(msg)
          }
          if (event === 'token' || event === 'reasoning' || event === 'tool_start' || event === 'tool_result') {
            setStreamHint('')
          }
          if (event === 'session_title') bumpSessionList()
          if (event === 'run_started') {
            setSessionRun(sid, String(d.run_id))
          }
          if (event === 'token') patchLastAssistant(String(d.delta || ''), sid)
          if (event === 'reasoning') patchLastReasoning(String(d.delta || ''), sid)
          if (event === 'tool_surface') {
            // 工具面仅用于调试，不插入对话，避免打断思考占位
          }
          if (event === 'tool_start') {
            appendMessage(
              {
                role: 'tool',
                content: `调用工具 ${d.name}\n${JSON.stringify(d.arguments, null, 2)}`,
              },
              sid,
            )
          }
          if (event === 'tool_result') {
            appendMessage(
              {
                role: 'tool',
                content: `工具结果 ${d.name}\n${JSON.stringify(d.result, null, 2)}`,
              },
              sid,
            )
          }
          if (event === 'knowledge_hit') {
            appendMessage(
              {
                role: 'tool',
                content: `资料库引用\n${JSON.stringify(d.items, null, 2)}`,
              },
              sid,
            )
          }
          if (event === 'attachments_loaded') {
            appendMessage(
              {
                role: 'tool',
                content: `已加载上传文件\n${JSON.stringify(d.items, null, 2)}`,
              },
              sid,
            )
          }
          if (event === 'skill_activated') {
            appendMessage(
              {
                role: 'tool',
                content: `已斜杠激活技能 /${d.skill_id}`,
              },
              sid,
            )
          }
          if (event === 'context_usage') {
            if (useAppStore.getState().sessionId !== sid) return
            setContextUsage(parseContextUsage(d as Record<string, unknown>))
          }
          if (event === 'compress') {
            if (useAppStore.getState().sessionId === sid) {
              setContextUsage((prev) =>
                parseContextUsage(
                  {
                    ...(d as Record<string, unknown>),
                    compressed: true,
                    has_summary: true,
                  },
                  prev,
                ),
              )
            }
            appendMessage(
              {
                role: 'tool',
                content: `上下文已压缩：${d.before_tokens} → ${d.after_tokens} tokens` +
                  (d.summarized_messages != null ? `（摘要 ${d.summarized_messages} 条，保留 ${d.kept_messages} 条）` : ''),
              },
              sid,
            )
          }
          if (event === 'tool_confirm') {
            // 暂停等待确认：立刻结束「流式中」状态，否则发送钮会一直转圈
            setSessionRun(sid, null)
            if (useAppStore.getState().sessionId === sid) {
              setConfirm({
                run_id: String(d.run_id),
                tool_call_id: String(d.tool_call_id),
                name: String(d.name),
                arguments: d.arguments,
              })
            }
          }
          if (event === 'error' && useAppStore.getState().sessionId === sid) {
            setError(
              typeof d.message === 'string'
                ? d.message
                : JSON.stringify(d),
            )
          }
          if (event === 'done') {
            setSessionRun(sid, null)
            if (d.status === 'waiting_confirm') {
              void loadPendingConfirm(sid)
            } else {
              // 以服务端落库为准，避免流式合并/竞态导致界面空白
              void loadMessages(sid)
              void refreshContextUsage(sid)
            }
          }
        },
        { signal: abort.signal },
      )
    } catch (e) {
      if (e instanceof StreamAbortedError) {
        // 用户主动停止，不弹错误
      } else if (useAppStore.getState().sessionId === sid) {
        setError(String(e))
      }
    } finally {
      if (streamAbortRef.current === abort) streamAbortRef.current = null
      setSessionRun(sid, null)
      // 再拉一次，覆盖「done 事件丢失但后端已写完」的情况
      void loadMessages(sid)
    }
  }

  const stop = async () => {
    if (!sessionId || !effectiveRunId) return
    const sid = sessionId
    const runId = effectiveRunId
    // 立刻解锁 UI；pending 时后端按 session 停止
    setSessionRun(sid, null)
    setRemoteRunning(false)
    setRemoteRunId(null)
    setStreamHint('')
    streamAbortRef.current?.abort()
    streamAbortRef.current = null
    try {
      await apiRequest('POST', '/api/v1/chat/stop', {
        session_id: sid,
        run_id: runId,
      })
    } catch {
      // 停止失败时 UI 已解锁；忽略
    }
    void loadMessages(sid)
  }

  const resolveConfirm = async (approve: boolean) => {
    if (!confirm || !sessionId) return
    const path = approve ? '/api/v1/chat/confirm' : '/api/v1/chat/reject'
    const sid = sessionId
    setSessionRun(sid, confirm.run_id)
    streamAbortRef.current?.abort()
    const abort = new AbortController()
    streamAbortRef.current = abort
    try {
      await apiStream(
        path,
        {
          session_id: sessionId,
          run_id: confirm.run_id,
          tool_call_id: confirm.tool_call_id,
          approve,
        },
        (event, data) => {
          const d = data as Record<string, unknown>
          if (event === 'token') patchLastAssistant(String(d.delta || ''), sid)
          if (event === 'reasoning') patchLastReasoning(String(d.delta || ''), sid)
          if (event === 'tool_result') {
            appendMessage({ role: 'tool', content: JSON.stringify(d.result, null, 2) }, sid)
          }
          if (event === 'done') {
            setConfirm(null)
          }
        },
        { signal: abort.signal },
      )
    } catch (e) {
      if (!(e instanceof StreamAbortedError) && useAppStore.getState().sessionId === sid) {
        setError(String(e))
      }
    } finally {
      if (streamAbortRef.current === abort) streamAbortRef.current = null
      setSessionRun(sid, null)
    }
  }

  const attachProps = {
    experts,
    skills,
    mcps,
    knowledge,
    expertId,
    skillIds,
    mcpIds,
    knowledgeIds,
    files: attachedFiles,
    onExpertChange: (id: string) => {
      setBindingsTouched(true)
      setExpertId(id)
    },
    onSkillToggle: (id: string) => {
      setBindingsTouched(true)
      toggleId(skillIds, id, setSkillIds)
    },
    onMcpToggle: (id: string) => {
      setBindingsTouched(true)
      toggleId(mcpIds, id, setMcpIds)
    },
    onKnowledgeToggle: (id: string) => {
      setBindingsTouched(true)
      toggleId(knowledgeIds, id, setKnowledgeIds)
    },
    onFilesChange: setAttachedFiles,
  }

  const showWorkspaceBack = params.get('from') === 'workspace' && Boolean(workspaceId)

  const workspaceBackBtn = showWorkspaceBack ? (
    <button type="button" className="chat-topbar-back" onClick={() => navigate('/projects')}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M15 6l-6 6 6 6"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span>返回工作空间</span>
    </button>
  ) : null

  const buddyMood = resolveBuddyMood(input, Boolean(viewStreaming))

  const composer = (
    <div className={`composer${empty ? ' composer-with-buddy' : ''}`}>
      {empty ? <BuddyMascot mood={buddyMood} /> : null}
      {scheduleCompose ? (
        <div className="compose-schedule-banner">
          <span>通过会话创建定时任务：补全名称、时间与执行内容后发送，助手会调用 schedule_task。</span>
          <div className="compose-schedule-actions">
            <button type="button" className="ghost sm" onClick={() => navigate('/automation')}>
              返回自动化
            </button>
            <button type="button" className="ghost sm" onClick={() => setScheduleCompose(false)}>
              关闭提示
            </button>
          </div>
        </div>
      ) : null}
      <SkillSlashMenu
        open={slashMenu.open}
        items={slashMenu.filtered}
        activeIndex={slashMenu.activeIndex}
        onPick={(id) => slashMenu.pick(id, textareaRef.current)}
        onHover={slashMenu.setActiveIndex}
      />
      <ComposerChips {...attachProps} />
      <div className="composer-input-wrap chat-input-box">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => {
            setInput(e.target.value)
            slashMenu.sync(e.target.value, e.target.selectionStart ?? e.target.value.length)
            syncTextareaHeight()
          }}
          onKeyUp={(e) => {
            if (['ArrowUp', 'ArrowDown', 'Escape', 'Enter', 'Tab'].includes(e.key)) return
            const t = e.currentTarget
            slashMenu.sync(t.value, t.selectionStart ?? t.value.length)
          }}
          onSelect={(e) => {
            const t = e.currentTarget
            slashMenu.sync(t.value, t.selectionStart ?? t.value.length)
          }}
          placeholder={
            scheduleCompose
              ? '描述定时任务的时间与要做的事…'
              : empty
                ? '今天我能帮你做什么？@ 引用文件 / 调用技能或指令…'
                : '继续对话，/ 调用技能与指令…'
          }
          onKeyDown={(e) => {
            if (slashMenu.handleKeyDown(e, () => void send())) return
          }}
        />
      </div>
      <div className="composer-bar">
        <div className="left">
          <ComposerAttachMenu {...attachProps} />
          {/* 新建任务主页可选工作空间；独立会话进行中不展示 */}
          {(empty || workspaceId || pendingFolderPath) && (
            <WorkspacePicker locked={Boolean(sessionId)} />
          )}
        </div>
        <div className="right">
          {viewStreaming && (
            <button type="button" className="ghost" onClick={() => void stop()}>
              停止
            </button>
          )}
          <select
            className="model-select"
            value={modelProfileId}
            onChange={(e) => setModelProfileId(e.target.value)}
            title="选择模型"
          >
            <option value="">Auto</option>
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.model}
              </option>
            ))}
          </select>
          {contextUsage && sessionId ? <ContextUsageMeter usage={contextUsage} /> : null}
          <button
            type="button"
            className="icon-btn send"
            disabled={viewStreaming || !input.trim()}
            onClick={() => void send()}
            title="发送 Enter"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  )

  const confirmUi = confirm && (
    <div className="confirm-bar" role="alertdialog" aria-label="高风险工具待确认">
      <div className="confirm-bar-title">
        需要你确认后才能继续：<strong>{confirm.name}</strong>
        {confirm.name === 'fs_write' ? '（写入本地文件）' : ''}
      </div>
      <pre className="confirm-bar-preview muted">{formatConfirmArgs(confirm.name, confirm.arguments)}</pre>
      <div className="row confirm-bar-actions">
        <button className="primary" onClick={() => void resolveConfirm(true)}>
          确认执行
        </button>
        <button className="danger" onClick={() => void resolveConfirm(false)}>
          拒绝
        </button>
      </div>
    </div>
  )

  if (empty) {
    return (
      <div className="chat-home chat-wrap">
        {workspaceBackBtn ? <div className="chat-home-topbar">{workspaceBackBtn}</div> : null}
        <div className="chat-hero">
          <h2>今天我能帮你做什么？</h2>
          <p className="muted">流式对话 · 可选模型 / 专家 / 资料库</p>
          {!llmReady && (
            <p className="error-line">
              尚未配置模型，请先前往 <Link to="/settings">设置</Link>
            </p>
          )}
        </div>
        <div className="cap-row">
          {CAPS.map((label) => (
            <span key={label} className="cap-chip">
              {label}
            </span>
          ))}
        </div>
        {composer}
        {confirmUi}
        {error && <div className="error-line chat-inline-error">错误：{error}</div>}
      </div>
    )
  }

  return (
    <div className="chat-work-shell">
      {(workspaceBackBtn || sessionTitle) && (
        <header className="chat-work-topbar">
          {workspaceBackBtn}
          {sessionTitle ? (
            <div className="chat-work-title-block">
              <p className="chat-work-kicker">当前会话</p>
              <h1 className="chat-work-title" title={sessionTitle}>
                {sessionTitle}
              </h1>
            </div>
          ) : null}
        </header>
      )}
      <div className="chat-log chat-wrap" ref={logRef}>
        <ChatLog messages={messages} streaming={viewStreaming} />
      </div>
      <div className="chat-composer-dock">
        {confirmUi}
        {error && <div className="error-line chat-inline-error">错误：{error}</div>}
        {viewStreaming && streamHint ? (
          <div className="stream-hint muted">{streamHint}</div>
        ) : null}
        {composer}
      </div>
    </div>
  )
}
