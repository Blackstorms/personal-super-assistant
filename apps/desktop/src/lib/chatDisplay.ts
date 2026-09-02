/**
 * 将对话消息分组，并解析工具调用 / 模型推理为可读的思考步骤。
 */
import type { ChatMessage } from '../stores/app'

export type ThinkingAction = {
  id: string
  label: string
  detail: string
}

export type ThinkingItem =
  | { type: 'reasoning'; content: string }
  | { type: 'text'; content: string }
  | { type: 'action'; action: ThinkingAction }

export type ChatTurn = {
  items: ThinkingItem[]
  answer?: ChatMessage
  /** 助手正文正在流式输出 */
  answerStreaming?: boolean
  /** 工具/推理阶段仍在进行，尚未进入正文输出 */
  thinkingStreaming?: boolean
}

export type ChatBlock =
  | { type: 'user'; content: string; key: string }
  | { type: 'turn'; turn: ChatTurn; key: string }

type ApiMessage = {
  id: string
  role: string
  content: string
  reasoning_content?: string | null
  tool_calls?: Array<{ id: string; function?: { name?: string; arguments?: string } }>
  tool_call_id?: string
}

const TOOL_LABELS: Record<string, (args?: Record<string, unknown>) => string> = {
  fs_read: () => '已读取 1 个文件',
  fs_list: () => '已列出目录',
  fs_write: () => '已写入文件',
  knowledge_search: () => '已检索资料库',
  web_search: (a) => {
    const q = String(a?.query || '').trim()
    return q ? `已联网搜索「${q.slice(0, 40)}${q.length > 40 ? '…' : ''}」` : '已联网搜索'
  },
  current_time: (a) => {
    const tz = String(a?.timezone || '').trim()
    return tz ? `已查询时间（${tz}）` : '已查询当前时间'
  },
  describe_skill: (a) => `已加载技能 ${String(a?.skill_id || '')}`.trim(),
  run_skill: (a) => `已运行技能 ${String(a?.skill_id || '')}`.trim(),
  feishu_send_message: () => '已发送飞书消息',
  feishu_lookup_user: () => '已查询飞书用户',
  feishu_create_task: () => '已创建飞书任务',
}

function parseToolCall(content: string): { phase: 'start' | 'result' | 'meta'; name?: string; label: string; detail: string } | null {
  const lines = content.split('\n')
  const head = lines[0] || ''

  if (head.startsWith('调用工具 ')) {
    const name = head.replace('调用工具 ', '').trim()
    const argsRaw = lines.slice(1).join('\n')
    let args: Record<string, unknown> = {}
    try {
      args = JSON.parse(argsRaw) as Record<string, unknown>
    } catch {
      /* ignore */
    }
    const labelFn = TOOL_LABELS[name]
    const label = labelFn ? labelFn(args) : `已调用 ${name}`
    return { phase: 'start', name, label, detail: content }
  }

  if (head.startsWith('工具结果 ')) {
    const name = head.replace('工具结果 ', '').trim()
    const labelFn = TOOL_LABELS[name]
    const label = labelFn ? labelFn() : `已完成 ${name}`
    return { phase: 'result', name, label, detail: content }
  }

  if (head.startsWith('资料库引用')) {
    return { phase: 'meta', label: '已检索资料库', detail: content }
  }
  if (head.startsWith('已斜杠激活技能')) {
    return { phase: 'meta', label: head, detail: content }
  }
  if (head.startsWith('上下文已压缩')) {
    return { phase: 'meta', label: '已压缩上下文', detail: content }
  }
  if (head.startsWith('已加载上传文件')) {
    return { phase: 'meta', label: '已加载上传文件', detail: content }
  }

  return { phase: 'meta', label: '执行步骤', detail: content }
}

function toolMessageToAction(m: ChatMessage, index: number, pending: Map<string, ThinkingAction>): ThinkingItem | null {
  const parsed = parseToolCall(m.content)
  if (!parsed) return null

  if (parsed.phase === 'start' && parsed.name) {
    const action: ThinkingAction = {
      id: m.id || `tool-${index}`,
      label: parsed.label,
      detail: parsed.detail,
    }
    pending.set(parsed.name, action)
    return { type: 'action', action }
  }

  if (parsed.phase === 'result' && parsed.name && pending.has(parsed.name)) {
    const existing = pending.get(parsed.name)!
    existing.detail = `${existing.detail}\n\n${parsed.detail}`
    return null
  }

  return {
    type: 'action',
    action: {
      id: m.id || `tool-${index}`,
      label: parsed.label,
      detail: parsed.detail,
    },
  }
}

