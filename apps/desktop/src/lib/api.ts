/**
 * API 客户端封装。
 * 浏览器开发态可直连后端；Electron 态走 IPC 代理。
 */
import { getStoredToken, useAuthStore } from '../stores/auth'

const DEV_BASE = 'http://127.0.0.1:18765'

function parseApiError(raw: unknown): string {
  if (typeof raw === 'string') {
    try {
      const j = JSON.parse(raw) as { detail?: { message?: string } | string }
      if (typeof j.detail === 'string') return j.detail
      if (j.detail && typeof j.detail === 'object' && j.detail.message) return j.detail.message
    } catch {
      return raw
    }
    return raw
  }
  if (raw && typeof raw === 'object') {
    const j = raw as { detail?: { message?: string } | string; message?: string }
    if (typeof j.detail === 'string') return j.detail
    if (j.detail && typeof j.detail === 'object' && j.detail.message) return j.detail.message
    if (j.message) return j.message
  }
  return '请求失败'
}

async function getToken(): Promise<string> {
  const token = useAuthStore.getState().token || getStoredToken()
  if (!token) throw new Error('未登录')
  return token
}

export async function loginRequest(username: string, password: string): Promise<{ token: string; username: string }> {
  if (window.api?.request) {
    const res = await window.api.request({
      method: 'POST',
      path: '/api/v1/auth/login',
      body: { username, password },
    })
    if (res.status >= 400) throw new Error(parseApiError(res.json))
    return res.json as { token: string; username: string }
  }
  const res = await fetch(`${DEV_BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error(parseApiError(await res.text()))
  return (await res.json()) as { token: string; username: string }
}

export async function apiRequest<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  if (window.api?.request) {
    const res = await window.api.request({ method, path, body })
    if (res.status === 401) {
      await useAuthStore.getState().logout()
      throw new Error('登录已失效，请重新登录')
    }
    if (res.status >= 400) throw new Error(parseApiError(res.json))
    return res.json as T
  }
  const token = await getToken()
  const res = await fetch(`${DEV_BASE}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401) {
    await useAuthStore.getState().logout()
    throw new Error('登录已失效，请重新登录')
  }
  if (!res.ok) throw new Error(parseApiError(await res.text()))
  if (res.headers.get('content-type')?.includes('text/')) return (await res.text()) as T
  return (await res.json()) as T
}

export class StreamAbortedError extends Error {
  constructor() {
    super('stream aborted')
    this.name = 'StreamAbortedError'
  }
}

export async function apiStream(
  path: string,
  body: unknown,
  onEvent: (event: string, data: unknown) => void,
  opts?: { signal?: AbortSignal },
): Promise<void> {
  const requestId = crypto.randomUUID()
  const signal = opts?.signal

  const dispatchPart = (part: string) => {
    let ev = 'message'
    let data = ''
    for (const line of part.split('\n')) {
      if (line.startsWith('event:')) ev = line.slice(6).trim()
      if (line.startsWith('data:')) data += line.slice(5).trim()
    }
    if (!data) return
    try {
      onEvent(ev, JSON.parse(data))
    } catch {
      onEvent(ev, data)
    }
  }

  if (signal?.aborted) throw new StreamAbortedError()

  if (window.api?.stream) {
    const onAbort = () => {
      void window.api?.streamAbort?.(requestId)
    }
    signal?.addEventListener('abort', onAbort)
    try {
      await window.api.stream({ path, body, requestId }, (msg) => {
        if (signal?.aborted) return
        onEvent(msg.event, msg.data)
      })
      if (signal?.aborted) throw new StreamAbortedError()
    } finally {
      signal?.removeEventListener('abort', onAbort)
    }
    return
  }

  const token = await getToken()
  const res = await fetch(`${DEV_BASE}${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
    signal,
  })
  if (res.status === 401) {
    await useAuthStore.getState().logout()
    throw new Error('登录已失效，请重新登录')
  }
  if (!res.body) throw new Error('no stream body')
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      if (signal?.aborted) {
        await reader.cancel().catch(() => undefined)
        throw new StreamAbortedError()
      }
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) dispatchPart(part)
    }
    buffer += decoder.decode()
    if (buffer.trim()) dispatchPart(buffer)
  } catch (e) {
    if (signal?.aborted || (e instanceof DOMException && e.name === 'AbortError')) {
      throw new StreamAbortedError()
    }
    throw e
  }
}
