/**
 * 自动化列表页：定时任务卡片、保持唤醒、模板区。
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiRequest } from '../lib/api'
import { formatDateTime, formatFutureRelative } from '../lib/formatTime'
import Modal from '../components/Modal'
import Toast from '../components/Toast'

type Job = {
  id: string
  name: string
  prompt: string
  schedule_raw: string
  schedule_kind: string
  next_run_at?: string | null
  enabled: boolean
  state: string
  last_run_at?: string | null
  last_status?: string | null
  last_error?: string | null
  run_count?: number
}

type JobRun = {
  id: string
  session_id?: string | null
  status: string
  started_at: string
  finished_at?: string | null
  output_preview?: string | null
  error_message?: string | null
}

const KEEP_AWAKE_KEY = 'psa-keep-awake-on-run'

const SCHEDULED_TEMPLATES = [
  {
    id: 'kb-digest',
    icon: 'list',
    name: '资料库每日摘要',
    description: '每天定时对已绑定资料库做要点摘要，输出可直接阅读的 Markdown 简报。',
  },
  {
    id: 'git-standup',
    icon: 'list',
    name: 'Git 站会摘要',
    description:
      '汇总本周 Git 活动，生成周五站会摘要：列出重要提交、已合并 PR 及主要变更，并保持简洁。',
  },
  {
    id: 'example',
    icon: 'check',
    name: '晨会动态',
    description:
      '汇总上一个工作日以来的提交、模块变化、CI 状态和待跟进事项，最终生成不超过 6 条的晨会口述摘要。',
  },
]

function TemplateIcon({ kind }: { kind: string }) {
  if (kind === 'pulse') {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M3 12h3l2-5 3 10 2-5h8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  if (kind === 'check') {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M9 6h11M9 12h11M9 18h11M5 6l.8.8L7.5 5M5 12l.8.8L7.5 11M5 18l.8.8L7.5 17" />
      </svg>
    )
  }
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" strokeLinecap="round" />
    </svg>
  )
}

/** 将 cron / interval / once 转成可读标签 */
export function formatScheduleLabel(raw: string, kind: string): string {
  const text = (raw || '').trim()
  if (kind === 'interval' || /^every\s+/i.test(text)) {
    const m = text.match(/(\d+)\s*(m|min|h|hr|d|day)/i)
    if (m) {
      const n = m[1]
      const u = m[2].toLowerCase()
      if (u.startsWith('m')) return `每 ${n} 分钟`
      if (u.startsWith('h')) return `每 ${n} 小时`
      if (u.startsWith('d')) return `每 ${n} 天`
    }
    return text
  }
  if (kind === 'once' || /^in\s+/i.test(text)) {
    return text.startsWith('in ') ? `一次性（${text}）` : '一次性'
  }
  const parts = text.split(/\s+/)
  if (parts.length === 5) {
    const [min, hour, , , dow] = parts
    const hh = hour === '*' ? '**' : hour.padStart(2, '0')
    const mm = min === '*' ? '**' : min.padStart(2, '0')
    const time = hour !== '*' && min !== '*' ? `${hh}:${mm}` : text
    if (dow === '1-5' || dow === 'MON-FRI') return `每工作日 ${time}`
    if (dow === '*') return `每天 ${time}`
    if (dow === '5' || dow === 'FRI') return `每周五 ${time}`
    if (dow === '1' || dow === 'MON') return `每周一 ${time}`
    return `Cron ${time}`
  }
  return text || '未设置'
}

function truncate(text: string, max = 120): string {
  const t = (text || '').replace(/\s+/g, ' ').trim()
  if (t.length <= max) return t
  return `${t.slice(0, max)}…`
}

