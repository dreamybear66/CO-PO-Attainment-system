import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, getToken, setToken, setUnauthorizedHandler } from './api'

export type Role = 'admin' | 'faculty' | 'coordinator' | 'student'
export type User = { user_id: number; username: string; role: Role; faculty_id: number | null; usn: string | null }

type AuthState = {
  user: User | null
  ready: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  const logout = useCallback(() => { setToken(null); setUser(null) }, [])

  useEffect(() => {
    setUnauthorizedHandler(logout)
    // Inspection builds only (vite build --mode inspect): take a token from #token=… so the screen
    // inspector can open signed-in screens. The shipped build does not contain this branch.
    if (import.meta.env.VITE_INSPECT === '1') {
      const m = window.location.hash.match(/token=([^&]+)/)
      if (m) { setToken(decodeURIComponent(m[1])); history.replaceState(null, '', window.location.pathname) }
    }
    if (!getToken()) { setReady(true); return }
    api<User>('/api/auth/me').then(setUser).catch(() => setToken(null)).finally(() => setReady(true))
  }, [logout])

  const login = useCallback(async (username: string, password: string) => {
    const r = await api<{ token: string; user: User }>('/api/auth/login', { body: { username, password } })
    setToken(r.token)
    setUser(r.user)
  }, [])

  return <AuthContext.Provider value={{ user, ready, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}

export const ROLE_NAMES: Record<Role, string> = {
  admin: 'Head of department', faculty: 'Course faculty', coordinator: 'Accreditation coordinator', student: 'Student',
}
