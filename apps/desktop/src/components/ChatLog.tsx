/**
 * 对话消息列表：对齐 WorkBuddy —
 * 用户浅灰气泡靠右；助手头像+名称，下方「思考中/已完成」可展开，正文无卡片。
 */
import { useEffect, useRef, useState } from 'react'
import type { ChatTurn } from '../lib/chatDisplay'
import { getThinkAutoCollapse, groupChatMessages } from '../lib/chatDisplay'
import { BrandMarkIcon } from './AppBrand'
import MarkdownContent from './MarkdownContent'
import type { ChatMessage } from '../stores/app'

const ASSISTANT_NAME = '超级助理'

type Props = {
  messages: ChatMessage[]
  streaming?: boolean
}

function formatDuration(sec: number | undefined): string | null {
  if (sec == null || sec <= 0) return null
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return s ? `${m}m${s}s` : `${m}m`
}

function thinkStatusLabel(opts: { active: boolean; durationSec?: number }): string {
  if (opts.active) return '思考中…'
  const d = formatDuration(opts.durationSec)
  if (d) return `已完成 ${d}`
  return '思考过程'
}

function AssistantAvatar() {
  return (
    <span className="assistant-avatar" aria-hidden>
      <BrandMarkIcon size={16} />
    </span>
  )
}

function ThinkingSection({
  turn,
  defaultCollapsed,
  autoCollapse,
}: {
  turn: ChatTurn
  defaultCollapsed: boolean
  autoCollapse: boolean
}) {
  const thinkingActive = Boolean(turn.thinkingStreaming)
  const turnActive = thinkingActive || Boolean(turn.answerStreaming)
  const hasDetail = turn.items.length > 0 || thinkingActive
  const [open, setOpen] = useState(!defaultCollapsed && hasDetail)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [durationSec, setDurationSec] = useState<number | undefined>(undefined)
  const startRef = useRef<number | null>(null)
  const hasAutoClosed = useRef(false)
  /** 用户手动点开/收起后，不再自动折叠 */
  const userPinned = useRef(false)

  useEffect(() => {
    if (turnActive) {
      if (startRef.current == null) startRef.current = Date.now()
      userPinned.current = false
      hasAutoClosed.current = false
      setOpen(true)
    } else if (startRef.current != null) {
      setDurationSec(Math.max(1, Math.ceil((Date.now() - startRef.current) / 1000)))
      startRef.current = null
    }
  }, [turnActive])

  useEffect(() => {
    // 仅在「本轮刚结束且用户未手动操作」时自动收起一次
    if (!autoCollapse || turnActive || !open || hasAutoClosed.current || userPinned.current) return
    if (!defaultCollapsed && !turn.items.length) return
    const timer = window.setTimeout(() => {
      if (userPinned.current) return
      if (defaultCollapsed || Boolean(turn.answer?.content)) {
        setOpen(false)
        hasAutoClosed.current = true
      }
    }, 1000)
    return () => window.clearTimeout(timer)
  }, [autoCollapse, turnActive, open, defaultCollapsed, turn.items.length, turn.answer?.content])

  if (!hasDetail && !durationSec) return null

  return (
    <div className="think-block">
      <button
        type="button"
        className={`think-head${turnActive ? ' is-active' : ''}`}
        onClick={() => {
          userPinned.current = true
          setOpen((v) => !v)
        }}
        aria-expanded={open}
      >
        <span>{thinkStatusLabel({ active: turnActive, durationSec })}</span>
        <span className="think-chevron">{open ? '⌄' : '›'}</span>
      </button>
      {open && (
        <div className="think-body">
          {turn.items.map((item, idx) => {
            if (item.type === 'reasoning') {
              const isLastReasoning = turn.items.slice(idx + 1).every((x) => x.type !== 'reasoning')
              const live = thinkingActive && isLastReasoning
              return (
                <div key={`r-${idx}`} className="think-reasoning">
                  <p className={`think-reasoning-text${live ? ' is-streaming' : ''}`}>
                    {item.content}
                    {live ? <span className="stream-caret" aria-hidden /> : null}
                  </p>
                </div>
              )
            }
            if (item.type === 'text') {
              return (
                <p key={`t-${idx}`} className="think-text">
                  {item.content}
                </p>
              )
            }
            const { action } = item
            const detailOpen = expandedId === action.id
            return (
              <div key={action.id} className="think-step">
                <button
                  type="button"
                  className="think-step-line"
                  onClick={() => setExpandedId(detailOpen ? null : action.id)}
                >
                  {action.label}
                </button>
                {detailOpen && <pre className="think-step-detail">{action.detail}</pre>}
              </div>
            )
          })}
          {thinkingActive && !turn.items.some((x) => x.type === 'reasoning' && x.content.trim()) && (
            <p className="think-pulse" aria-live="polite">
              深度思考
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export default function ChatLog({ messages, streaming = false }: Props) {
  const blocks = groupChatMessages(messages, streaming)
  const autoCollapse = getThinkAutoCollapse()

  return (
    <>
      {blocks.map((block) => {
        if (block.type === 'user') {
          return (
            <div key={block.key} className="bubble user chat-user-bubble">
              {block.content}
            </div>
          )
        }

        const { turn } = block
        const hasAnswer = Boolean(turn.answer?.content) || Boolean(turn.answerStreaming)
        const showThinking =
          turn.items.length > 0 || Boolean(turn.thinkingStreaming) || Boolean(turn.answerStreaming)
        const collapseThinking = hasAnswer && !turn.answerStreaming && !turn.thinkingStreaming

        return (
          <div key={block.key} className="chat-turn">
            <div className="assistant-head">
              <AssistantAvatar />
              <div className="assistant-meta">
                <div className="assistant-name">{ASSISTANT_NAME}</div>
                {showThinking && (
                  <ThinkingSection
                    turn={turn}
                    defaultCollapsed={collapseThinking}
                    autoCollapse={autoCollapse}
                  />
                )}
              </div>
            </div>
            {hasAnswer && (
              <div className="assistant-answer chat-ai-bubble">
                <MarkdownContent
                  content={turn.answer?.content || ''}
                  streaming={Boolean(turn.answerStreaming)}
                />
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}
