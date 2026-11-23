import { useEffect, useId, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Mark } from '../components/Shell'
import '../landing.css'

/* Public landing page. Direction (taste-skill, seed 351696131): one motif. The motif is the
   attainment staircase: levels 0-3, reached at 50, 60 and 70 % of students. It is the hero shape,
   the button corner, the list bullet, the picture frame, the band and the footer wordmark. */

// The rules in force since 1 Aug 2024 (attainment_config). The calculator uses exactly these.
const L1 = 50, L2 = 60, L3 = 70, DIRECT = 80, SURVEY = 20
const toLevel = (pct: number) => (pct >= L3 ? 3 : pct >= L2 ? 2 : pct >= L1 ? 1 : 0)

/** Staircase silhouette: three treads rising left to right. */
function Stairs({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 300 300" preserveAspectRatio="none" aria-hidden="true">
      <path d="M0 300V200H100V100H200V0H300V300Z" />
    </svg>
  )
}

function Bullet() {
  return <svg className="lp-bullet" viewBox="0 0 12 12" aria-hidden="true"><path d="M0 12V8h4V4h4V0h4v12Z" /></svg>
}

/** Adds .is-in to [data-reveal] blocks as they enter; children stagger by --i. */
function useReveal(root: React.RefObject<HTMLElement>) {
  useEffect(() => {
    const el = root.current
    if (!el) return
    const blocks = [...el.querySelectorAll<HTMLElement>('[data-reveal]')]
    if (!('IntersectionObserver' in window)) { blocks.forEach((b) => b.classList.add('is-in')); return }
    el.classList.add('lp-anim')
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target) } })
    }, { rootMargin: '0px 0px -12% 0px' })
    blocks.forEach((b) => io.observe(b))
    return () => io.disconnect()
  }, [root])
}

const STEPS = [
  {
    name: 'Student CO score',
    text: 'For each component, the marks on the questions that test the CO, over their maximum. Components then weigh CIE theory 20, quiz 10, experiential learning 20 and SEE 50, counting only those that test the CO. An absent student is AB and scores 0.',
    pic: { src: '/landing/marks.webp', w: 1600, h: 736, alt: 'Assessments table for IS243: six assessments, every mark entered, all locked' },
  },
  {
    name: 'Direct level',
    text: `The share of students whose CO score reaches the 60 % target, mapped to a level: 3 at ${L3} %, 2 at ${L2} %, 1 at ${L1} %, otherwise 0.`,
    pic: { src: '/landing/ladder.webp', w: 1058, h: 530, alt: 'CO attainment ladder for IS243 with the 50, 60 and 70 % thresholds marked on each bar' },
  },
  {
    name: 'Survey level',
    text: 'The share of course-exit survey ratings of 4 or 5 for the CO, through the same thresholds. Responses live in MongoDB; a nightly ETL job brings the level into PostgreSQL. No survey means 0.',
    pic: { src: '/landing/evidence.webp', w: 920, h: 504, alt: 'Direct and survey evidence table: students at target, respondents and favourable share per CO' },
  },
  {
    name: 'Final CO level',
    text: `(${DIRECT} × direct + ${SURVEY} × survey) / 100. The worked example in the requirements gives CO1 3.00, CO2 2.20 and CO3 0.40, and the test suite checks those numbers on every run.`,
  },
  {
    name: 'PO attainment',
    text: 'Σ(strength × final CO level) / Σ strength over the CO-PO map. The worked example gives PO1 2.30 and PO2 1.48. The programme PO is the plain average of the offering values.',
    pic: { src: '/landing/matrix.webp', w: 1600, h: 544, alt: 'CO-PO matrix for IS243 with mapping strengths 1 to 3 and the PO values beneath' },
  },
]

