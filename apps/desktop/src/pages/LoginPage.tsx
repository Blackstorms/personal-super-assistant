import { useState } from 'react'
import AppBrand from '../components/AppBrand'
import { loginRequest } from '../lib/api'
import { useAuthStore } from '../stores/auth'

export default function LoginPage() {
  const setSession = useAuthStore((s) => s.setSession)
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const r = await loginRequest(username.trim(), password)
      await setSession(r.token, r.username)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <AppBrand size="hero" showSub className="login-brand" healthy />

        <form className="login-form stack" onSubmit={(e) => void submit(e)}>
          <label className="muted">用户名</label>
          <input
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="用户名"
            autoComplete="username"
          />
          <label className="muted">密码</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="密码"
            autoComplete="current-password"
          />
          {error && <p className="login-error">{error}</p>}
          <button type="submit" className="primary login-submit" disabled={loading}>
            {loading ? '登录中…' : '登录'}
          </button>
        </form>

        <p className="muted login-hint">默认账号：admin / admin</p>
      </div>
    </div>
  )
}