const THINK_PAIR_RE = /<(think|thinking|reasoning)\s*>([\s\S]*?)<\/\1\s*>/gi
const THINK_OPEN_RE = /<(think|thinking|reasoning)\s*>/i
const THINK_CLOSE_RE = /<\/(think|thinking|reasoning)\s*>/i

/** 从正文抽出 think 标签，避免思考过程被 Markdown 当答案渲染 */
export function splitThinkFromContent(raw: string): { reasoning: string; content: string } {
  if (!raw) return { reasoning: '', content: '' }
  THINK_PAIR_RE.lastIndex = 0
  let reasoning = ''
  let content = raw.replace(THINK_PAIR_RE, (_m, _tag: string, inner: string) => {
    reasoning += inner
    return ''
  })

  const openIdx = content.search(THINK_OPEN_RE)
  if (openIdx >= 0) {
    const m = content.slice(openIdx).match(THINK_OPEN_RE)
    if (m) {
      reasoning += content.slice(openIdx + m[0].length)
      content = content.slice(0, openIdx)
    }
  }

  const closeIdx = content.search(THINK_CLOSE_RE)
  if (closeIdx >= 0) {
    reasoning = content.slice(0, closeIdx) + reasoning
    content = content.slice(closeIdx).replace(THINK_CLOSE_RE, '')
  }

  return { reasoning, content }
}

/** 思考增量被网关重复写入 content 时，不应升为答案正文 */
export function isLeakedReasoningBody(content: string, reasoning: string, streaming = false): boolean {
  const c = content.trim()
  const r = (reasoning || '').trim()
  if (!c || !r) return false
  if (c === r) return true
  if (r.endsWith(c) || (c.length <= 24 && r.includes(c) && (streaming || c.length <= 16))) return true
  if (r.length >= 40 && c.startsWith(r)) return true
  // 短 stub + 长思考：多为思考模型漏进 content 的碎片（如「基本齐全马上」）
  if (c.length <= 48 && r.length >= 120) return true
  if (c.length <= 80 && r.length >= c.length * 8) return true
  // 规划/工具独白典型句式，不应当最终攻略正文
  if (
    r.length >= 80 &&
    c.length <= 400 &&
    /^(用户没给出|我按记忆|先 fs_|做一轮搜索|然后编写|白名单根目录参数)/m.test(c)
  ) {
    return true
  }
  return false
}

export function isolateAssistantReasoning(m: ChatMessage, streaming = false): ChatMessage {
  const peeled = splitThinkFromContent(m.content || '')
  const reasoning = mergeReasoningText(m.reasoning || '', peeled.reasoning)
  let content = peeled.content
  if (isLeakedReasoningBody(content, reasoning, streaming)) {
    content = ''
  }
  return { ...m, content, reasoning: reasoning || undefined }
}

function mergeReasoningText(a: string, b: string): string {
  const x = a || ''
  const y = b || ''
  if (!y) return x
  if (!x) return y
  if (x.includes(y)) return x
  if (y.includes(x)) return y
  return `${x}${y}`
}

function pushAssistantThinking(items: ThinkingItem[], m: ChatMessage) {
  if (m.reasoning?.trim()) {
    items.push({ type: 'reasoning', content: m.reasoning })
  }
  if (m.content.trim()) {
    items.push({ type: 'text', content: m.content })
  }
}

function buildTurnItems(
  turnMessages: ChatMessage[],
  streamingLast = false,
): { items: ThinkingItem[]; answer?: ChatMessage } {
  const items: ThinkingItem[] = []
  const pending = new Map<string, ThinkingAction>()
  let answer: ChatMessage | undefined
  const lastAssistantIdx = (() => {
    for (let i = turnMessages.length - 1; i >= 0; i--) {
      if (turnMessages[i].role === 'assistant') return i
    }
    return -1
  })()

  turnMessages.forEach((raw, idx) => {
    if (raw.role === 'assistant') {
      const m = isolateAssistantReasoning(raw, streamingLast && idx === lastAssistantIdx)
      const after = turnMessages.slice(idx + 1)
      const hasLaterAssistant = after.some((x) => x.role === 'assistant')
      const hasToolAfter = after.some((x) => x.role === 'tool')
      if (!hasLaterAssistant && !hasToolAfter) {
        // 推理始终进思考区；勿把 reasoning 升为正文（流式思考会被 Markdown 正文样式渲染）
        answer = m
        if (m.reasoning?.trim()) {
          items.push({ type: 'reasoning', content: m.reasoning })
        }
        return
      }
      pushAssistantThinking(items, m)
      return
    }

    if (raw.role === 'tool') {
      const item = toolMessageToAction(raw, idx, pending)
      if (item) items.push(item)
    }
  })

  return { items, answer }
}