const SCREENS = [
  {
    name: 'Root cause', src: '/landing/rootcause.webp', w: 1600, h: 411, stage: 'var(--lp-field-1)',
    alt: 'Root cause for IS243 CO4: IS231 CO2 ranked as likely cause with r 0.81; IS111 CO5 a weak link at r −0.06',
    fact: 'DBMS CO4 fell to 0.40 in 2024-25. Walking the CO graph back, the system ranks Data Structures CO2 first (r = 0.81) and clears the declared decoy, Programming in C CO5 (r = −0.06).',
  },
  {
    name: 'Trends', src: '/landing/trend.webp', w: 1056, h: 468, stage: 'var(--lp-field-3)',
    alt: 'Line chart of IS243 CO4 final level by year, dipping below the 2.00 target in 2024-25',
    fact: 'The same CO across four years: 2.85, then 0.90 for the planted weak batch, then back to 2.00 the year after.',
  },
  {
    name: 'Improvement actions', src: '/landing/actions.webp', w: 650, h: 541, stage: 'var(--lp-field-2)',
    alt: 'Improvement actions list: four open actions, each with a follow-up result from the next year',
    fact: 'Every CO below target gets an action when attainment is computed. The next computation links its follow-up and shows the change.',
  },
  {
    name: 'What-if', src: '/landing/whatif.webp', w: 1600, h: 380, stage: 'var(--lp-field-1)',
    alt: 'What-if form with student target, level thresholds and weights',
    fact: 'Change the target, thresholds or weights and re-run an offering. Results land in scenario tables; the official ones do not move.',
  },
  {
    name: 'Rule versions', src: '/landing/rules.webp', w: 1568, h: 300, stage: 'var(--lp-field-3)',
    alt: 'Rule versions table: 55 % target from Aug 2021 to Aug 2024, 60 % from Aug 2024',
    fact: 'Targets and weights are rows with a validity period. 2023 results were computed at 55 % and still reproduce at 55 %.',
  },
]

const TESTS: [string, number, string][] = [
  ['Correctness', 13, 'Worked example: CO 3.00 / 2.20 / 0.40, PO1 2.30, PO2 1.48.'],
  ['Constraints', 23, 'Out-of-range marks, locked edits, bad weights and cycles all rejected.'],
  ['Access control', 18, 'Faculty see only their offerings; students only their own rows.'],
  ['Audit tamper', 7, 'An edited or deleted audit record is reported at its seq.'],
  ['Root cause', 6, 'The planted cause ranks first; the decoy is excluded.'],
  ['Surveys and ETL', 7, 'Reference checks, one response per student, idempotent load.'],
  ['Simulator isolation', 4, 'What-if runs leave official tables unchanged.'],
  ['Reproducibility', 4, 'Old rule versions reproduce old numbers exactly.'],
  ['Concurrency', 2, 'A second compute waits or is refused; a failed run keeps the last result.'],
]

export function Landing() {
  const root = useRef<HTMLDivElement>(null)
  useReveal(root)

  return (
    <div className="lp" ref={root}>
      <a className="lp-skip" href="#main">Skip to content</a>
      <header className="lp-bar">
        <Link to="/" className="lp-word" aria-label="CO-PO Attainment, home"><Mark /><span>CO-PO Attainment</span></Link>
        <nav aria-label="Sections">
          <a href="#method">Method</a>
          <a href="#views">Views</a>
          <a href="#tests">Tests</a>
          <Link to="/login" className="lp-bar-sign">Sign in</Link>
        </nav>
      </header>
      <main id="main">
        <Hero />
        <Method />
        <Rules />
        <Views />
        <Calculator />
        <Tests />
        <Start />
      </main>
      <Footer />
    </div>
  )
}

function Hero() {
  const shutter = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const t = requestAnimationFrame(() => shutter.current?.classList.add('is-in'))
    return () => cancelAnimationFrame(t)
  }, [])
  return (
    <section className="lp-hero" aria-labelledby="lp-title">
      <Stairs className="lp-hero-stairs" />
      <div className="lp-hero-copy">
        <h1 id="lp-title">CO-PO attainment</h1>
        <p className="lp-lede">
          A PostgreSQL and MongoDB system that turns question-wise marks and course-exit surveys into Course
          Outcome and Programme Outcome levels for NBA accreditation, with the rules kept in the database.
        </p>
        <div className="lp-hero-actions">
          <Link to="/login" className="lp-btn">Sign in to the demo</Link>
          <a href="#method" className="lp-link">See the method</a>
        </div>
        <p className="lp-credit">DBMS (CD252IA) project · Dept. of ISE, RV College of Engineering · Team 2</p>
      </div>
      <figure className="lp-hero-shot">
        <div className="lp-shutter lp-frame" ref={shutter}>
          <img src="/landing/ladder.webp" width={1058} height={530}
               alt="CO attainment ladder for Database Management Systems, 2024-25, section C: CO2 at 2.20, the other four below the 2.00 target" />
        </div>
        <figcaption>IS243 Database Management Systems, 2024-25, section C. Four of five COs below target.</figcaption>
      </figure>
    </section>
  )
}

