import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth'
import { Mark } from '../components/Shell'

export function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try { await login(username, password) } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="login">
      <form onSubmit={submit} aria-describedby={error ? 'login-error' : undefined}>
        <div className="brand" style={{ padding: 0 }}>
          <Mark />
          <div><b>CO-PO Attainment</b><span>Dept. of ISE · RVCE</span></div>
        </div>
        <div>
          <h1>Sign in</h1>
          <p className="muted" style={{ marginTop: 4 }}>Faculty use their staff ID, students their USN.</p>
        </div>
        <div className="field">
          <label htmlFor="u">Username</label>
          <input id="u" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="p">Password</label>
          <input id="p" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </div>
        {error && <div id="login-error" className="error-box" role="alert">{error}</div>}
        <button className="btn primary" type="submit" disabled={busy} style={{ height: 38 }}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </div>
  )
}
