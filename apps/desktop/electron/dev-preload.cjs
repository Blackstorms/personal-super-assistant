const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('api', {
  backendStatus: () => ipcRenderer.invoke('backend:status'),
  backendRestart: () => ipcRenderer.invoke('backend:restart'),
  setAuthToken: (value) => ipcRenderer.invoke('auth:setToken', value),
  clearAuthToken: () => ipcRenderer.invoke('auth:clearToken'),
  setThemeSource: (source) => ipcRenderer.invoke('theme:setSource', source),
  selectDirectory: () => ipcRenderer.invoke('dialog:selectDirectory'),
  selectFiles: () => ipcRenderer.invoke('dialog:selectFiles'),
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
