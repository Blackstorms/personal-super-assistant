/**
 * Preload：通过 contextBridge 暴露白名单 API，禁止直接访问 Node。
 */
import { contextBridge, ipcRenderer } from 'electron'

export type ApiRequest = {
  method: string
  path: string
  body?: unknown
  headers?: Record<string, string>
}

const api = {
  backendStatus: () => ipcRenderer.invoke('backend:status'),
  backendRestart: () => ipcRenderer.invoke('backend:restart'),
  // 本文件只打进安装包；开发态走 electron/dev-preload.cjs。每次打开都进登录页。
  forceLogin: true,
  setAuthToken: (token: string) => ipcRenderer.invoke('auth:setToken', token),
  clearAuthToken: () => ipcRenderer.invoke('auth:clearToken'),
  setThemeSource: (source: 'system' | 'light' | 'dark') => ipcRenderer.invoke('theme:setSource', source),
  selectDirectory: () => ipcRenderer.invoke('dialog:selectDirectory') as Promise<string | null>,
  selectFiles: () => ipcRenderer.invoke('dialog:selectFiles') as Promise<string[] | null>,
  openExternal: (url: string) => ipcRenderer.invoke('shell:openExternal', url) as Promise<{ ok: boolean }>,
  request: (payload: ApiRequest) => ipcRenderer.invoke('api:request', payload),
  stream: (
    payload: { path: string; body: unknown; requestId: string },
    onEvent: (ev: { requestId: string; event: string; data: unknown }) => void,
  ) => {
    const listener = (_: unknown, msg: { requestId: string; event: string; data: unknown }) => {
      if (msg.requestId === payload.requestId) onEvent(msg)
    }
    ipcRenderer.on('api:stream:event', listener)
    return ipcRenderer.invoke('api:stream', payload).finally(() => {
      ipcRenderer.removeListener('api:stream:event', listener)
    })
  },
  streamAbort: (requestId: string) => ipcRenderer.invoke('api:stream:abort', requestId),
}

contextBridge.exposeInMainWorld('api', api)

export type DesktopApi = typeof api
