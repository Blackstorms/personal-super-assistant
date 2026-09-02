/** Renderer 全局类型：preload 暴露的 window.api */
export {}

declare global {
  interface Window {
    api: {
      backendStatus: () => Promise<{ healthy: boolean; port: number; hasToken: boolean; error?: string }>
      backendRestart: () => Promise<{ ok: boolean }>
      setAuthToken: (token: string) => Promise<{ ok: boolean }>
      clearAuthToken: () => Promise<{ ok: boolean }>
      setThemeSource: (source: 'system' | 'light' | 'dark') => Promise<{ ok: boolean }>
      selectDirectory: () => Promise<string | null>
      selectFiles: () => Promise<string[] | null>
      request: (payload: {
        method: string
        path: string
        body?: unknown
      }) => Promise<{ status: number; json: unknown }>
      stream: (
        payload: { path: string; body: unknown; requestId: string },
        onEvent: (ev: { requestId: string; event: string; data: unknown }) => void,
      ) => Promise<unknown>
      streamAbort?: (requestId: string) => Promise<{ ok: boolean }>
    }
  }
}
