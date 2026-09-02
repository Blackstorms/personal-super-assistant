import { useEffect, useState } from 'react'
import { apiRequest } from '../lib/api'
import { getThinkAutoCollapse, setThinkAutoCollapse } from '../lib/chatDisplay'
import { useAppStore } from '../stores/app'
import Modal from '../components/Modal'
import Toast from '../components/Toast'
import AppearanceSettings from '../components/AppearanceSettings'

type Profile = {
  id: string
  name: string
  base_url: string
  model: string
  temperature: number
  max_tokens: number
  is_default: boolean
  api_key_masked: string
}

type Health = {
  status: string
  version: string
  db_ok: boolean
  uptime_sec: number
  hermes?: {
    available?: boolean
    root?: string | null
    error?: string | null
    mcp_tools?: string[]
    missing_deps?: string[]
  }
}

const emptyForm = () => ({
  name: '',
  base_url: 'https://api.openai.com/v1',
  model: 'gpt-4o-mini',
  api_key: '',
  temperature: 0.7,
  max_tokens: 2048,
  is_default: false,
})

export default function SettingsPage() {
  const { backendHealthy, setBackendHealthy } = useAppStore()
  const [tab, setTab] = useState<'models' | 'appearance' | 'toolsets' | 'about'>('models')
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [form, setForm] = useState(emptyForm())
  const [editId, setEditId] = useState<string | null>(null)
  const [apiKeyMasked, setApiKeyMasked] = useState('')
  const [apiKeyTouched, setApiKeyTouched] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [toolsets, setToolsets] = useState<Array<{ id: string; name: string; enabled: boolean }>>([])
  const [toast, setToast] = useState<{ msg: string; type: 'info' | 'success' | 'error' } | null>(null)
  const [probingId, setProbingId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [thinkAutoCollapse, setThinkAutoCollapseState] = useState(true)

  const showToast = (msg: string, type: 'info' | 'success' | 'error' = 'info') => {
    setToast({ msg, type })
    window.setTimeout(() => setToast(null), 5000)
  }

  const loadProfiles = async () => {
    const data = await apiRequest<{ items: Profile[] }>('GET', '/api/v1/settings/llm/profiles')
    setProfiles(data.items)
  }

  const loadHealth = async () => {
    const h = await apiRequest<Health>('GET', '/api/v1/health')
    setHealth(h)
  }

  const loadToolsets = async () => {
    const data = await apiRequest<{ items: Array<{ id: string; name: string; enabled: boolean }> }>(
      'GET',
      '/api/v1/tools/toolsets',
    )
    setToolsets(data.items || [])
  }

  useEffect(() => {
    loadProfiles().catch((e) => showToast(String(e), 'error'))
    loadHealth().catch(() => setHealth(null))
    loadToolsets().catch(() => setToolsets([]))
    setThinkAutoCollapseState(getThinkAutoCollapse())
  }, [])

  const openCreate = () => {
    setEditId(null)
    setApiKeyMasked('')
    setApiKeyTouched(false)
    setForm(emptyForm())
    setModalOpen(true)
  }

  const openEdit = (p: Profile) => {
    setEditId(p.id)
    setApiKeyMasked(p.api_key_masked || '')
    setApiKeyTouched(false)
    setForm({
      name: p.name,
      base_url: p.base_url,
      model: p.model,
      api_key: '',
      temperature: p.temperature,
      max_tokens: p.max_tokens,
      is_default: p.is_default,
    })
    setModalOpen(true)
  }

  const closeModal = () => {
    setModalOpen(false)
    setEditId(null)
    setApiKeyMasked('')
    setApiKeyTouched(false)
    setForm(emptyForm())
  }

  const saveProfile = async () => {
    setSaving(true)
    try {
      if (editId) {
        const body: Record<string, unknown> = {
          name: form.name,
          base_url: form.base_url,
          model: form.model,
          temperature: form.temperature,
          max_tokens: form.max_tokens,
          is_default: form.is_default,
        }
        if (apiKeyTouched && form.api_key.trim()) body.api_key = form.api_key.trim()
        await apiRequest('PATCH', `/api/v1/settings/llm/profiles/${editId}`, body)
      } else {
        await apiRequest('POST', '/api/v1/settings/llm/profiles', {
          ...form,
          api_key: form.api_key || '',
        })
      }
      closeModal()
      showToast('已保存模型配置', 'success')
      await loadProfiles()
    } catch (e) {
      showToast(`保存失败：${e}`, 'error')
    } finally {
      setSaving(false)
    }
  }

  const probeProfile = async (p: Profile) => {
    setProbingId(p.id)
    try {
      const r = await apiRequest<{ ok: boolean; message: string; latency_ms: number }>(
        'POST',
        `/api/v1/settings/llm/profiles/${p.id}/test`,
      )
      showToast(
        `${p.name}：${r.ok ? '连通成功' : '探测失败'} · ${r.message} · ${r.latency_ms}ms`,
        r.ok ? 'success' : 'error',
      )
    } catch (e) {
      showToast(`${p.name} 探测失败：${e}`, 'error')
    } finally {
      setProbingId(null)
    }
  }

  const probeForm = async () => {
    setSaving(true)
    try {
      if (editId && !(apiKeyTouched && form.api_key.trim())) {
        const p = profiles.find((x) => x.id === editId)
        if (p) {
          setSaving(false)
          return probeProfile(p)
        }
      }
      const r = await apiRequest<{ ok: boolean; message: string; latency_ms: number }>(
        'POST',
        '/api/v1/settings/llm/test',
        {
          base_url: form.base_url,
          model: form.model,
          api_key: form.api_key || '',
        },
      )
      showToast(
        `${form.name || '当前配置'}：${r.ok ? '连通成功' : '探测失败'} · ${r.message} · ${r.latency_ms}ms`,
        r.ok ? 'success' : 'error',
      )
    } catch (e) {
      showToast(`探测失败：${e}`, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="stack">
      {toast && <Toast message={toast.msg} type={toast.type} onClose={() => setToast(null)} />}

      <h2>设置</h2>
      <div className="tabs">
        <button type="button" className={`tab ${tab === 'models' ? 'active' : ''}`} onClick={() => setTab('models')}>
          模型
        </button>
        <button
          type="button"
          className={`tab ${tab === 'appearance' ? 'active' : ''}`}
          onClick={() => setTab('appearance')}
        >
          外观
        </button>
        <button
          type="button"
          className={`tab ${tab === 'toolsets' ? 'active' : ''}`}
          onClick={() => {
            setTab('toolsets')
            void loadToolsets().catch(() => setToolsets([]))
          }}
        >
          Hermes 工具组
        </button>
        <button type="button" className={`tab ${tab === 'about' ? 'active' : ''}`} onClick={() => setTab('about')}>
          关于
        </button>
      </div>

      {tab === 'models' && (
        <div className="stack">
          <div className="row" style={{ justifyContent: 'flex-end' }}>
            <button type="button" className="primary" onClick={openCreate}>
              + 新增模型
            </button>
          </div>
          <div className="panel">
            {profiles.length === 0 ? (
              <p className="muted">还没有模型配置，点击「新增模型」添加。</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>名称</th>
                    <th>模型</th>
                    <th>默认</th>
                    <th>Key</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {profiles.map((p) => (
                    <tr key={p.id}>
                      <td>{p.name}</td>
                      <td>
                        {p.model}
                        <div className="muted" style={{ fontSize: 11 }}>
                          {p.base_url}
                        </div>
                      </td>
                      <td>{p.is_default ? '是' : ''}</td>
                      <td>{p.api_key_masked || '空'}</td>
                      <td className="row">
                        <button type="button" onClick={() => openEdit(p)}>
                          编辑
                        </button>
                        <button
                          type="button"
                          disabled={probingId === p.id}
                          onClick={() => void probeProfile(p)}
                        >
                          {probingId === p.id ? '探测中…' : '探测'}
                        </button>
                        <button
                          type="button"
                          className="danger"
                          onClick={async () => {
                            try {
                              await apiRequest('DELETE', `/api/v1/settings/llm/profiles/${p.id}`)
                              showToast(`已删除「${p.name}」`, 'success')
                              await loadProfiles()
                            } catch (e) {
                              showToast(String(e), 'error')
                            }
                          }}
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      <Modal
        open={modalOpen}
        title={editId ? '编辑模型' : '新增模型配置'}
        onClose={closeModal}
        footer={
          <>
            <button type="button" onClick={closeModal}>
              取消
            </button>
            <button type="button" disabled={saving || !!probingId} onClick={() => void probeForm()}>
              {probingId ? '探测中…' : '探测'}
            </button>
            <button type="button" className="primary" disabled={saving} onClick={() => void saveProfile()}>
              {saving ? '保存中…' : '保存'}
            </button>
          </>
        }
      >
        <div className="stack">
          <label className="muted">名称</label>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如 DeepSeek" />
          <label className="muted">Base URL</label>
          <input
            value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            placeholder="本地 LM Studio: http://127.0.0.1:1234/v1"
          />
          <label className="muted">Model</label>
          <input
            value={form.model}
            onChange={(e) => setForm({ ...form, model: e.target.value })}
            placeholder="LM Studio 填列表中的 id，如 qwen/qwen3.5-9b"
          />
          <label className="muted">API Key</label>
          <input
            type={apiKeyTouched || !editId ? 'password' : 'text'}
            value={
              editId && !apiKeyTouched
                ? apiKeyMasked
                : form.api_key
            }
            placeholder={
              editId
                ? apiKeyMasked
                  ? '留空则不修改'
                  : '未设置'
                : '可选（本地 Ollama 可空）'
            }
            onFocus={() => {
              if (editId && !apiKeyTouched) {
                setApiKeyTouched(true)
                setForm({ ...form, api_key: '' })
              }
            }}
            onChange={(e) => {
              setApiKeyTouched(true)
              setForm({ ...form, api_key: e.target.value })
            }}
          />
          <label className="row muted">
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
            />
            设为默认
          </label>
        </div>
      </Modal>

      {tab === 'appearance' && <AppearanceSettings />}

      {tab === 'toolsets' && (
        <div className="panel stack">
          <h3>Hermes Toolsets</h3>
          <p className="muted">
            控制会话默认暴露的 Hermes 工具组（终端/浏览器等默认关闭，可在此开启）。更改后新对话生效。
          </p>
          {toolsets.length === 0 ? (
            <div className="stack">
              <p className="muted">
                暂无工具组（Hermes 未就绪或未注册）。请确认仓库内存在{' '}
                <code>third_party/hermes-agent</code>（须含 <code>model_tools.py</code>
                ），然后重启后端。详见 docs/Hermes集成说明.md。
              </p>
              {health?.hermes && (
                <pre className="muted" style={{ fontSize: 12 }}>
                  {JSON.stringify(
                    {
                      available: health.hermes.available,
                      root: health.hermes.root,
                      error: health.hermes.error,
                      missing_deps: health.hermes.missing_deps,
                    },
                    null,
                    2,
                  )}
                </pre>
              )}
            </div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>工具组</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {toolsets.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <code>{t.name}</code>
                    </td>
                    <td>{t.enabled ? '已启用' : '已禁用'}</td>
                    <td>
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            await apiRequest('PUT', `/api/v1/tools/toolsets/${encodeURIComponent(t.id)}`, {
                              enabled: !t.enabled,
                            })
                            await loadToolsets()
                            showToast(`${t.name} → ${!t.enabled ? '启用' : '禁用'}`, 'success')
                          } catch (e) {
                            showToast(String(e), 'error')
                          }
                        }}
                      >
                        {t.enabled ? '禁用' : '启用'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'about' && (
        <div className="panel stack">
          <h3>对话体验</h3>
          <label className="row" style={{ gap: 8, alignItems: 'center' }}>
            <input
              type="checkbox"
              checked={thinkAutoCollapse}
              onChange={(e) => {
                const on = e.target.checked
                setThinkAutoCollapseState(on)
                setThinkAutoCollapse(on)
                showToast(on ? '思考过程将在完成后自动折叠' : '思考过程将保持展开', 'success')
              }}
            />
            <span>思考内容自动折叠（对齐 Cherry Studio）</span>
          </label>
          <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
            开启后，流式结束后约 1 秒自动收起「思考过程」；关闭则保持展开。标题会显示「思考中… / 已思考 Ns」。
          </p>
          <h3>健康与启动</h3>
          <p>
            后端状态：
            <span className={backendHealthy ? '' : 'error-line'}>{backendHealthy ? '已连接' : '未连接'}</span>
          </p>
          {health && (
            <pre className="muted">
              {JSON.stringify(
                {
                  status: health.status,
                  version: health.version,
                  db_ok: health.db_ok,
                  uptime_sec: health.uptime_sec,
                  hermes: health.hermes,
                },
                null,
                2,
              )}
            </pre>
          )}
          <p className="muted" style={{ fontSize: 12 }}>
            Hermes 源码已内置于 <code>third_party/hermes-agent</code>，健康检查中的{' '}
            <code>root</code> 字段即该路径。
          </p>
          <div className="row">
            <button
              onClick={async () => {
                await loadHealth()
                showToast('已刷新健康信息', 'success')
              }}
            >
              刷新健康检查
            </button>
            <button
              className="primary"
              onClick={async () => {
                try {
                  if (window.api?.backendRestart) {
                    await window.api.backendRestart()
                    const s = await window.api.backendStatus()
                    setBackendHealthy(s.healthy)
                  }
                  await loadHealth()
                  showToast('已请求重启后端', 'success')
                } catch (e) {
                  showToast(String(e), 'error')
                }
              }}
            >
              重启后端
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
