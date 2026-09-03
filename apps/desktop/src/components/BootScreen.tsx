import { useEffect, useState } from 'react'
import AppBrand from './AppBrand'

function stageLabel(elapsedMs: number, failed: boolean): string {
  if (failed) return '本地引擎启动失败'
  if (elapsedMs < 2500) return '正在启动本地引擎…'
  if (elapsedMs < 8000) return '正在初始化数据…'
  if (elapsedMs < 20000) return '即将就绪…'
  return '仍在启动，请稍候…'
}

export default function BootScreen({
  progress,
  elapsedMs,
  error,
  failed,
  onRetry,
  retrying,
}: {
  progress: number
  elapsedMs: number
  error: string
  failed: boolean
  onRetry: () => void
  retrying: boolean
}) {
  const pct = Math.max(4, Math.min(100, progress))
  return (
    <div className="login-page">
      <div className="login-card boot-card">
        <AppBrand size="hero" showSub className="login-brand" healthy={!failed} />
        <p className="boot-status">{retrying ? '正在重新启动…' : stageLabel(elapsedMs, failed)}</p>
        <div className="boot-progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
          <div className={`boot-progress-bar${failed ? ' is-error' : ''}`} style={{ width: `${pct}%` }} />
        </div>
        <p className="muted boot-hint">{failed ? '可点击重试，或查看本机 127.0.0.1:18765' : `启动进度 ${Math.round(pct)}%`}</p>
        {failed && error ? <p className="login-warn">{error.slice(-220)}</p> : null}
        {failed ? (
          <button type="button" className="primary login-submit" disabled={retrying} onClick={onRetry}>
            {retrying ? '重试中…' : '重试'}
          </button>
        ) : null}
      </div>
    </div>
  )
}

/** 后端已就绪也至少展示启动页，避免窗口 show 时已经切走 */
const MIN_BOOT_VISIBLE_MS = 1800

export function useBackendBoot() {
  const [ready, setReady] = useState(false)
  const [progress, setProgress] = useState(6)
  const [elapsedMs, setElapsedMs] = useState(0)
  const [error, setError] = useState('')
  const [failed, setFailed] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let stopped = false
    let finishTimer: ReturnType<typeof setTimeout> | null = null
    const started = Date.now()
    setProgress(6)
    setFailed(false)
    setError('')

    const finish = (elapsed: number) => {
      setProgress(100)
      const wait = Math.max(0, MIN_BOOT_VISIBLE_MS - elapsed)
      if (wait === 0) {
        setReady(true)
        return
      }
      if (finishTimer) return
      finishTimer = setTimeout(() => {
        if (!stopped) setReady(true)
      }, wait)
    }

    const tick = async () => {
      if (stopped) return
      const elapsed = Date.now() - started
      setElapsedMs(elapsed)
      setProgress((prev) => {
        const target = Math.min(92, 6 + elapsed / 220)
        return Math.max(prev, target)
      })
      try {
        if (window.api?.backendStatus) {
          const s = await window.api.backendStatus()
          if (stopped) return
          if (s.healthy) {
            finish(elapsed)
            return
          }
          if (s.error) setError(s.error)
        } else {
          const r = await fetch('http://127.0.0.1:18765/api/v1/health')
          if (stopped) return
          if (r.ok) {
            finish(elapsed)
            return
          }
        }
      } catch {
        /* still booting */
      }
      if (elapsed > 50000) setFailed(true)
    }

    void tick()
    const t = setInterval(() => void tick(), 400)
    return () => {
      stopped = true
      clearInterval(t)
      if (finishTimer) clearTimeout(finishTimer)
    }
  }, [nonce])

  const retry = async () => {
    setRetrying(true)
    setFailed(false)
    setProgress(6)
    try {
      if (window.api?.backendRestart) await window.api.backendRestart()
    } catch {
      /* status poll will surface */
    } finally {
      setRetrying(false)
      setNonce((n) => n + 1)
    }
  }

  return { ready, progress, elapsedMs, error, failed, retrying, retry }
}
