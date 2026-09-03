import { create } from 'zustand'

const TOKEN_KEY = 'psa_auth_token'
const USER_KEY = 'psa_username'

type AuthState = {
  token: string | null
  username: string | null
  hydrated: boolean
  hydrate: () => void
  setSession: (token: string, username: string) => Promise<void>
  logout: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  username: null,
  hydrated: false,
  hydrate: () => {
    const forceLogin =
      import.meta.env.VITE_PSA_SHOW_LOGIN === '1' || window.api?.forceLogin === true
    if (forceLogin) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      if (window.api?.clearAuthToken) void window.api.clearAuthToken()
      set({ token: null, username: null, hydrated: true })
      return
    }
    const token = localStorage.getItem(TOKEN_KEY)
    const username = localStorage.getItem(USER_KEY)
    set({ token, username, hydrated: true })
    if (token && window.api?.setAuthToken) {
      void window.api.setAuthToken(token)
    }
  },
  setSession: async (token, username) => {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, username)
    if (window.api?.setAuthToken) await window.api.setAuthToken(token)
    set({ token, username })
  },
  logout: async () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    if (window.api?.clearAuthToken) await window.api.clearAuthToken()
    set({ token: null, username: null })
  },
}))

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
