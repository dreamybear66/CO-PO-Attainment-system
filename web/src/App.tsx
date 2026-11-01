import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import { Shell } from './components/Shell'
import { SkeletonRows } from './components/States'
import { Actions } from './pages/Actions'
import { Login } from './pages/Login'
import { Offering } from './pages/Offering'
import { Offerings } from './pages/Offerings'
import { Settings } from './pages/Settings'
import { MyScores, Surveys } from './pages/Student'
import { Trends } from './pages/Trends'

export default function App() {
  const { user, ready } = useAuth()
  if (!ready) return <div style={{ padding: 24 }}><SkeletonRows rows={3} /></div>
  if (!user) return <Login />
  if (user.role === 'student') {
    return (
      <Shell>
        <Routes>
          <Route path="/me" element={<MyScores />} />
          <Route path="/me/surveys" element={<Surveys />} />
          <Route path="*" element={<Navigate to="/me" replace />} />
        </Routes>
      </Shell>
    )
  }
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Offerings />} />
        <Route path="/offerings/:id" element={<Offering />} />
        <Route path="/trends" element={<Trends />} />
        <Route path="/actions" element={<Actions />} />
        {(user.role === 'admin' || user.role === 'coordinator') && <Route path="/settings" element={<Settings />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}