function Method() {
  const [open, setOpen] = useState(0)
  const base = useId()
  return (
    <section className="lp-method" id="method" aria-labelledby="lp-method-h">
      <div className="lp-intro" data-reveal>
        <h2 id="lp-method-h" style={{ '--i': 0 } as React.CSSProperties}>Five steps, one procedure</h2>
        <p style={{ '--i': 1 } as React.CSSProperties}>
          <code>sp_compute_attainment</code> runs all five in one transaction and refuses to start while any
          assessment is still unlocked. Every threshold and weight below is a row in <code>attainment_config</code>,
          not a constant in code.
        </p>
      </div>
      <div className="lp-acc" data-reveal>
        {STEPS.map((s, i) => {
          const isOpen = open === i
          return (
            <div key={s.name} className={`lp-acc-panel t${i}`} data-open={isOpen} style={{ '--i': i } as React.CSSProperties}>
              <h3>
                <button type="button" aria-expanded={isOpen} aria-controls={`${base}-${i}`} id={`${base}-b${i}`}
                        onClick={() => setOpen(i)}>
                  <span className="lp-acc-name">{s.name}</span>
                </button>
              </h3>
              <div className="lp-acc-body" id={`${base}-${i}`} role="region" aria-labelledby={`${base}-b${i}`} hidden={!isOpen}>
                <p>{s.text}</p>
                {s.pic
                  ? <img src={s.pic.src} width={s.pic.w} height={s.pic.h} alt={s.pic.alt} loading="lazy" className="lp-frame" />
                  : <p className="lp-acc-formula" aria-hidden="true">(80 × 2 + 20 × 3) / 100 = 2.20</p>}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function Rules() {
  return (
    <section className="lp-rules" id="rules" aria-labelledby="lp-rules-h">
      <div className="lp-rules-head" data-reveal>
        <h2 id="lp-rules-h" style={{ '--i': 0 } as React.CSSProperties}>Enforced in SQL</h2>
        <p style={{ '--i': 1 } as React.CSSProperties}>
          Triggers, CHECK constraints and row-level security hold these rules, so the API cannot skip them. Each
          request runs in one transaction as the caller's own database role.
        </p>
      </div>
      <ul className="lp-tiles" data-reveal>
        <li style={{ '--i': 0 } as React.CSSProperties}>
          <div className="lp-tile f1">
            <div className="lp-ui" data-ui>
              <div className="lp-ui-row"><span>CIE Test 2</span><span className="lp-pill">Locked</span></div>
              <div className="lp-ui-row"><span>Quiz 2</span><span className="lp-pill">Locked</span></div>
              <div className="lp-ui-err">CP001 Assessment is locked</div>
            </div>
          </div>
          <h3>Locking</h3>
          <p>Locks only when every mark is in. Unlocking needs the HoD's approval, and each refused edit is logged.</p>
        </li>
        <li className="wide" style={{ '--i': 1 } as React.CSSProperties}>
          <div className="lp-tile f2">
            <img src="/landing/rules.webp" width={1568} height={300} loading="lazy" className="lp-frame"
                 alt="Two rule versions: 55 % target until 1 Aug 2024, 60 % since" />
          </div>
          <h3>Versioned rules</h3>
          <p>Each offering uses the rules in force for its term, so results from 2023 still reproduce.</p>
        </li>
        <li style={{ '--i': 2 } as React.CSSProperties}>
          <div className="lp-tile f3">
            <div className="lp-ui" data-ui>
              <div className="lp-ui-file">marks_IS243_C.csv</div>
              <div className="lp-ui-err">Row 14, Q3: 12 is above the maximum 10 (CP002)</div>
              <div className="lp-ui-muted">0 of 60 rows saved</div>
            </div>
          </div>
          <h3>All-or-nothing upload</h3>
          <p>Every row of a question-wise CSV is checked. One bad row and nothing is saved.</p>
        </li>
        <li style={{ '--i': 3 } as React.CSSProperties}>
          <div className="lp-tile f2">
            <div className="lp-ui" data-ui>
              {[['HoD', 'every offering'], ['Faculty', 'own offerings'], ['Coordinator', 'all, read-only'], ['Student', 'own rows']].map(([r, s]) => (
                <div className="lp-ui-row" key={r}><span>{r}</span><span className="lp-ui-muted">{s}</span></div>
              ))}
            </div>
          </div>
          <h3>Row-level security</h3>
          <p>PostgreSQL policies per role. The API login itself can read nothing.</p>
        </li>
        <li style={{ '--i': 4 } as React.CSSProperties}>
          <div className="lp-tile f1">
            <div className="lp-ui lp-ui-chain" data-ui>
              {[['573221', '6642b0bd…d7a6e9da'], ['573222', '8f594847…ff032eb2'], ['573223', '30f94908…c4967511']].map(([s, h]) => (
                <div className="lp-ui-row" key={s}><span>seq {s}</span><span className="lp-ui-hash">{h}</span></div>
              ))}
            </div>
          </div>
          <h3>Audit chain</h3>
          <p>Each change goes to an outbox in the same transaction, then into a SHA-256 chain in MongoDB.</p>
        </li>
        <li style={{ '--i': 5 } as React.CSSProperties}>
          <div className="lp-tile f3">
            <div className="lp-ui" data-ui>
              <div className="lp-ui-row"><span>Student target</span><b>55 %</b></div>
              <div className="lp-ui-row"><span>Survey weight</span><b>30 %</b></div>
              <div className="lp-ui-muted">Writes to scenario tables only</div>
            </div>
          </div>
          <h3>What-if, kept apart</h3>
          <p>Scenarios write to their own tables and can never be saved as official.</p>
        </li>
      </ul>
    </section>
  )
}

function Views() {
  const [sel, setSel] = useState(0)
  const s = SCREENS[sel]
  return (
    <section className="lp-views" id="views" aria-labelledby="lp-views-h">
      <div className="lp-views-stage" style={{ background: s.stage }}>
        <Stairs className="lp-views-stairs" />
        {SCREENS.map((x, i) => (
          <img key={x.name} src={x.src} width={x.w} height={x.h} alt={x.alt} loading="lazy"
               className="lp-frame" data-on={i === sel} aria-hidden={i !== sel} />
        ))}
      </div>
      <div className="lp-views-list" data-reveal>
        <h2 id="lp-views-h" style={{ '--i': 0 } as React.CSSProperties}>When a CO falls</h2>
        <ul role="list">
          {SCREENS.map((x, i) => (
            <li key={x.name} style={{ '--i': i + 1 } as React.CSSProperties}>
              <button type="button" aria-pressed={i === sel} onClick={() => setSel(i)}>
                <Bullet />{x.name}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <p className="lp-views-fact" aria-live="polite">{s.fact}</p>
    </section>
  )
}

function Calculator() {
  const [atTarget, setAtTarget] = useState(58)
  const [favourable, setFavourable] = useState(74)
  const d = toLevel(atTarget), sv = toLevel(favourable)
  const final = (DIRECT * d + SURVEY * sv) / 100
  return (
    <section className="lp-calc" id="try" aria-labelledby="lp-calc-h">
      <div className="lp-calc-top">
        <h2 id="lp-calc-h">How many reached 60 %?</h2>
        <div className="lp-calc-ui" data-ui>
          <label className="lp-range">
            <span className="lp-range-label">Students at or above the target<output>{atTarget} %</output></span>
            <input type="range" min={0} max={100} value={atTarget} onChange={(e) => setAtTarget(+e.target.value)} />
          </label>
          <label className="lp-range">
            <span className="lp-range-label">Survey ratings of 4 or 5<output>{favourable} %</output></span>
            <input type="range" min={0} max={100} value={favourable} onChange={(e) => setFavourable(+e.target.value)} />
          </label>
        </div>
      </div>
      <div className="lp-calc-bottom">
        <p className="lp-figure" aria-live="polite">
          <span className="visually-hidden">Final CO level </span>{final.toFixed(2)}<span className="lp-unit"> of 3</span>
        </p>
        <p className="lp-calc-why">
          {atTarget} % of students gives direct level {d}; {favourable} % favourable gives survey level {sv}.
          ({DIRECT} × {d} + {SURVEY} × {sv}) / 100 = {final.toFixed(2)}, {final >= 2 ? 'at or above' : 'below'} the 2.00 target.
        </p>
      </div>
    </section>
  )
}

function Tests() {
  return (
    <section className="lp-tests" id="tests" aria-labelledby="lp-tests-h">
      <ul className="lp-board" data-reveal>
        <li className="lp-board-head" style={{ '--i': 0 } as React.CSSProperties}>
          <h2 id="lp-tests-h">84 tests, all passing</h2>
          <p>
            Each one rebuilds a test database. The demo data is a synthetic ISE programme: 1,440 students,
            280 offerings, 556,800 question-wise marks and 11,965 surveys.
          </p>
        </li>
        {TESTS.map(([name, n, what], i) => (
          <li key={name} style={{ '--i': i + 1 } as React.CSSProperties}>
            <h3>{name}</h3>
            <p><b>{n}</b> {n === 1 ? 'test' : 'tests'}. {what}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Start() {
  const navigate = useNavigate()
  const [role, setRole] = useState<'hod' | 'faculty'>('hod')
  const [user, setUser] = useState('hod')
  function pick(r: 'hod' | 'faculty') { setRole(r); setUser(r === 'hod' ? 'hod' : 'fac06') }
  return (
    <section className="lp-start" id="start" aria-labelledby="lp-start-h">
      <div className="lp-start-copy">
        <h2 id="lp-start-h">Open the demo</h2>
        <p>Sign in with a demo login. The password is <code>DEMO_PASSWORD</code> in your <code>.env</code>; the
          HoD sees every offering, faculty only their own.</p>
      </div>
      <form className="lp-dialog" data-ui onSubmit={(e) => { e.preventDefault(); navigate(`/login?u=${encodeURIComponent(user.trim())}`) }}>
        <h3>Sign in as</h3>
        <div className="lp-seg" role="radiogroup" aria-label="Role">
          {(['hod', 'faculty'] as const).map((r) => (
            <button key={r} type="button" role="radio" aria-checked={role === r} onClick={() => pick(r)}>
              {r === 'hod' ? 'Head of department' : 'Faculty'}
            </button>
          ))}
        </div>
        <label className="field">
          <span>Username</span>
          <input className="input" value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" required />
        </label>
        <p className="lp-dialog-note">Faculty logins run from fac01 to fac14; fac06 teaches IS243 sections C and D.</p>
        <button className="lp-btn" type="submit">Continue to sign in</button>
      </form>
    </section>
  )
}

function Footer() {
  const blocks: [string, number][] = [['C', 62], ['O', 74], ['–', 50], ['P', 87], ['O', 100]]
  return (
    <footer className="lp-foot">
      <div className="lp-foot-mark" aria-hidden="true">
        {blocks.map(([ch, h], i) => <span key={i} style={{ height: `${h}%` }}>{ch}</span>)}
      </div>
      <div className="lp-foot-cols">
        <div>
          <h2>On this page</h2>
          <a href="#method">Method</a><a href="#rules">Rules</a><a href="#views">Views</a><a href="#tests">Tests</a>
        </div>
        <div>
          <h2>The app</h2>
          <Link to="/login">Sign in</Link><a href="/docs">API reference</a>
        </div>
        <div>
          <h2>Built with</h2>
          <p>PostgreSQL 16, MongoDB 8, FastAPI, React 18</p>
        </div>
        <div className="lp-foot-addr">
          <p>Department of Information Science and Engineering, RV College of Engineering, Bengaluru</p>
          <p>Database Management Systems (CD252IA), Team 2. All data is synthetic.</p>
        </div>
      </div>
      <div className="lp-foot-last">
        <p>© 2026 Team 2 · MIT licence</p>
        <Link to="/login" className="lp-btn small">Sign in</Link>
      </div>
    </footer>
  )
}