/** 将 API 历史消息转为与流式一致的展示格式 */
export function formatHistoryMessages(raw: ApiMessage[]): ChatMessage[] {
  const out: ChatMessage[] = []
  const callById = new Map<string, { name: string; args: Record<string, unknown> }>()

  for (const m of raw) {
    if (m.role === 'user') {
      out.push({ id: m.id, role: 'user', content: m.content || '' })
      continue
    }

    if (m.role === 'assistant') {
      const reasoning = (m.reasoning_content || '').trim() || undefined
      if (m.tool_calls?.length) {
        if (m.content?.trim() || reasoning) {
          out.push({
            id: m.id,
            role: 'assistant',
            content: m.content || '',
            reasoning,
          })
        }
        for (const tc of m.tool_calls) {
          const name = tc.function?.name || 'tool'
          let args: Record<string, unknown> = {}
          try {
            args = JSON.parse(tc.function?.arguments || '{}') as Record<string, unknown>
          } catch {
            /* ignore */
          }
          callById.set(tc.id, { name, args })
          out.push({
            role: 'tool',
            content: `调用工具 ${name}\n${JSON.stringify(args, null, 2)}`,
          })
        }
      } else {
        // 历史：正文与 reasoning 分离；展示层会再剥 think 标签并丢掉重复 stub
        out.push({
          id: m.id,
          role: 'assistant',
          content: m.content || '',
          reasoning,
        })
      }
      continue
    }

    if (m.role === 'tool') {
      const call = m.tool_call_id ? callById.get(m.tool_call_id) : undefined
      const name = call?.name || 'tool'
      out.push({
        id: m.id,
        role: 'tool',
        content: `工具结果 ${name}\n${m.content || ''}`,
      })
    }
  }

  return out
}

export function groupChatMessages(messages: ChatMessage[], streamingLast = false): ChatBlock[] {
  const blocks: ChatBlock[] = []
  let i = 0

  while (i < messages.length) {
    const m = messages[i]
    if (m.role === 'user') {
      blocks.push({ type: 'user', content: m.content, key: m.id || `user-${i}` })
      i += 1
      continue
    }

    const turnStart = i
    const turnMessages: ChatMessage[] = []

    while (i < messages.length && messages[i].role !== 'user') {
      turnMessages.push(messages[i])
      i += 1
    }

    const isLastTurn = i >= messages.length
    const { items, answer } = buildTurnItems(turnMessages, isLastTurn && streamingLast)
    const lastInTurn = answer ?? turnMessages[turnMessages.length - 1]
    const answerContent = lastInTurn?.role === 'assistant' ? String(lastInTurn.content || '').trim() : ''
    const waitingForAnswer =
      !lastInTurn || lastInTurn.role !== 'assistant' || !answerContent
    const answerStreaming =
      isLastTurn && streamingLast && lastInTurn?.role === 'assistant' && Boolean(answerContent)
    const thinkingStreaming = isLastTurn && streamingLast && waitingForAnswer

    const hasAnswer = Boolean(answerContent) || answerStreaming
    if (!items.length && !hasAnswer && !thinkingStreaming) continue

    blocks.push({
      type: 'turn',
      key: `turn-${turnStart}`,
      turn: {
        items,
        answer: hasAnswer ? answer : undefined,
        answerStreaming,
        thinkingStreaming,
      },
    })
  }

  // 流式已开始但尚未插入助手占位时，仍显示「思考中…」
  if (streamingLast && blocks.length > 0) {
    const last = blocks[blocks.length - 1]
    if (last.type === 'user') {
      blocks.push({
        type: 'turn',
        key: `turn-pending-${blocks.length}`,
        turn: {
          items: [],
          thinkingStreaming: true,
        },
      })
    }
  }

  return blocks
}

export const THINK_AUTO_COLLAPSE_KEY = 'psa.thinkAutoCollapse'

export function getThinkAutoCollapse(): boolean {
  try {
    const v = localStorage.getItem(THINK_AUTO_COLLAPSE_KEY)
    if (v === null) return true
    return v === '1'
  } catch {
    return true
  }
}

export function setThinkAutoCollapse(on: boolean) {
  try {
    localStorage.setItem(THINK_AUTO_COLLAPSE_KEY, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}
