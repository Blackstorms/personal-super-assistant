const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('api', {
  backendStatus: () => ipcRenderer.invoke('backend:status'),
  backendRestart: () => ipcRenderer.invoke('backend:restart'),
  forceLogin: process.env.PSA_SHOW_LOGIN === '1' || process.env.VITE_PSA_SHOW_LOGIN === '1',
  setAuthToken: (value) => ipcRenderer.invoke('auth:setToken', value),
  clearAuthToken: () => ipcRenderer.invoke('auth:clearToken'),
  setThemeSource: (source) => ipcRenderer.invoke('theme:setSource', source),
  selectDirectory: () => ipcRenderer.invoke('dialog:selectDirectory'),
  selectFiles: () => ipcRenderer.invoke('dialog:selectFiles'),
  openExternal: (url) => ipcRenderer.invoke('shell:openExternal', url),
  request: (payload) => ipcRenderer.invoke('api:request', payload),
  stream: (payload, onEvent) => {
    const listener = (_e, msg) => {
      if (msg.requestId === payload.requestId) onEvent(msg)
    }
    ipcRenderer.on('api:stream:event', listener)
    return ipcRenderer.invoke('api:stream', payload).finally(() => {
      ipcRenderer.removeListener('api:stream:event', listener)
    })
  },
  streamAbort: (requestId) => ipcRenderer.invoke('api:stream:abort', requestId),
})
