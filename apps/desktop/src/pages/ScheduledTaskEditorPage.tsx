/**
 * 新建 / 编辑定时任务全页（对齐 Cursor 自动化编辑器布局）。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { apiRequest } from '../lib/api'
import { formatDateTime } from '../lib/formatTime'
import Modal from '../components/Modal'
import Toast from '../components/Toast'

type Job = {
  id: string
  name: string
  prompt: string
  schedule_raw: string
  schedule_kind: string
  next_run_at?: string | null
  delivery_mode?: string
  expert_id?: string | null
  model_profile_id?: string | null
  knowledge_ids?: string[] | null
  workspace_id?: string | null
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

type Profile = { id: string; name: string }
type Expert = { id: string; name: string }
type Knowledge = { id: string; name?: string | null }
type Workspace = { id: string; name: string }

type ScheduleOptionId = 'hourly' | 'daily' | 'weekday' | 'weekly' | 'monthly' | 'custom'

const SCHEDULE_OPTIONS: Array<{ id: ScheduleOptionId; label: string }> = [
  { id: 'hourly', label: '每小时' },
  { id: 'daily', label: '每天' },
  { id: 'weekday', label: '每工作日' },
  { id: 'weekly', label: '每周' },
  { id: 'monthly', label: '每月' },
  { id: 'custom', label: '自定义' },
]

const WEEKDAY_OPTS = [
  { v: 1, label: '一' },
  { v: 2, label: '二' },
  { v: 3, label: '三' },
  { v: 4, label: '四' },
  { v: 5, label: '五' },
  { v: 6, label: '六' },
  { v: 0, label: '日' },
] as const

type EveryUnit = 'm' | 'h' | 'd' | 'w' | 'mo' | 'y'

const UNIT_LABEL: Record<EveryUnit, string> = {
  m: '分钟',
  h: '小时',
  d: '天',
  w: '周',
  mo: '个月',
  y: '年',
}

const CUSTOM_UNIT_OPTS: Array<{ value: EveryUnit; label: string }> = [
  { value: 'm', label: '分钟' },
  { value: 'h', label: '小时' },
  { value: 'd', label: '天' },
  { value: 'w', label: '周' },
  { value: 'mo', label: '个月' },
  { value: 'y', label: '年' },
]

const pad2 = (n: number) => String(n).padStart(2, '0')

const TIME_OPTIONS = Array.from({ length: 48 }, (_, i) => {
  const hour = Math.floor(i / 2)
  const minute = i % 2 === 0 ? 0 : 30
  return { hour, minute, label: `${pad2(hour)}:${pad2(minute)}` }
})

const MINUTE_OPTIONS = Array.from({ length: 60 }, (_, m) => m)
const MONTH_DAY_OPTIONS = Array.from({ length: 31 }, (_, i) => i + 1)

const TEMPLATES: Record<
  string,
  { name: string; prompt: string; scheduleMode: 'cron' | 'every' | 'at'; cron?: string; at?: string }
> = {
  'git-standup': {
    name: 'Git 站会摘要',
    prompt:
      '汇总本仓库本周 Git 活动，生成周五站会摘要：重要提交、已合并 PR、主要变更；输出简洁 Markdown。',
    scheduleMode: 'cron',
    cron: '0 17 * * 5',
  },
  'ci-flaky': {
    name: 'CI 失败与不稳定测试报告',
    prompt: '扫描最近 CI 运行，列出失败与不稳定测试、可能原因，并按影响范围给出修复建议；输出结构化报告。',
    scheduleMode: 'at',
    at: 'in 2h',
  },
  'docs-sync': {
    name: '文档同步检查',
    prompt:
      '基于当前代码与最近提交，检查 README、docs、配置说明与示例是否过时或与实现不一致；列出差异与修改建议。',
    scheduleMode: 'at',
    at: 'in 1h',
  },
  'kb-digest': {
    name: '资料库每日摘要',
    prompt: '总结资料库中最近相关要点，输出简洁 Markdown 报告。',
    scheduleMode: 'cron',
    cron: '0 9 * * *',
  },
  example: {
    name: '每日资料库摘要',
    prompt: '总结资料库中最近相关要点，输出简洁 Markdown 报告。',
    scheduleMode: 'cron',
    cron: '0 9 * * *',
  },
}

const CONFIRM_MODES = [
  { id: 'confirm', label: '变更前确认' },
  { id: 'auto', label: '自动执行' },
]

const EFFORT_LEVELS = [
  { id: 'highest', label: '最高' },
  { id: 'high', label: '高' },
  { id: 'standard', label: '标准' },
  { id: 'low', label: '低' },
]

type FormState = {
  name: string
  prompt: string
  scheduleMode: 'cron' | 'every' | 'at'
  cron: string
  every: string
  at: string
  scheduleAdded: boolean
  scheduleLabel: string
  scheduleOptionId: ScheduleOptionId | ''
  schMinute: number
  schHour: number
  schWeekdays: number[]
  schMonthDay: number
  schEveryAmount: number
  schEveryUnit: EveryUnit
  schEndNever: boolean
  schEndDate: string
  delivery_mode: 'new_session' | 'fixed_session'
  model_profile_id: string
  expert_id: string
  knowledge_ids: string[]
  workspace_id: string
  confirmMode: string
  effort: string
}

const emptyForm = (): FormState => ({
  name: '未命名定时任务',
  prompt: '',
  scheduleMode: 'cron',
  cron: '0 9 * * *',
  every: 'every 1d',
  at: 'in 1h',
  scheduleAdded: false,
  scheduleLabel: '',
  scheduleOptionId: '',
  schMinute: 0,
  schHour: 9,
  schWeekdays: [1, 2, 3, 4, 5],
  schMonthDay: 1,
  schEveryAmount: 1,
  schEveryUnit: 'd',
  schEndNever: true,
  schEndDate: new Date().toISOString().slice(0, 10),
  delivery_mode: 'new_session',
  model_profile_id: '',
  expert_id: '',
  knowledge_ids: [],
  workspace_id: '',
  confirmMode: 'confirm',
  effort: 'highest',
})

function weekdayLabel(days: number[]): string {
  const sorted = [...days].sort((a, b) => {
    const rank = (d: number) => (d === 0 ? 7 : d)
    return rank(a) - rank(b)
  })
  if (sorted.length === 5 && [1, 2, 3, 4, 5].every((d) => sorted.includes(d))) return '一、二、三、四、五'
  if (sorted.length === 7) return '每天'
  return sorted
    .map((d) => WEEKDAY_OPTS.find((w) => w.v === d)?.label || String(d))
    .join('、')
}

function cronDow(days: number[]): string {
  const uniq = [...new Set(days)].sort((a, b) => a - b)
  if (!uniq.length) return '1'
  if (uniq.length === 5 && [1, 2, 3, 4, 5].every((d) => uniq.includes(d))) return '1-5'
  return uniq.join(',')
}

/** 根据选项与细节字段生成 cron/every 与摘要文案 */
function materializeSchedule(
  optionId: ScheduleOptionId,
  details: Pick<
    FormState,
    | 'schMinute'
    | 'schHour'
    | 'schWeekdays'
    | 'schMonthDay'
    | 'schEveryAmount'
    | 'schEveryUnit'
    | 'schEndNever'
    | 'schEndDate'
  >,
): Pick<FormState, 'scheduleMode' | 'cron' | 'every' | 'at' | 'scheduleLabel'> {
  const m = Math.min(59, Math.max(0, details.schMinute | 0))
  const h = Math.min(23, Math.max(0, details.schHour | 0))
  const time = `${pad2(h)}:${pad2(m)}`
  if (optionId === 'hourly') {
    return {
      scheduleMode: 'cron',
      cron: `${m} * * * *`,
      every: details.schEveryAmount ? `every ${details.schEveryAmount}${details.schEveryUnit}` : 'every 1h',
      at: 'in 1h',
      scheduleLabel: `每小时的第 ${pad2(m)} 分`,
    }
  }
  if (optionId === 'daily') {
    return {
      scheduleMode: 'cron',
      cron: `${m} ${h} * * *`,
      every: 'every 1d',
      at: 'in 1h',
      scheduleLabel: `GMT+8 每天 ${time}`,
    }
  }
  if (optionId === 'weekday') {
    return {
      scheduleMode: 'cron',
      cron: `${m} ${h} * * 1-5`,
      every: 'every 1d',
      at: 'in 1h',
      scheduleLabel: `GMT+8 每工作日 ${time}`,
    }
  }
  if (optionId === 'weekly') {
    const days = details.schWeekdays.length ? details.schWeekdays : [1]
    return {
      scheduleMode: 'cron',
      cron: `${m} ${h} * * ${cronDow(days)}`,
      every: 'every 1d',
      at: 'in 1h',
      scheduleLabel: `GMT+8 每周${weekdayLabel(days)} ${time}`,
    }
  }
  if (optionId === 'monthly') {
    const day = Math.min(31, Math.max(1, details.schMonthDay | 0))
    return {
      scheduleMode: 'cron',
      cron: `${m} ${h} ${day} * *`,
      every: 'every 1d',
      at: 'in 1h',
      scheduleLabel: `GMT+8 每月 ${day} 号 ${time}`,
    }
  }
  // custom → interval / 每周 cron
  const amount = Math.max(1, details.schEveryAmount | 0)
  const unit = details.schEveryUnit
  const end = details.schEndNever ? '' : ` · 至 ${details.schEndDate}`
  if (unit === 'w') {
    const days = details.schWeekdays.length ? details.schWeekdays : [1]
    const dayText = weekdayLabel(days)
    if (amount === 1) {
      return {
        scheduleMode: 'cron',
        cron: `${m} ${h} * * ${cronDow(days)}`,
        every: `every ${amount}w`,
        at: 'in 1h',
        scheduleLabel: `每 1 周（周${dayText}）${end}`,
      }
    }
    return {
      scheduleMode: 'every',
      cron: '0 9 * * *',
      every: `every ${amount}w`,
      at: 'in 1h',
      scheduleLabel: `每 ${amount} 周（周${dayText}）${end}`,
    }
  }
  const every = `every ${amount}${unit}`
  return {
    scheduleMode: 'every',
    cron: '0 9 * * *',
    every,
    at: 'in 1h',
    scheduleLabel: `每 ${amount} ${UNIT_LABEL[unit]}${end}`,
  }
}

