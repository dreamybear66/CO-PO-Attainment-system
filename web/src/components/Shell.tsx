import { useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { ROLE_NAMES, useAuth, type Role } from '../auth'
import { useApi } from '../hooks'

const icon = {
  offerings: <path d="M3 4.5h10M3 8h10M3 11.5h6" />,
  trends: <path d="M2.5 12.5 6 8.5l3 2.5 4.5-6" />,
  actions: <path d="M3.5 8.5 6.5 11.5 12.5 4.5" />,
  settings: <><circle cx="8" cy="8" r="2.2" /><path d="M8 2v1.6M8 12.4V14M2 8h1.6M12.4 8H14M3.8 3.8l1.1 1.1M11.1 11.1l1.1 1.1M3.8 12.2l1.1-1.1M11.1 4.9l1.1-1.1" /></>,
  scores: <path d="M3 13V8M8 13V4M13 13V9.5" />,
  surveys: <><rect x="3" y="2.5" width="10" height="11" rx="1.5" /><path d="M5.5 6h5M5.5 9h3.5" /></>,
  menu: <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />,
}
const Icon = ({ d }: { d: ReactNode }) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
)

export function Mark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect width="24" height="24" rx="6" fill="var(--accent)" />
      <circle cx="7.5" cy="8" r="2.5" fill="#fff" /><circle cx="7.5" cy="16" r="2.5" fill="#fff" />
      <circle cx="16.5" cy="12" r="3" fill="none" stroke="#fff" strokeWidth="2" />
      <path d="M9.8 8.9 13.7 11M9.8 15.1 13.7 13" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

type Nav = { to: string; label: string; d: ReactNode; roles: Role[]; count?: number | null }

export function Shell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  const pending = useApi<unknown[]>(user?.role === 'admin' ? '/api/unlock-requests' : null)
  if (!user) return null

  const nav: Nav[] = [
    { to: '/', label: 'Offerings', d: icon.offerings, roles: ['admin', 'faculty', 'coordinator'] },
    { to: '/trends', label: 'Trends', d: icon.trends, roles: ['admin', 'faculty', 'coordinator'] },
    { to: '/actions', label: 'Improvement actions', d: icon.actions, roles: ['admin', 'faculty', 'coordinator'] },
    { to: '/me', label: 'My CO scores', d: icon.scores, roles: ['student'] },
    { to: '/me/surveys', label: 'Course-exit surveys', d: icon.surveys, roles: ['student'] },
  ]
  const bottom: Nav[] = [
    { to: '/settings', label: 'Rules and audit', d: icon.settings, roles: ['admin', 'coordinator'],
      count: pending.data?.length || null },
  ]
  const item = (n: Nav) => n.roles.includes(user.role) && (
    <NavLink key={n.to} to={n.to} end className="nav-item" onClick={() => setOpen(false)}>
      <Icon d={n.d} />{n.label}
      {n.count ? <span className="count num" aria-label={`${n.count} unlock requests waiting`}>{n.count}</span> : null}
    </NavLink>
  )
  const initials = user.username.slice(0, 2).toUpperCase()

  return (
    <div className="app">
      <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Main">
        <div className="brand">
          <Mark />
          <div><b>CO-PO Attainment</b><span>Dept. of ISE · RVCE</span></div>
        </div>
        <button className="btn ghost menu-toggle" style={{ justifySelf: 'end' }} onClick={() => setOpen(false)}>Close</button>
        {nav.map(item)}
        <div className="bottom">{bottom.map(item)}</div>
      </aside>
      <header className="topbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button className="btn ghost menu-toggle" aria-label="Open menu" onClick={() => setOpen(true)}><Icon d={icon.menu} /></button>
          <span className="phone-brand"><Mark />CO-PO Attainment</span>
          <span className="scope">B.E. Information Science and Engineering · {loc.pathname.startsWith('/me') ? 'Student view' : 'Outcome-based education'}</span>
        </div>
        <div className="who">
          <span className="avatar" aria-hidden="true">{initials}</span>
          <span className="hide-phone"><span className="id">{user.username}</span> <span className="muted">· {ROLE_NAMES[user.role]}</span></span>
          <button className="btn ghost small" onClick={logout}>Sign out</button>
        </div>
      </header>
      <main className="sheet">{children}</main>
    </div>
  )
}
