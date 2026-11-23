import { AnimatePresence, motion } from 'motion/react'
import { EASE_OUT, Notice, Spinner, Tabs } from '../components/motion'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { useAuth } from '../auth'
import { ErrorBox, SkeletonRows } from '../components/States'
import { int, term, when } from '../format'
import { useApi } from '../hooks'
import { AttainmentTab } from './offering/AttainmentTab'
import { MarksTab } from './offering/MarksTab'
import { RootCauseTab } from './offering/RootCauseTab'
import { SurveyTab } from './offering/SurveyTab'
import type { AttainmentData, OfferingDetail } from './offering/types'
import { WhatIfTab } from './offering/WhatIfTab'

const TABS = { marks: 'Marks and locking', attainment: 'Attainment', cause: 'Root cause', whatif: 'What-if', survey: 'Survey' } as const
type Tab = keyof typeof TABS

export function Offering() {
  const { id } = useParams()
  const { user } = useAuth()
  const detail = useApi<OfferingDetail>(`/api/offerings/${id}`)
  const att = useApi<AttainmentData>(`/api/offerings/${id}/attainment`)
  // ?tab=survey (and google=connected / google_error=...) arrive back from the Google sign-in.
  const [query] = useState(() => new URLSearchParams(window.location.search))
  const [tab, setTab] = useState<Tab | null>(() => (query.get('tab') ?? '') in TABS ? query.get('tab') as Tab : null)
  const [computing, setComputing] = useState(false)
  const [notice, setNotice] = useState<string | null>(() =>
    query.get('google') === 'connected' ? 'Google account connected. You can create the survey form now.' : query.get('google_error'))
  const canEdit = user?.role === 'admin' || user?.role === 'faculty'

  const d = detail.data
  const computed = (att.data?.cos.length ?? 0) > 0
  const active: Tab = tab ?? (computed ? 'attainment' : 'marks')
  const allLocked = !!d && d.assessments.length > 0 && d.assessments.every((a) => a.locked)

  async function compute() {
    setComputing(true)
    setNotice(null)
    try {
      const r = await api<AttainmentData>(`/api/offerings/${id}/compute`, { method: 'POST' })
      att.setData(r)
      detail.reload()
      setTab('attainment')
      const below = r.cos.filter((c) => Number(c.final_level) < Number(c.target)).length
      setNotice(below ? `Computed. ${below} CO${below > 1 ? 's are' : ' is'} below target; an improvement action was added for each.` : 'Computed. Every CO meets its target.')
    } catch (e) {
      setNotice((e as ApiError).message)
    } finally {
      setComputing(false)
    }
  }

  if (detail.error) return <ErrorBox message={`Couldn't load this offering. ${detail.error}`} onRetry={detail.reload} />
  if (!d) return <SkeletonRows rows={6} height={24} />

  const lastComputed = att.data?.cos[0]?.computed_at ?? null
  return (
    <>
      <nav className="crumbs" aria-label="Breadcrumb"><Link to="/">Offerings</Link><span aria-hidden="true">/</span><span className="id">{d.code}</span></nav>
      <div className="object-head">
        <div className="code" aria-hidden="true">{d.code}</div>
        <div style={{ minWidth: 0 }}>
          <h1>{d.title}</h1>
          <div className="meta">{d.academic_year} · {term(d.term)} · Section {d.section} · {d.faculty} · <span className="num">{int(d.enrolled)}</span> students</div>
        </div>
        <div className="actions">
          {lastComputed && <span className="stamp" style={{ alignSelf: 'center' }}>Computed {when(lastComputed)}</span>}
          {canEdit && (
            <button className="btn primary" onClick={compute} disabled={computing || !allLocked}
                    title={allLocked ? undefined : 'Lock every assessment first'}>
              {computing ? <><Spinner />Computing…</> : computed ? 'Recompute attainment' : 'Compute attainment'}
            </button>
          )}
        </div>
      </div>
      <AnimatePresence>{notice && <Notice key={notice}>{notice}</Notice>}</AnimatePresence>

      <Tabs label="Offering" tabs={TABS} value={active} onChange={setTab} />

      <motion.div key={active} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: EASE_OUT }}>
      {active === 'marks' && <MarksTab offering={d} canEdit={canEdit} onChange={detail.reload} />}
      {active === 'attainment' && <AttainmentTab offering={d} att={att} canEdit={canEdit} onCompute={compute} allLocked={allLocked} />}
      {active === 'cause' && <RootCauseTab offering={d} att={att.data} canEdit={canEdit} onAction={att.reload} />}
      {active === 'whatif' && <WhatIfTab offering={d} computed={computed} canEdit={canEdit} />}
      {active === 'survey' && <SurveyTab offering={d} canEdit={canEdit} />}
      </motion.div>
    </>
  )
}