function scheduleSummary(form: FormState): string {
  if (!form.scheduleAdded) return ''
  if (form.scheduleLabel) return form.scheduleLabel
  if (form.scheduleMode === 'cron') return form.cron.trim() || 'Cron'
  if (form.scheduleMode === 'every') return form.every.trim() || '间隔'
  return form.at.trim() || '一次性'
}

function parseScheduleRaw(raw: string, kind: string): Partial<FormState> {
  const text = (raw || '').trim()
  const everyMatch = text.match(
    /^every\s+(\d+)\s*(mo|months?|m|min|mins|minute|minutes|h|hr|hour|hours|d|day|days|w|week|weeks|y|year|years)$/i,
  )
  if (kind === 'interval' || everyMatch) {
    const amount = everyMatch ? Number(everyMatch[1]) : 1
    const u = (everyMatch?.[2] || 'd').toLowerCase()
    let unit: EveryUnit = 'd'
    if (u === 'mo' || u.startsWith('month')) unit = 'mo'
    else if (u.startsWith('m')) unit = 'm'
    else if (u.startsWith('h')) unit = 'h'
    else if (u.startsWith('w')) unit = 'w'
    else if (u.startsWith('y')) unit = 'y'
    else unit = 'd'
    const base = {
      scheduleOptionId: 'custom' as const,
      schEveryAmount: amount,
      schEveryUnit: unit,
      ...materializeSchedule('custom', {
        schMinute: 0,
        schHour: 9,
        schWeekdays: [1],
        schMonthDay: 1,
        schEveryAmount: amount,
        schEveryUnit: unit,
        schEndNever: true,
        schEndDate: new Date().toISOString().slice(0, 10),
      }),
    }
    return base
  }
  if (kind === 'once' || text.startsWith('in ') || /\d{4}-\d{2}-\d{2}/.test(text)) {
    return {
      scheduleOptionId: 'custom',
      scheduleMode: 'at',
      at: text || 'in 1h',
      scheduleLabel: text || '一次性',
    }
  }
  const parts = text.split(/\s+/)
  if (parts.length === 5) {
    const minute = Number(parts[0])
    const hour = parts[1]
    const dom = parts[2]
    const dow = parts[4]
    const schMinute = Number.isFinite(minute) ? minute : 0
    const schHour = hour === '*' ? 9 : Number(hour) || 0
    if (hour === '*' && dom === '*' && dow === '*') {
      return {
        scheduleOptionId: 'hourly',
        schMinute,
        schHour: 0,
        ...materializeSchedule('hourly', {
          schMinute,
          schHour: 0,
          schWeekdays: [1, 2, 3, 4, 5],
          schMonthDay: 1,
          schEveryAmount: 1,
          schEveryUnit: 'd',
          schEndNever: true,
          schEndDate: new Date().toISOString().slice(0, 10),
        }),
      }
    }
    if (dom === '*' && dow === '*') {
      return {
        scheduleOptionId: 'daily',
        schMinute,
        schHour,
        ...materializeSchedule('daily', {
          schMinute,
          schHour,
          schWeekdays: [1, 2, 3, 4, 5],
          schMonthDay: 1,
          schEveryAmount: 1,
          schEveryUnit: 'd',
          schEndNever: true,
          schEndDate: new Date().toISOString().slice(0, 10),
        }),
      }
    }
    if (dom === '*' && (dow === '1-5' || dow === '1,2,3,4,5')) {
      return {
        scheduleOptionId: 'weekday',
        schMinute,
        schHour,
        schWeekdays: [1, 2, 3, 4, 5],
        ...materializeSchedule('weekday', {
          schMinute,
          schHour,
          schWeekdays: [1, 2, 3, 4, 5],
          schMonthDay: 1,
          schEveryAmount: 1,
          schEveryUnit: 'd',
          schEndNever: true,
          schEndDate: new Date().toISOString().slice(0, 10),
        }),
      }
    }
    if (dom === '*' && dow !== '*') {
      const days = dow.split(',').flatMap((p) => {
        if (p.includes('-')) {
          const [a, b] = p.split('-').map(Number)
          const out: number[] = []
          for (let i = a; i <= b; i++) out.push(i)
          return out
        }
        return [Number(p)]
      }).filter((n) => Number.isFinite(n))
      return {
        scheduleOptionId: 'weekly',
        schMinute,
        schHour,
        schWeekdays: days.length ? days : [1],
        ...materializeSchedule('weekly', {
          schMinute,
          schHour,
          schWeekdays: days.length ? days : [1],
          schMonthDay: 1,
          schEveryAmount: 1,
          schEveryUnit: 'd',
          schEndNever: true,
          schEndDate: new Date().toISOString().slice(0, 10),
        }),
      }
    }
    if (dow === '*' && dom !== '*') {
      const day = Number(dom) || 1
      return {
        scheduleOptionId: 'monthly',
        schMinute,
        schHour,
        schMonthDay: day,
        ...materializeSchedule('monthly', {
          schMinute,
          schHour,
          schWeekdays: [1, 2, 3, 4, 5],
          schMonthDay: day,
          schEveryAmount: 1,
          schEveryUnit: 'd',
          schEndNever: true,
          schEndDate: new Date().toISOString().slice(0, 10),
        }),
      }
    }
  }
  return {
    scheduleOptionId: 'custom',
    scheduleMode: 'cron',
    cron: text || '0 9 * * *',
    scheduleLabel: text || '自定义',
  }
}

