import { useState, useEffect, useCallback } from 'react'
import { Routes, Route, useNavigate } from 'react-router-dom'
import { api, AUTH_REQUIRED_EVENT } from './api'
import Layout from './components/Layout'
import ToastNotice from './components/ToastNotice'
import { useToast } from './hooks/useToast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Lock } from 'lucide-react'

import Dashboard from './pages/Dashboard'
import Config from './pages/Config'
import Cpa from './pages/Cpa'
import Security from './pages/Security'
import Control from './pages/Control'
import Logs from './pages/Logs'
import Results from './pages/Results'

function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      const res = await api.login(username, password)
      if (res.ok) {
        onLogin()
      } else {
        const data = await res.json().catch(() => null)
        setError(data?.message || '登录失败，请重试')
      }
    } catch {
      setError('网络错误，请检查连接')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-dvh flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-[400px]">
        <div className="text-center mb-8">
          <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-br from-emerald-500 to-blue-600 flex items-center justify-center shadow-lg">
            <span className="text-white font-bold text-2xl">R</span>
          </div>
          <h1 className="text-2xl font-bold text-foreground">Reg-GPT</h1>
          <p className="text-sm text-muted-foreground mt-1">管理后台登录</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 p-6 border border-border rounded-2xl bg-card shadow-sm">
          {error && (
            <div className="p-3 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm">
              {error}
            </div>
          )}

          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">用户名</label>
            <Input
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="请输入用户名"
              autoFocus
              required
            />
          </div>

          <div>
            <label className="text-sm font-medium text-foreground mb-1.5 block">密码</label>
            <Input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="请输入密码"
              required
            />
          </div>

          <Button type="submit" className="w-full" disabled={loading}>
            <Lock className="size-4" />
            {loading ? '登录中…' : '登录'}
          </Button>
        </form>
      </div>
    </div>
  )
}

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null)
  const { toast, showToast } = useToast()
  const navigate = useNavigate()

  const checkAuth = useCallback(async () => {
    try {
      const ok = await api.checkAuth()
      setAuthed(ok)
    } catch {
      setAuthed(false)
    }
  }, [])

  useEffect(() => {
    void checkAuth()
  }, [checkAuth])

  useEffect(() => {
    const handler = () => {
      setAuthed(false)
      showToast('登录已过期，请重新登录', 'error')
    }
    window.addEventListener(AUTH_REQUIRED_EVENT, handler)
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, handler)
  }, [showToast])

  const handleLogin = () => {
    setAuthed(true)
    navigate('/')
  }

  const handleLogout = async () => {
    try {
      await api.logout('')
    } catch {
      // ignore
    }
    setAuthed(false)
  }

  if (authed === null) {
    return (
      <div className="min-h-dvh flex items-center justify-center">
        <div className="spinner" />
      </div>
    )
  }

  if (!authed) {
    return (
      <>
        <ToastNotice toast={toast} />
        <LoginPage onLogin={handleLogin} />
      </>
    )
  }

  return (
    <>
      <ToastNotice toast={toast} />
      <Layout onLogout={handleLogout}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/config" element={<Config />} />
          <Route path="/cpa" element={<Cpa />} />
          <Route path="/security" element={<Security />} />
          <Route path="/control" element={<Control />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/results" element={<Results />} />
        </Routes>
      </Layout>
    </>
  )
}
