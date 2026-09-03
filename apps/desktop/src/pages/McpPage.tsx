import { useEffect, useMemo, useRef, useState } from 'react'
import { apiRequest } from '../lib/api'
import Modal from '../components/Modal'
import Toast from '../components/Toast'
import JsonCodeEditor from '../components/JsonCodeEditor'
import {
  MarketCard,
  MarketScopeTabs,
  MarketSection,
  groupByCategory,
  type MarketScope,
} from '../components/MarketShelf'

type Server = {
  id: string
  name: string
  transport: string
  command?: string | null
  args?: string[]
  env?: Record<string, string>
  url?: string | null
  enabled: boolean
  is_preset?: boolean
  description?: string
  category?: string
  badge?: string | null
  icon?: string
  tools_policy?: {
    include?: string[]
    exclude?: string[]
    resources?: boolean
    prompts?: boolean
  }
}
type DiscoveredTool = { name: string; description?: string; selected?: boolean }

const MANUAL_PLACEHOLDER = `// 示例:
// {
//   "mcpServers": {
//     "example-server": {
//       "command": "npx",
//       "args": [
//         "-y",
//         "mcp-server-example"
//       ]
//     }
//   }
// }`

const stripJsonComments = (text: string) =>
  text
    .replace(/\/\/.*$/gm, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .trim()

const parseJsonConfig = (text: string): unknown => {
  const cleaned = stripJsonComments(text)
  if (!cleaned) throw new Error('请输入 JSON 配置')
  return JSON.parse(cleaned)
}

function envFromMcpManual(text: string): Record<string, string> {
  try {
    const parsed = parseJsonConfig(text) as Record<string, unknown>
    let raw: Record<string, unknown>
    if (parsed.mcpServers && typeof parsed.mcpServers === 'object') {
      const servers = parsed.mcpServers as Record<string, unknown>
      const first = Object.values(servers)[0]
      raw = (first && typeof first === 'object' ? first : {}) as Record<string, unknown>
    } else {
      raw = parsed
    }
    const env = raw.env
    return env && typeof env === 'object' && !Array.isArray(env)
      ? (env as Record<string, string>)
      : {}
  } catch {
    return {}
  }
}

async function openExternalUrl(url: string) {
  if (window.api?.openExternal) {
    const r = await window.api.openExternal(url)
    if (r?.ok !== false) return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

function feishuUserTokenInfo(env: Record<string, string>) {
  const tok = (
    env.USER_ACCESS_TOKEN ||
    env.FEISHU_USER_ACCESS_TOKEN ||
    env.LARK_USER_ACCESS_TOKEN ||
    ''
  ).trim()
  if (!tok) return null
  const preview = tok.length > 10 ? `${tok.slice(0, 6)}…${tok.slice(-4)}` : '已配置'
  const hasRefresh = !!(env.REFRESH_USER_ACCESS_TOKEN || env.FEISHU_REFRESH_USER_ACCESS_TOKEN || '').trim()
  return { preview, hasRefresh }
}

const serverToMcpJson = (s: Server) =>
  JSON.stringify(
    {
      mcpServers: {
        [s.id.replace('preset-mcp-', '') || s.name]: {
          ...(s.url
            ? { url: s.url, transport: s.transport }
            : {
                command: s.command,
                args: s.args || [],
              }),
          env: s.env || {},
          ...(s.enabled ? {} : { disabled: true }),
        },
      },
    },
    null,
    2,
  )

export default function McpPage() {
  const [items, setItems] = useState<Server[]>([])
  const [info, setInfo] = useState('')
  const [tools, setTools] = useState<DiscoveredTool[]>([])

  const [manualOpen, setManualOpen] = useState(false)
  const [manualText, setManualText] = useState('')
  const [manualEditId, setManualEditId] = useState<string | null>(null)
  const [manualViewOnly, setManualViewOnly] = useState(false)
  const [manualSaving, setManualSaving] = useState(false)
  const [query, setQuery] = useState('')

  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null)
  const [scope, setScope] = useState<MarketScope>('public')
  const [menuId, setMenuId] = useState<string | null>(null)
  const [installingId, setInstallingId] = useState<string | null>(null)
  const [feishuOAuthState, setFeishuOAuthState] = useState<string | null>(null)
  const [feishuOAuthBusy, setFeishuOAuthBusy] = useState(false)
  const [feishuOAuthHint, setFeishuOAuthHint] = useState('')
  const [feishuAuthorizeUrl, setFeishuAuthorizeUrl] = useState('')
  const feishuOAuthAbortRef = useRef(false)

  const isFeishuServer = (id: string | null) =>
    !!id && (id === 'preset-mcp-feishu' || id.toLowerCase().includes('feishu'))

  const feishuTokenInfo = useMemo(() => {
    if (!manualEditId || !isFeishuServer(manualEditId)) return null
    return feishuUserTokenInfo(envFromMcpManual(manualText))
  }, [manualEditId, manualText])

  const startFeishuOAuth = async () => {
    if (!manualEditId || manualViewOnly) return
    feishuOAuthAbortRef.current = false
    setFeishuOAuthBusy(true)
    setFeishuOAuthHint('')
    setFeishuAuthorizeUrl('')
    setFeishuOAuthState(null)
    try {
      const env = envFromMcpManual(manualText)
      const r = await apiRequest<{
        state: string
        authorize_url: string
        hint?: string
        redirect_uri?: string
      }>('POST', `/api/v1/mcp/servers/${manualEditId}/feishu-oauth/start`, {
        app_id: String(env.APP_ID || env.FEISHU_APP_ID || '').trim() || undefined,
        app_secret: String(env.APP_SECRET || env.FEISHU_APP_SECRET || '').trim() || undefined,
      })
      if (feishuOAuthAbortRef.current) return
      setFeishuOAuthState(r.state)
      setFeishuAuthorizeUrl(r.authorize_url)
      setFeishuOAuthHint(r.hint || '')
      await openExternalUrl(r.authorize_url)
      const deadline = Date.now() + 180_000
      while (Date.now() < deadline && !feishuOAuthAbortRef.current) {
        await new Promise((resolve) => setTimeout(resolve, 400))
        if (feishuOAuthAbortRef.current) return
        const st = await apiRequest<{ status: string; saved_to_db?: boolean; message?: string }>(
          'GET',
          `/api/v1/mcp/servers/${manualEditId}/feishu-oauth/status?state=${encodeURIComponent(r.state)}`,
        )
        if (st.status === 'success' && st.saved_to_db) {
          showToast('飞书用户授权成功，USER_ACCESS_TOKEN 已写入')
          await load()
          const fresh = await apiRequest<{ items: Server[] }>('GET', '/api/v1/mcp/servers')
          const s = fresh.items.find((x) => x.id === manualEditId)
          if (s) setManualText(serverToMcpJson(s))
          setFeishuOAuthState(null)
          setFeishuAuthorizeUrl('')
          return
        }
        if (st.status === 'error') {
          throw new Error(st.message || '授权失败')
        }
      }
      if (feishuOAuthAbortRef.current) return
      throw new Error('授权超时，请重试')
    } catch (e) {
      if (!feishuOAuthAbortRef.current) showToast(String(e), 'error')
    } finally {
      setFeishuOAuthBusy(false)
    }
  }

  const cancelFeishuOAuth = () => {
    feishuOAuthAbortRef.current = true
    setFeishuOAuthBusy(false)
    setFeishuOAuthState(null)
    setFeishuAuthorizeUrl('')
  }

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 5000)
  }

  const load = async () => {
    const data = await apiRequest<{ items: Server[] }>('GET', '/api/v1/mcp/servers')
    setItems(data.items)
  }

  useEffect(() => {
    load().catch((e) => showToast(String(e), 'error'))
  }, [])

  const openManualCreate = () => {
    setManualEditId(null)
    setManualViewOnly(false)
    setManualText('')
    setManualOpen(true)
  }

  const openManualDetail = (s: Server, mode: 'edit' | 'view' = 'edit') => {
    setManualEditId(s.id)
    setManualViewOnly(mode === 'view')
    setManualText(serverToMcpJson(s))
    setManualOpen(true)
    setMenuId(null)
  }

  const closeManual = () => {
    setManualOpen(false)
    setManualEditId(null)
    setManualViewOnly(false)
    setManualText('')
    setFeishuOAuthState(null)
    setFeishuOAuthHint('')
  }

  const confirmManual = async () => {
    if (manualViewOnly) return
    setManualSaving(true)
    try {
      const parsed = parseJsonConfig(manualText)
      if (manualEditId) {
        const payload = importSingleFromConfig(parsed)
        await apiRequest('PATCH', `/api/v1/mcp/servers/${manualEditId}`, payload)
        showToast('连接器已更新')
      } else {
        const r = await apiRequest<{ count: number }>('POST', '/api/v1/mcp/servers/import', { config: parsed })
        showToast(`已添加 ${r.count} 个连接器`)
        setScope('personal')
      }
      closeManual()
      await load()
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setManualSaving(false)
    }
  }

  const importSingleFromConfig = (parsed: unknown) => {
    // 复用后端 import 解析逻辑：编辑时只允许一条
    if (typeof parsed !== 'object' || parsed === null) throw new Error('配置必须是 JSON 对象')
    const obj = parsed as Record<string, unknown>
    let raw: Record<string, unknown>
    let name = 'imported-mcp'
    if ('mcpServers' in obj && typeof obj.mcpServers === 'object' && obj.mcpServers) {
      const servers = obj.mcpServers as Record<string, unknown>
      const keys = Object.keys(servers)
      if (keys.length !== 1) throw new Error('编辑时请只保留一个 mcpServers 条目')
      name = keys[0]
      raw = { name, ...(servers[keys[0]] as Record<string, unknown>) }
    } else if ('command' in obj || 'url' in obj) {
      raw = obj
      name = String(obj.name || name)
    } else {
      throw new Error('无法识别的 JSON：需要 mcpServers 或 command/url')
    }
    const env =
      raw.env && typeof raw.env === 'object' && !Array.isArray(raw.env)
        ? (raw.env as Record<string, string>)
        : {}
    const enabled = raw.disabled !== true
    if (raw.url) {
      return {
        name: String(raw.name || name),
        transport: String(raw.transport || 'sse'),
        command: null,
        args: [],
        env,
        url: String(raw.url),
        enabled,
      }
    }
    const args = raw.args
    return {
      name: String(raw.name || name),
      transport: String(raw.transport || 'stdio'),
      command: String(raw.command || ''),
      args: Array.isArray(args) ? args.map(String) : typeof args === 'string' ? args.split(/\s+/).filter(Boolean) : [],
      env,
      url: null,
      enabled,
    }
  }

  const envHint = (s: Server) => {
    const env = s.env || {}
    const keys = Object.keys(env).filter((k) => env[k])
    if (keys.length) return keys.join(', ')
    const emptyKeys = Object.keys(env)
    return emptyKeys.length ? `待配置：${emptyKeys.join(', ')}` : '—'
  }

  const installServer = async (s: Server) => {
    setInstallingId(s.id)
    try {
      await apiRequest('PATCH', `/api/v1/mcp/servers/${s.id}`, { enabled: true })
      showToast(`已安装并启用「${s.name}」，请按需填写凭证`)
      setScope('personal')
      await load()
    } catch (e) {
      showToast(String(e), 'error')
    } finally {
      setInstallingId(null)
    }
  }

  const disableServer = async (s: Server) => {
    try {
      await apiRequest('PATCH', `/api/v1/mcp/servers/${s.id}`, { enabled: false })
      showToast(`已停用「${s.name}」`)
      setMenuId(null)
      await load()
    } catch (e) {
      showToast(String(e), 'error')
    }
  }

  const publicItems = useMemo(
    () => items.filter((s) => s.is_preset && !s.enabled),
    [items],
  )
  const personalItems = useMemo(
    () => items.filter((s) => s.enabled || !s.is_preset),
    [items],
  )
  const filteredItems = useMemo(() => {
    const base = scope === 'public' ? publicItems : personalItems
    const q = query.trim().toLowerCase()
    if (!q) return base
    return base.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.id.toLowerCase().includes(q) ||
        (s.description || '').toLowerCase().includes(q) ||
        (s.category || '').toLowerCase().includes(q),
    )
  }, [scope, publicItems, personalItems, query])
  const sections = useMemo(
    () => groupByCategory(filteredItems, scope === 'public' ? '其他' : '已安装'),
    [filteredItems, scope],
  )

  return (
    <div className="market-page mcp-page">
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}

      <MarketScopeTabs
        scope={scope}
        onChange={setScope}
        trailing={
          <div className="row">
            <input
              style={{ width: 200 }}
              value={query}
              placeholder="搜索连接器…"
              onChange={(e) => setQuery(e.target.value)}
            />
            <button type="button" className="primary" onClick={openManualCreate}>
              新增MCP
            </button>
          </div>
        }
      />

      {sections.length === 0 || sections.every((s) => s.items.length === 0) ? (
        <div className="market-empty">
          {query.trim()
            ? '没有匹配的连接器，换个关键词试试。'
            : scope === 'public'
              ? '公开预置均已安装，可在「个人」中管理，或手动添加连接器。'
              : '还没有已启用的连接器，可在「公开」中安装预置。'}
        </div>
      ) : (
        sections.map((sec) => (
          <MarketSection key={sec.category} title={sec.category}>
            {sec.items.map((s) => {
              const publicOnly = scope === 'public'
              return (
              <MarketCard
                key={s.id}
                item={{
                  id: s.id,
                  name: s.name,
                  description: s.description || `${s.transport} · ${s.url || s.command || ''}`.trim(),
                  category: s.category,
                  badge: s.badge,
                  icon: s.icon,
                  installed: scope === 'personal' || s.enabled,
                }}
                installing={installingId === s.id}
                onInstall={publicOnly ? () => void installServer(s) : undefined}
                onClick={() => openManualDetail(s, publicOnly ? 'view' : 'edit')}
                menu={
                  <div className="market-menu-wrap">
                    <button
                      type="button"
                      className="market-menu-btn"
                      onClick={() => setMenuId((id) => (id === s.id ? null : s.id))}
                    >
                      ···
                    </button>
                    {menuId === s.id ? (
                      <div className="market-menu">
                        {publicOnly ? (
                          <button type="button" onClick={() => openManualDetail(s, 'view')}>
                            查看
                          </button>
                        ) : (
                          <>
                            <button type="button" onClick={() => openManualDetail(s, 'edit')}>
                              编辑
                            </button>
                            <button
                              type="button"
                              onClick={async () => {
                                try {
                                  const r = await apiRequest<{
                                    ok: boolean
                                    message: string
                                    latency_ms?: number
                                  }>('POST', `/api/v1/mcp/servers/${s.id}/test`)
                                  setInfo(
                                    r.ok
                                      ? `✓ ${s.name} 连通 · ${r.latency_ms ?? 0} ms · ${r.message}`
                                      : `✗ ${s.name} 失败 · ${r.message}`,
                                  )
                                  setMenuId(null)
                                } catch (e) {
                                  setInfo(String(e))
                                }
                              }}
                            >
                              测试
                            </button>
                            <button
                              type="button"
                              onClick={async () => {
                                try {
                                  const r = await apiRequest<{ tools: DiscoveredTool[] }>(
                                    'POST',
                                    `/api/v1/mcp/servers/${s.id}/discover`,
                                  )
                                  const discovered = (r.tools || []).map((t) => ({ ...t, selected: true }))
                                  setTools(discovered)
                                  setInfo(
                                    discovered.length
                                      ? `${s.name}：Discover 到 ${discovered.length} 个工具`
                                      : `${s.name}：未发现工具`,
                                  )
                                  ;(window as unknown as { __mcpFilterSid?: string }).__mcpFilterSid = s.id
                                  setMenuId(null)
                                } catch (e) {
                                  setInfo(String(e))
                                }
                              }}
                            >
                              Discover
                            </button>
                            {s.enabled ? (
                              <button type="button" onClick={() => void disableServer(s)}>
                                停用
                              </button>
                            ) : null}
                            {!s.is_preset ? (
                              <button
                                type="button"
                                className="danger"
                                onClick={async () => {
                                  await apiRequest('DELETE', `/api/v1/mcp/servers/${s.id}`)
                                  setTools([])
                                  setMenuId(null)
                                  await load()
                                }}
                              >
                                删除
                              </button>
                            ) : null}
                          </>
                        )}
                      </div>
                    ) : null}
                  </div>
                }
              />
              )
            })}
          </MarketSection>
        ))
      )}

      <p className="market-foot">
        公开预置仅可查看与安装；安装后请到个人区填写凭证（
        {items.filter((s) => s.is_preset).slice(0, 1).map(envHint).join('') || '见配置'}
        ）。MCP 为智能体提供外部工具能力。
      </p>

      {tools.length > 0 && (
        <div className="panel stack">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h3 style={{ margin: 0 }}>已发现工具（勾选后保存过滤）</h3>
            <button
              type="button"
              className="primary"
              onClick={async () => {
                const sid = (window as unknown as { __mcpFilterSid?: string }).__mcpFilterSid
                if (!sid) {
                  showToast('请先对某个 Server 执行 Discover', 'error')
                  return
                }
                const include = tools.filter((t) => t.selected !== false).map((t) => t.name)
                try {
                  await apiRequest('PUT', `/api/v1/mcp/servers/${sid}/tools-policy`, {
                    tools_policy: { include },
                  })
                  showToast(`已保存工具过滤（${include.length} 个）`)
                  await apiRequest('POST', '/api/v1/mcp/reload')
                } catch (e) {
                  showToast(String(e), 'error')
                }
              }}
            >
              保存过滤并重载
            </button>
          </div>
          <ul>
            {tools.map((t, idx) => (
              <li key={t.name}>
                <label className="row" style={{ gap: 8, alignItems: 'flex-start' }}>
                  <input
                    type="checkbox"
                    checked={t.selected !== false}
                    onChange={(e) => {
                      const next = [...tools]
                      next[idx] = { ...t, selected: e.target.checked }
                      setTools(next)
                    }}
                  />
                  <span>
                    <code>{t.name}</code> {t.description}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}
      {info && <pre className="panel muted">{info}</pre>}

      <Modal
        open={manualOpen}
        wide
        title={manualViewOnly ? '查看连接器' : manualEditId ? '编辑连接器' : '手动配置'}
        onClose={closeManual}
        footer={
          manualViewOnly ? (
            <button type="button" className="primary" onClick={closeManual}>
              关闭
            </button>
          ) : (
            <>
              <button type="button" onClick={closeManual}>
                取消
              </button>
              <button type="button" className="primary" disabled={manualSaving} onClick={() => void confirmManual()}>
                {manualSaving ? '处理中…' : '确认'}
              </button>
            </>
          )
        }
      >
        <div className="stack">
          {!manualEditId && !manualViewOnly && (
            <p className="muted" style={{ margin: 0 }}>
              请从 MCP Servers 的介绍页面复制配置 JSON（优先使用 NPX 或 UVX 配置），并粘贴到输入框中。
            </p>
          )}
          {isFeishuServer(manualEditId) && !manualViewOnly && (
            <div className="panel stack feishu-oauth-panel" style={{ gap: 8 }}>
              <strong>飞书用户授权（OAuth）</strong>
              {feishuOAuthBusy ? (
                <>
                  <p className="muted" style={{ margin: 0, fontSize: 13 }}>
                    {feishuOAuthState
                      ? '已在系统浏览器打开授权页，请完成登录后回到这里。'
                      : '正在打开系统浏览器…'}
                  </p>
                  {feishuAuthorizeUrl ? (
                    <button type="button" onClick={() => void openExternalUrl(feishuAuthorizeUrl)}>
                      浏览器未打开？再打开一次
                    </button>
                  ) : null}
                  <div className="row" style={{ gap: 8 }}>
                    <button type="button" className="primary" disabled>
                      等待浏览器授权…
                    </button>
                    <button type="button" onClick={cancelFeishuOAuth}>
                      取消
                    </button>
                  </div>
                </>
              ) : feishuTokenInfo ? (
                <div className="feishu-oauth-success">
                  <div className="feishu-oauth-success-title">✅ 授权成功</div>
                  <p className="feishu-oauth-success-copy">
                    USER_ACCESS_TOKEN 已写入连接器
                    {feishuTokenInfo.preview ? `（${feishuTokenInfo.preview}）` : ''}
                    {feishuTokenInfo.hasRefresh ? '，已保存 refresh_token，到期可自动续期。' : '。'}
                  </p>
                  <button type="button" onClick={() => void startFeishuOAuth()}>
                    重新授权
                  </button>
                </div>
              ) : (
                <>
                  <p className="muted" style={{ margin: 0, fontSize: 13 }}>
                    填写 APP_ID / APP_SECRET 后，点击下方按钮在浏览器完成授权，系统会自动写入
                    USER_ACCESS_TOKEN（与 lark-mcp login 同源）。创建任务时可指定负责人并出现在你的飞书任务中心。
                  </p>
                  {feishuOAuthHint ? (
                    <p className="muted" style={{ margin: 0, fontSize: 12 }}>
                      {feishuOAuthHint}
                    </p>
                  ) : (
                    <p className="muted" style={{ margin: 0, fontSize: 12 }}>
                      开放平台需配置重定向 URL（与 lark-mcp 官方一致）：{' '}
                      <code>http://localhost:3000/callback</code>
                    </p>
                  )}
                  <button type="button" className="primary" onClick={() => void startFeishuOAuth()}>
                    浏览器授权获取 USER_ACCESS_TOKEN
                  </button>
                </>
              )}
            </div>
          )}
          <JsonCodeEditor
            value={manualText}
            onChange={setManualText}
            rows={manualEditId || manualViewOnly ? 14 : 12}
            readOnly={manualViewOnly}
            placeholder={manualEditId || manualViewOnly ? undefined : MANUAL_PLACEHOLDER}
          />
          {!manualEditId && !manualViewOnly && (
            <p className="mcp-safety-note">
              <span aria-hidden="true">⚠</span> 配置前请确认来源，甄别风险
            </p>
          )}
        </div>
      </Modal>
    </div>
  )
}