export default function ScheduledTaskEditorPage() {
  const { jobId } = useParams<{ jobId?: string }>()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const isEdit = Boolean(jobId)

  const [tab, setTab] = useState<'settings' | 'history'>('settings')
  const [form, setForm] = useState(emptyForm)
  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(isEdit)
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [experts, setExperts] = useState<Expert[]>([])
  const [knowledge, setKnowledge] = useState<Knowledge[]>([])
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [runs, setRuns] = useState<JobRun[]>([])
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const [weekdayOpen, setWeekdayOpen] = useState(false)
  const [customModalOpen, setCustomModalOpen] = useState(false)
  const [customDraft, setCustomDraft] = useState({
    amount: 1,
    unit: 'd' as EveryUnit,
    weekdays: [1] as number[],
    endNever: true,
    endDate: new Date().toISOString().slice(0, 10),
  })
  const [projectOpen, setProjectOpen] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [modelOpen, setModelOpen] = useState(false)
  const [effortOpen, setEffortOpen] = useState(false)
  const toolbarRef = useRef<HTMLDivElement>(null)
  const scheduleMenuRef = useRef<HTMLDivElement>(null)

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 4000)
  }

  const patchSchedule = (optionId: ScheduleOptionId, patch: Partial<FormState> = {}) => {
    setForm((f) => {
      const next = { ...f, ...patch, scheduleOptionId: optionId, scheduleAdded: true }
      const built = materializeSchedule(optionId, next)
      return { ...next, ...built }
    })
  }

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (toolbarRef.current && !toolbarRef.current.contains(e.target as Node)) {
        setProjectOpen(false)
        setConfirmOpen(false)
        setModelOpen(false)
        setEffortOpen(false)
      }
      if (scheduleMenuRef.current && !scheduleMenuRef.current.contains(e.target as Node)) {
        setScheduleOpen(false)
        setWeekdayOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        const [p, ex, kn, ws] = await Promise.all([
          apiRequest<{ items: Profile[] }>('GET', '/api/v1/settings/llm/profiles'),
          apiRequest<{ items: Expert[] }>('GET', '/api/v1/experts'),
          apiRequest<{ items: Knowledge[] }>('GET', '/api/v1/knowledge/bases'),
          apiRequest<{ items: Workspace[] }>('GET', '/api/v1/workspaces'),
        ])
        setProfiles(p.items)
        setExperts(ex.items)
        setKnowledge(kn.items)
        setWorkspaces(ws.items)
      } catch (e) {
        showToast(String(e), 'error')
      }
    })()
  }, [])

  useEffect(() => {
    if (!isEdit || !jobId) {
      const tplKey = search.get('template')
      if (tplKey && TEMPLATES[tplKey]) {
        const tpl = TEMPLATES[tplKey]
        const raw = tpl.scheduleMode === 'at' ? tpl.at || 'in 1h' : tpl.cron || '0 9 * * *'
        const parsed = parseScheduleRaw(raw, tpl.scheduleMode === 'at' ? 'once' : 'cron')
        setForm({
          ...emptyForm(),
          name: tpl.name,
          prompt: tpl.prompt,
          scheduleAdded: true,
          ...parsed,
          scheduleMode: tpl.scheduleMode,
          cron: tpl.cron || parsed.cron || '0 9 * * *',
          at: tpl.at || parsed.at || 'in 1h',
        })
      }
      return
    }
    setLoading(true)
    void (async () => {
      try {
        const job = await apiRequest<Job>('GET', `/api/v1/scheduled-jobs/${jobId}`)
        const kind = job.schedule_kind
        const parsed = parseScheduleRaw(job.schedule_raw, kind)
        setForm({
          ...emptyForm(),
          name: job.name || '未命名定时任务',
          prompt: job.prompt || '',
          scheduleAdded: true,
          ...parsed,
          scheduleMode: kind === 'interval' ? 'every' : kind === 'once' ? 'at' : parsed.scheduleMode || 'cron',
          cron: kind === 'cron' ? job.schedule_raw : parsed.cron || '0 9 * * *',
          every: kind === 'interval' ? job.schedule_raw : parsed.every || 'every 1d',
          at: kind === 'once' ? job.schedule_raw : parsed.at || 'in 1h',
          delivery_mode: (job.delivery_mode as 'new_session' | 'fixed_session') || 'new_session',
          model_profile_id: job.model_profile_id || '',
          expert_id: job.expert_id || '',
          knowledge_ids: job.knowledge_ids || [],
          workspace_id: job.workspace_id || '',
        })
        const r = await apiRequest<{ items: JobRun[] }>('GET', `/api/v1/scheduled-jobs/${jobId}/runs`)
        setRuns(r.items)
      } catch (e) {
        showToast(String(e), 'error')
      } finally {
        setLoading(false)
      }
    })()
  }, [isEdit, jobId, search])

  const selectedModel = useMemo(
    () => profiles.find((p) => p.id === form.model_profile_id)?.name || '默认模型',
    [profiles, form.model_profile_id],
  )
  const selectedProject = useMemo(() => {
    if (!form.workspace_id) return '选择项目'
    return workspaces.find((w) => w.id === form.workspace_id)?.name || '选择项目'
  }, [workspaces, form.workspace_id])
  const confirmLabel = CONFIRM_MODES.find((c) => c.id === form.confirmMode)?.label || '变更前确认'
  const effortLabel = EFFORT_LEVELS.find((e) => e.id === form.effort)?.label || '最高'

  const buildBody = () => {
    const body: Record<string, unknown> = {
      name: form.name.trim() || '未命名定时任务',
      prompt: form.prompt.trim(),
      delivery_mode: form.delivery_mode,
      model_profile_id: form.model_profile_id || null,
      expert_id: form.expert_id || null,
      knowledge_ids: form.knowledge_ids.length ? form.knowledge_ids : null,
      workspace_id: form.workspace_id || null,
    }
    if (form.scheduleMode === 'cron') body.cron = form.cron.trim()
    else if (form.scheduleMode === 'every') body.every = form.every.trim()
    else body.at = form.at.trim()
    return body
  }

  const save = async () => {
    if (!form.scheduleAdded) {
      showToast('请先添加调度计划', 'error')
      setScheduleOpen(true)
      return
    }
    if (!form.prompt.trim()) {
      showToast('请填写指令', 'error')
      return
    }
    setSaving(true)
    try {
      const body = buildBody()
      if (isEdit && jobId) {
        await apiRequest('PUT', `/api/v1/scheduled-jobs/${jobId}`, body)
        showToast('已更新')
      } else {
        await apiRequest('POST', '/api/v1/scheduled-jobs', body)
        showToast('已创建')
      }
      navigate('/automation')
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  const openCustomModal = () => {
    setCustomDraft({
      amount: form.schEveryAmount || 1,
      unit: form.schEveryUnit || 'd',
      weekdays: form.schWeekdays.length ? form.schWeekdays : [1],
      endNever: form.schEndNever,
      endDate: form.schEndDate,
    })
    setCustomModalOpen(true)
  }

  const applyScheduleOption = (opt: (typeof SCHEDULE_OPTIONS)[number]) => {
    setScheduleOpen(false)
    if (opt.id === 'custom') {
      openCustomModal()
      return
    }
    patchSchedule(opt.id, {
      schWeekdays: opt.id === 'weekly' || opt.id === 'weekday' ? [1, 2, 3, 4, 5] : form.schWeekdays,
      schMinute: opt.id === 'hourly' ? form.schMinute : form.schMinute || 0,
      schHour: form.schHour || 9,
    })
  }

  const confirmCustom = () => {
    const weekdays = customDraft.weekdays.length ? customDraft.weekdays : [1]
    patchSchedule('custom', {
      schEveryAmount: Math.max(1, customDraft.amount | 0),
      schEveryUnit: customDraft.unit,
      schWeekdays: weekdays,
      schEndNever: customDraft.endNever,
      schEndDate: customDraft.endDate,
    })
    setCustomModalOpen(false)
  }

  if (loading) {
    return (
      <div className="auto-editor-page">
        <p className="muted">加载中…</p>
      </div>
    )
  }

  return (
    <div className="auto-editor-page">
      {toast ? <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} /> : null}

      <nav className="auto-editor-crumb">
        <Link to="/automation">自动化</Link>
        <span className="auto-editor-crumb-sep">›</span>
        <span>{isEdit ? '编辑任务' : '新建任务'}</span>
      </nav>

      <header className="auto-editor-hero">
        <h1>{isEdit ? '编辑定时任务' : '新建定时任务'}</h1>
        <p>配置任务的执行时间、指令和运行方式。</p>
      </header>

      <div className="auto-editor-toolbar">
        <div className="auto-editor-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'settings'}
            className={tab === 'settings' ? 'active' : ''}
            onClick={() => setTab('settings')}
          >
            设置
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'history'}
            className={tab === 'history' ? 'active' : ''}
            onClick={() => setTab('history')}
          >
            历史
          </button>
        </div>
        <button type="button" className="auto-editor-submit" disabled={saving} onClick={() => void save()}>
          {saving ? '保存中…' : isEdit ? '保存定时任务' : '创建定时任务'}
        </button>
      </div>

      {tab === 'history' ? (
        <section className="auto-editor-history">
          {!isEdit ? (
            <p className="muted">创建任务后才会有运行历史。</p>
          ) : runs.length === 0 ? (
            <p className="muted">暂无运行记录</p>
          ) : (
            runs.map((r) => (
              <div key={r.id} className="auto-editor-run">
                <div className="auto-editor-run-head">
                  <strong>{r.status}</strong>
                  <span className="muted">{formatDateTime(r.started_at)}</span>
                </div>
                {r.error_message ? <div className="auto-editor-run-err">{r.error_message}</div> : null}
                {r.output_preview ? <pre>{r.output_preview}</pre> : null}
                {r.session_id ? (
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => navigate(`/tasks?session=${r.session_id}`)}
                  >
                    查看会话
                  </button>
                ) : null}
              </div>
            ))
          )}
        </section>
      ) : (
        <section className="auto-editor-form">
          <label className="auto-editor-field">
            <span className="auto-editor-label">任务标题</span>
            <input
              className="auto-editor-input"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="未命名定时任务"
            />
          </label>

          <div className="auto-editor-field">
            <span className="auto-editor-label">调度</span>
            {!form.scheduleAdded ? (
              <div className="auto-editor-schedule-wrap" ref={scheduleMenuRef}>
                <button
                  type="button"
                  className="auto-editor-input auto-editor-schedule-trigger"
                  onClick={() => setScheduleOpen((v) => !v)}
                >
                  <span className="auto-editor-plus" aria-hidden>
                    +
                  </span>
                  添加计划
                </button>
                {scheduleOpen ? (
                  <div className="auto-editor-schedule-menu">
                    {SCHEDULE_OPTIONS.map((opt) => (
                      <button key={opt.id} type="button" onClick={() => applyScheduleOption(opt)}>
                        {opt.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="auto-editor-schedule-row" ref={scheduleMenuRef}>
                <select
                  className="auto-editor-sch-select"
                  value={form.scheduleOptionId || 'daily'}
                  onChange={(e) => {
                    const id = e.target.value as ScheduleOptionId
                    if (id === 'custom') {
                      openCustomModal()
                      return
                    }
                    patchSchedule(id)
                  }}
                >
                  {SCHEDULE_OPTIONS.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.label}
                    </option>
                  ))}
                </select>

                {form.scheduleOptionId === 'hourly' ? (
                  <>
                    <span className="auto-editor-sch-join">第</span>
                    <select
                      className="auto-editor-sch-select"
                      value={form.schMinute}
                      onChange={(e) => patchSchedule('hourly', { schMinute: Number(e.target.value) })}
                    >
                      {MINUTE_OPTIONS.map((m) => (
                        <option key={m} value={m}>
                          {pad2(m)}
                        </option>
                      ))}
                    </select>
                    <span className="auto-editor-sch-join">分钟</span>
                  </>
                ) : null}

                {form.scheduleOptionId === 'weekly' ? (
                  <div className="auto-editor-sch-weekday-wrap">
                    <button
                      type="button"
                      className="auto-editor-sch-select auto-editor-sch-weekday-btn"
                      onClick={() => setWeekdayOpen((v) => !v)}
                    >
                      {weekdayLabel(form.schWeekdays)}
                    </button>
                    {weekdayOpen ? (
                      <div className="auto-editor-sch-weekday-menu">
                        {WEEKDAY_OPTS.map((d) => {
                          const on = form.schWeekdays.includes(d.v)
                          return (
                            <button
                              key={d.v}
                              type="button"
                              className={on ? 'active' : ''}
                              onClick={() => {
                                const next = on
                                  ? form.schWeekdays.filter((x) => x !== d.v)
                                  : [...form.schWeekdays, d.v]
                                patchSchedule('weekly', { schWeekdays: next.length ? next : [d.v] })
                              }}
                            >
                              周{d.label}
                            </button>
                          )
                        })}
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {form.scheduleOptionId === 'monthly' ? (
                  <select
                    className="auto-editor-sch-select"
                    value={form.schMonthDay}
                    onChange={(e) => patchSchedule('monthly', { schMonthDay: Number(e.target.value) })}
                  >
                    {MONTH_DAY_OPTIONS.map((d) => (
                      <option key={d} value={d}>
                        {d} 号
                      </option>
                    ))}
                  </select>
                ) : null}

                {form.scheduleOptionId === 'daily' ||
                form.scheduleOptionId === 'weekday' ||
                form.scheduleOptionId === 'weekly' ||
                form.scheduleOptionId === 'monthly' ? (
                  <>
                    <span className="auto-editor-sch-join">于</span>
                    <select
                      className="auto-editor-sch-select"
                      value={`${pad2(form.schHour)}:${pad2(form.schMinute)}`}
                      onChange={(e) => {
                        const [hh, mm] = e.target.value.split(':').map(Number)
                        patchSchedule(form.scheduleOptionId as ScheduleOptionId, {
                          schHour: hh,
                          schMinute: mm,
                        })
                      }}
                    >
                      {/* 保证当前非整点半点时间也在列表中 */}
                      {!TIME_OPTIONS.some((t) => t.hour === form.schHour && t.minute === form.schMinute) ? (
                        <option value={`${pad2(form.schHour)}:${pad2(form.schMinute)}`}>
                          {pad2(form.schHour)}:{pad2(form.schMinute)}
                        </option>
                      ) : null}
                      {TIME_OPTIONS.map((t) => (
                        <option key={t.label} value={t.label}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </>
                ) : null}

                {form.scheduleOptionId === 'custom' ? (
                  <button
                    type="button"
                    className="auto-editor-sch-select auto-editor-sch-weekday-btn"
                    onClick={() => openCustomModal()}
                  >
                    {scheduleSummary(form)}
                  </button>
                ) : null}

                <span className="auto-editor-sch-summary muted">{scheduleSummary(form)}</span>

                <button
                  type="button"
                  className="auto-editor-sch-del"
                  title="清除调度"
                  aria-label="清除调度"
                  onClick={() =>
                    setForm((f) => ({
                      ...f,
                      scheduleAdded: false,
                      scheduleLabel: '',
                      scheduleOptionId: '',
                    }))
                  }
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                    <path d="M4 7h16M9 7V5h6v2M10 11v6M14 11v6M6 7l1 12h10l1-12" />
                  </svg>
                </button>
              </div>
            )}
          </div>

          <Modal
            open={customModalOpen}
            title="自定义重复"
            onClose={() => setCustomModalOpen(false)}
            footer={
              <>
                <button type="button" onClick={() => setCustomModalOpen(false)}>
                  取消
                </button>
                <button type="button" className="primary" onClick={confirmCustom}>
                  确认
                </button>
              </>
            }
          >
            <div className="auto-custom-repeat stack">
              <div className="auto-custom-block">
                <label className="auto-custom-label">重复频率</label>
                <div className="auto-custom-freq-row">
                  <input
                    className="auto-custom-amount"
                    type="number"
                    min={1}
                    value={customDraft.amount}
                    onChange={(e) =>
                      setCustomDraft((d) => ({ ...d, amount: Math.max(1, Number(e.target.value) || 1) }))
                    }
                  />
                  <select
                    className="auto-custom-unit"
                    value={customDraft.unit}
                    onChange={(e) => {
                      const unit = e.target.value as EveryUnit
                      setCustomDraft((d) => ({
                        ...d,
                        unit,
                        weekdays: unit === 'w' && !d.weekdays.length ? [1] : d.weekdays,
                      }))
                    }}
                  >
                    {CUSTOM_UNIT_OPTS.map((u) => (
                      <option key={u.value} value={u.value}>
                        {u.label}
                      </option>
                    ))}
                  </select>
                </div>
                {customDraft.unit === 'w' ? (
                  <div className="auto-custom-weekdays" role="group" aria-label="选择星期">
                    {WEEKDAY_OPTS.map((d) => {
                      const on = customDraft.weekdays.includes(d.v)
                      return (
                        <button
                          key={d.v}
                          type="button"
                          className={`auto-custom-weekday ${on ? 'active' : ''}`}
                          onClick={() => {
                            setCustomDraft((draft) => {
                              const next = on
                                ? draft.weekdays.filter((x) => x !== d.v)
                                : [...draft.weekdays, d.v]
                              return { ...draft, weekdays: next.length ? next : [d.v] }
                            })
                          }}
                        >
                          {d.label}
                        </button>
                      )
                    })}
                  </div>
                ) : null}
              </div>

              <div className="auto-custom-block">
                <label className="auto-custom-label">结束</label>
                <label className="auto-custom-radio">
                  <input
                    type="radio"
                    checked={customDraft.endNever}
                    onChange={() => setCustomDraft((d) => ({ ...d, endNever: true }))}
                  />
                  永不结束
                </label>
                <label className="auto-custom-radio">
                  <input
                    type="radio"
                    checked={!customDraft.endNever}
                    onChange={() => setCustomDraft((d) => ({ ...d, endNever: false }))}
                  />
                  指定日期
                </label>
                <input
                  className="auto-custom-date"
                  type="date"
                  disabled={customDraft.endNever}
                  value={customDraft.endDate}
                  onChange={(e) => setCustomDraft((d) => ({ ...d, endDate: e.target.value }))}
                />
              </div>
            </div>
          </Modal>

          <div className="auto-editor-field">
            <span className="auto-editor-label">指令</span>
            <div className="auto-editor-prompt-box" ref={toolbarRef}>
              <textarea
                className="auto-editor-prompt"
                rows={8}
                value={form.prompt}
                onChange={(e) => setForm((f) => ({ ...f, prompt: e.target.value }))}
                placeholder="例如：Review 最近 24 小时的提交，总结可能引入的 bug 和修复建议"
              />
              <div className="auto-editor-prompt-bar">
                <div className="auto-editor-prompt-bar-left">
                  <div className="auto-editor-dd">
                    <button
                      type="button"
                      className="auto-editor-chip"
                      onClick={() => {
                        setProjectOpen((v) => !v)
                        setConfirmOpen(false)
                        setModelOpen(false)
                        setEffortOpen(false)
                      }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <path d="M3 7h6l2 2h10v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
                      </svg>
                      {selectedProject}
                      <span className="auto-editor-caret">▾</span>
                    </button>
                    {projectOpen ? (
                      <div className="auto-editor-menu">
                        <button
                          type="button"
                          onClick={() => {
                            setForm((f) => ({ ...f, workspace_id: '' }))
                            setProjectOpen(false)
                          }}
                        >
                          不指定项目
                        </button>
                        {workspaces.map((w) => (
                          <button
                            key={w.id}
                            type="button"
                            onClick={() => {
                              setForm((f) => ({ ...f, workspace_id: w.id }))
                              setProjectOpen(false)
                            }}
                          >
                            {w.name}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  <div className="auto-editor-dd">
                    <button
                      type="button"
                      className="auto-editor-chip"
                      onClick={() => {
                        setConfirmOpen((v) => !v)
                        setProjectOpen(false)
                        setModelOpen(false)
                        setEffortOpen(false)
                      }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <path d="M8 11V8a4 4 0 1 1 8 0v3M6 11h12v9H6z" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      {confirmLabel}
                      <span className="auto-editor-caret">▾</span>
                    </button>
                    {confirmOpen ? (
                      <div className="auto-editor-menu">
                        {CONFIRM_MODES.map((m) => (
                          <button
                            key={m.id}
                            type="button"
                            onClick={() => {
                              setForm((f) => ({
                                ...f,
                                confirmMode: m.id,
                                delivery_mode: m.id === 'auto' ? 'new_session' : 'new_session',
                              }))
                              setConfirmOpen(false)
                            }}
                          >
                            {m.label}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>

                <div className="auto-editor-prompt-bar-right">
                  <div className="auto-editor-dd">
                    <button
                      type="button"
                      className="auto-editor-chip"
                      onClick={() => {
                        setModelOpen((v) => !v)
                        setProjectOpen(false)
                        setConfirmOpen(false)
                        setEffortOpen(false)
                      }}
                    >
                      {selectedModel}
                      <span className="auto-editor-caret">▾</span>
                    </button>
                    {modelOpen ? (
                      <div className="auto-editor-menu right">
                        <button
                          type="button"
                          onClick={() => {
                            setForm((f) => ({ ...f, model_profile_id: '' }))
                            setModelOpen(false)
                          }}
                        >
                          默认模型
                        </button>
                        {profiles.map((p) => (
                          <button
                            key={p.id}
                            type="button"
                            onClick={() => {
                              setForm((f) => ({ ...f, model_profile_id: p.id }))
                              setModelOpen(false)
                            }}
                          >
                            {p.name}
                          </button>
                        ))}
                        {experts.length ? (
                          <>
                            <div className="auto-editor-menu-sep">专家</div>
                            {experts.map((ex) => (
                              <button
                                key={ex.id}
                                type="button"
                                onClick={() => {
                                  setForm((f) => ({ ...f, expert_id: ex.id }))
                                  setModelOpen(false)
                                  showToast(`已绑定专家「${ex.name}」`)
                                }}
                              >
                                {ex.name}
                              </button>
                            ))}
                          </>
                        ) : null}
                      </div>
                    ) : null}
                  </div>

                  <div className="auto-editor-dd">
                    <button
                      type="button"
                      className="auto-editor-chip"
                      onClick={() => {
                        setEffortOpen((v) => !v)
                        setProjectOpen(false)
                        setConfirmOpen(false)
                        setModelOpen(false)
                      }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <circle cx="12" cy="12" r="3" />
                        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
                      </svg>
                      {effortLabel}
                      <span className="auto-editor-caret">▾</span>
                    </button>
                    {effortOpen ? (
                      <div className="auto-editor-menu right">
                        {EFFORT_LEVELS.map((lv) => (
                          <button
                            key={lv.id}
                            type="button"
                            onClick={() => {
                              setForm((f) => ({ ...f, effort: lv.id }))
                              setEffortOpen(false)
                            }}
                          >
                            {lv.label}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </div>

            {knowledge.length > 0 ? (
              <div className="auto-editor-kb">
                <span className="muted">资料库</span>
                <div className="auto-editor-kb-list">
                  {knowledge.map((k) => (
                    <label key={k.id} className="auto-editor-kb-item">
                      <input
                        type="checkbox"
                        checked={form.knowledge_ids.includes(k.id)}
                        onChange={() =>
                          setForm((f) => ({
                            ...f,
                            knowledge_ids: f.knowledge_ids.includes(k.id)
                              ? f.knowledge_ids.filter((x) => x !== k.id)
                              : [...f.knowledge_ids, k.id],
                          }))
                        }
                      />
                      {k.name || k.id.slice(0, 8)}
                    </label>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </section>
      )}
    </div>
  )
}