export default function ScheduledTasksPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<Job[]>([])
  const [detail, setDetail] = useState<Job | null>(null)
  const [runs, setRuns] = useState<JobRun[]>([])
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)
  const [createMenuOpen, setCreateMenuOpen] = useState(false)
  const [cardMenuId, setCardMenuId] = useState<string | null>(null)
  const createMenuRef = useRef<HTMLDivElement>(null)
  const [keepAwake, setKeepAwake] = useState(() => {
    try {
      return localStorage.getItem(KEEP_AWAKE_KEY) === '1'
    } catch {
      return false
    }
  })
  const [refreshing, setRefreshing] = useState(false)

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 4000)
  }

  const load = async () => {
    const jobs = await apiRequest<{ items: Job[] }>('GET', '/api/v1/scheduled-jobs')
    setItems(jobs.items)
  }

  useEffect(() => {
    load().catch((e) => showToast(String(e), 'error'))
  }, [])

  useEffect(() => {
    if (!createMenuOpen && !cardMenuId) return
    const onDoc = (e: MouseEvent) => {
      if (createMenuRef.current && !createMenuRef.current.contains(e.target as Node)) {
        setCreateMenuOpen(false)
      }
      const t = e.target as HTMLElement
      if (!t.closest?.('.auto-card-menu-wrap')) setCardMenuId(null)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [createMenuOpen, cardMenuId])

  const toggleKeepAwake = () => {
    setKeepAwake((v) => {
      const next = !v
      try {
        localStorage.setItem(KEEP_AWAKE_KEY, next ? '1' : '0')
      } catch {
        /* ignore */
      }
      showToast(next ? '已开启：运行会话时尽量保持唤醒（需系统支持）' : '已关闭保持唤醒')
      return next
    })
  }

  const goCreateNow = () => {
    setCreateMenuOpen(false)
    navigate('/automation/new')
  }

  const goCreateInChat = () => {
    setCreateMenuOpen(false)
    navigate('/tasks?compose=schedule')
  }

  const goCreateFromTemplate = (template?: string) => {
    setCreateMenuOpen(false)
    navigate(template ? `/automation/new?template=${template}` : '/automation/new')
  }

  const refresh = async () => {
    setRefreshing(true)
    try {
      await load()
      showToast('已刷新')
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setRefreshing(false)
    }
  }

  const openDetail = async (job: Job) => {
    setDetail(job)
    setCardMenuId(null)
    try {
      const r = await apiRequest<{ items: JobRun[] }>('GET', `/api/v1/scheduled-jobs/${job.id}/runs`)
      setRuns(r.items)
    } catch (e) {
      showToast(String(e), 'error')
      setRuns([])
    }
  }

  return (
    <div className="auto-page">
      {toast ? <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} /> : null}

      <header className="auto-hero">
        <h1>自动化</h1>
        <p className="muted">按计划运行定时任务，或在需要时随时执行。</p>
      </header>

      <div className="auto-topbar">
        <h2 className="auto-section-label" style={{ margin: 0 }}>
          定时任务
        </h2>
        <div className="auto-topbar-actions">
          <button
            type="button"
            className="auto-icon-btn"
            aria-label="刷新"
            title="刷新"
            disabled={refreshing}
            onClick={() => void refresh()}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M21 12a9 9 0 1 1-2.6-6.3" strokeLinecap="round" />
              <path d="M21 3v6h-6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <div className="auto-create-wrap" ref={createMenuRef}>
            <button
              type="button"
              className="auto-btn-primary"
              onClick={() => setCreateMenuOpen((v) => !v)}
            >
              创建定时任务
              <span className="auto-btn-caret" aria-hidden>
                ▾
              </span>
            </button>
            {createMenuOpen ? (
              <div className="auto-create-menu">
                <button type="button" onClick={goCreateNow}>
                  立即创建
                </button>
                <button type="button" onClick={goCreateInChat}>
                  去会话中创建
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <div className="auto-awake-bar">
        <div className="auto-awake-copy">
          <span className="auto-info-icon" aria-hidden>
            i
          </span>
          <span>运行会话时保持电脑唤醒。</span>
        </div>
        <button
          type="button"
          className={`auto-switch ${keepAwake ? 'on' : ''}`}
          role="switch"
          aria-checked={keepAwake}
          onClick={toggleKeepAwake}
        >
          <span className="auto-switch-knob" />
        </button>
      </div>

      <section className="auto-created">
        <h2 className="auto-section-label">已创建任务</h2>
        {items.length === 0 ? (
          <div className="auto-empty-inline">
            <p className="muted">还没有定时任务</p>
            <button type="button" className="ghost" onClick={goCreateNow}>
              立即创建
            </button>
          </div>
        ) : (
          <div className="auto-card-list">
            {items.map((j) => {
              const sched = formatScheduleLabel(j.schedule_raw, j.schedule_kind)
              const next = formatFutureRelative(j.next_run_at)
              const badge = next ? `${sched} · 下次运行 ${next}` : !j.enabled ? `${sched} · 已暂停` : sched
              return (
                <article
                  key={j.id}
                  className="auto-task-card"
                  onClick={() => navigate(`/automation/${j.id}/edit`)}
                >
                  <div className="auto-task-card-top">
                    <h3>{j.name}</h3>
                    <div className="auto-card-menu-wrap" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="auto-card-more"
                        aria-label="更多"
                        onClick={() => setCardMenuId((id) => (id === j.id ? null : j.id))}
                      >
                        ···
                      </button>
                      {cardMenuId === j.id ? (
                        <div className="auto-create-menu auto-card-menu">
                          <button type="button" onClick={() => void openDetail(j)}>
                            运行历史
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setCardMenuId(null)
                              navigate(`/automation/${j.id}/edit`)
                            }}
                          >
                            编辑
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setCardMenuId(null)
                              void apiRequest('POST', `/api/v1/scheduled-jobs/${j.id}/run`)
                                .then(() => showToast('已触发'))
                                .catch((e) => showToast(String(e), 'error'))
                            }}
                          >
                            立即运行
                          </button>
                          {j.enabled ? (
                            <button
                              type="button"
                              onClick={() => {
                                setCardMenuId(null)
                                void apiRequest('POST', `/api/v1/scheduled-jobs/${j.id}/pause`)
                                  .then(() => load())
                                  .then(() => showToast('已暂停'))
                                  .catch((e) => showToast(String(e), 'error'))
                              }}
                            >
                              暂停
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => {
                                setCardMenuId(null)
                                void apiRequest('POST', `/api/v1/scheduled-jobs/${j.id}/resume`)
                                  .then(() => load())
                                  .then(() => showToast('已恢复'))
                                  .catch((e) => showToast(String(e), 'error'))
                              }}
                            >
                              恢复
                            </button>
                          )}
                          <button
                            type="button"
                            className="danger-text"
                            onClick={() => {
                              setCardMenuId(null)
                              if (!window.confirm(`删除「${j.name}」？`)) return
                              void apiRequest('DELETE', `/api/v1/scheduled-jobs/${j.id}`)
                                .then(() => load())
                                .then(() => showToast('已删除'))
                                .catch((e) => showToast(String(e), 'error'))
                            }}
                          >
                            删除
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                  <p className="auto-task-desc">{truncate(j.prompt)}</p>
                  <div className="auto-task-foot">
                    <span className="auto-sched-badge">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="9" />
                        <path d="M12 7v5l3 2" strokeLinecap="round" />
                      </svg>
                      {badge}
                    </span>
                    <span className="auto-run-count">已运行 {j.run_count ?? 0} 次</span>
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>

      <hr className="auto-divider" />

      <section className="auto-templates">
        <h2>定时任务模板</h2>
        <div className="auto-template-grid">
          {SCHEDULED_TEMPLATES.map((tpl) => (
            <button
              key={tpl.id}
              type="button"
              className="auto-template-card"
              onClick={() => goCreateFromTemplate(tpl.id)}
            >
              <div className="auto-template-head">
                <span className="auto-template-icon">
                  <TemplateIcon kind={tpl.icon} />
                </span>
                <strong>{tpl.name}</strong>
              </div>
              <p>{tpl.description}</p>
              <div className="auto-template-foot muted">一键创建</div>
            </button>
          ))}
        </div>
      </section>

      <Modal
        open={!!detail}
        title={detail ? `运行历史 · ${detail.name}` : '运行历史'}
        onClose={() => setDetail(null)}
      >
        {detail ? (
          <div className="stack">
            <div className="muted">
              {detail.schedule_raw} · 下次 {formatDateTime(detail.next_run_at)}
            </div>
            {runs.length === 0 ? (
              <p className="muted">暂无运行记录</p>
            ) : (
              runs.map((r) => (
                <div key={r.id} className="panel stack" style={{ gap: 8 }}>
                  <div className="row" style={{ justifyContent: 'space-between' }}>
                    <strong>{r.status}</strong>
                    <span className="muted">{formatDateTime(r.started_at)}</span>
                  </div>
                  {r.error_message ? <div style={{ color: 'var(--danger)' }}>{r.error_message}</div> : null}
                  {r.output_preview ? (
                    <pre style={{ whiteSpace: 'pre-wrap', margin: 0, fontSize: 12 }}>{r.output_preview}</pre>
                  ) : null}
                  {r.session_id ? (
                    <div>
                      <button
                        type="button"
                        className="ghost"
                        onClick={() => {
                          setDetail(null)
                          navigate(`/tasks?session=${r.session_id}`)
                        }}
                      >
                        查看会话
                      </button>
                    </div>
                  ) : null}
                </div>
              ))
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  )
}
