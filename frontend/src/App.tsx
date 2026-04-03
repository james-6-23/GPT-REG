import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import ToastNotice from './components/ToastNotice'
import { useToast } from './hooks/useToast'

import Dashboard from './pages/Dashboard'
import Config from './pages/Config'
import Cpa from './pages/Cpa'
import Security from './pages/Security'
import Control from './pages/Control'
import Logs from './pages/Logs'
import Results from './pages/Results'

export default function App() {
  const { toast } = useToast()

  return (
    <>
      <ToastNotice toast={toast} />
      <Layout>
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
