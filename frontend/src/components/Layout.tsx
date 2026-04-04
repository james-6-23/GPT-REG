import { type PropsWithChildren, useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, Settings as SettingsIcon, Activity, Shield, Play,
  ScrollText, FileCheck, Sun, Moon
} from 'lucide-react'
import { useTheme } from '../hooks/useTheme'
import type { ReactNode } from 'react'

type NavDef = {
  to: string
  label: string
  icon: ReactNode
  end?: boolean
}

const navDefs: NavDef[] = [
  { to: '/', label: '总览', icon: <LayoutDashboard className="size-[18px]" />, end: true },
  { to: '/config', label: '配置中心', icon: <SettingsIcon className="size-[18px]" /> },
  { to: '/security', label: '安全设置', icon: <Shield className="size-[18px]" />, end: true },
  { to: '/control', label: '运行控制', icon: <Play className="size-[18px]" />, end: true },
  { to: '/logs', label: '日志监控', icon: <ScrollText className="size-[18px]" />, end: true },
  { to: '/results', label: '结果概览', icon: <FileCheck className="size-[18px]" />, end: true },
]

export default function Layout({ children }: PropsWithChildren) {
  const { theme, toggle } = useTheme()
  const [spinning, setSpinning] = useState(false)

  const handleThemeToggle = (e: React.MouseEvent) => {
    setSpinning(true)
    toggle(e)
    setTimeout(() => setSpinning(false), 500)
  }

  return (
    <div className="min-h-dvh">
      <div className="grid grid-cols-[280px_minmax(0,1fr)] max-w-full max-lg:grid-cols-1 max-lg:px-4">
        {/* Sidebar */}
        <aside className="sticky top-0 self-start h-dvh border-r border-border bg-[hsl(var(--sidebar-background))] max-lg:hidden">
          <div className="flex flex-col h-full px-6 pt-8 pb-6">
            {/* Brand */}
            <div className="pb-6 border-b border-border">
              <div className="flex items-center gap-3.5">
                <div className="w-[48px] h-[48px] rounded-2xl bg-gradient-to-br from-emerald-500 to-blue-600 flex items-center justify-center shadow-[0_4px_16px_hsl(170_60%_45%/0.2)] shrink-0">
                  <span className="text-white font-bold text-lg">R</span>
                </div>
                <div className="flex flex-col gap-1 min-w-0">
                  <h1 className="text-[20px] leading-tight font-bold text-foreground whitespace-nowrap">
                    Reg-GPT
                  </h1>
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-primary/10 text-primary text-[11px] font-bold w-fit">
                    v1.0.0
                  </span>
                </div>
              </div>
            </div>

            {/* Nav */}
            <nav className="flex-1 flex flex-col gap-2 pt-5" aria-label="Main navigation">
              <span className="text-[12px] font-bold tracking-[0.16em] uppercase text-primary/70 mb-1">
                控制台
              </span>
              {navDefs.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `flex items-center gap-3 min-h-[46px] px-3.5 py-2.5 border rounded-2xl text-[15px] font-semibold transition-all duration-150 ${
                      isActive
                        ? 'bg-gradient-to-br from-primary/8 to-blue-500/6 border-primary/20 text-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.8)]'
                        : 'border-transparent text-muted-foreground hover:-translate-y-px hover:bg-white/50 hover:border-border hover:text-foreground'
                    }`
                  }
                >
                  {item.icon}
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </nav>

            {/* Footer */}
            <div className="mt-auto flex items-center justify-between">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/16 bg-[hsl(var(--success-bg))] px-3 py-1.5 text-[11px] font-bold text-[hsl(var(--success))] shadow-[inset_0_1px_0_rgba(255,255,255,0.55)] shrink-0 whitespace-nowrap">
                <span className="size-2 rounded-full bg-emerald-500 shrink-0" />
                在线
              </span>
              <div className="flex items-center gap-0.5">
                <button
                  onClick={handleThemeToggle}
                  className="flex items-center justify-center size-9 rounded-xl text-muted-foreground hover:text-foreground hover:bg-white/60 dark:hover:bg-white/10 transition-all duration-150"
                  title={theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'}
                >
                  <span className={`inline-flex transition-transform duration-500 ease-out ${spinning ? 'rotate-[360deg] scale-110' : 'rotate-0 scale-100'}`}>
                    {theme === 'dark' ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
                  </span>
                </button>
              </div>
            </div>
          </div>
        </aside>

        {/* Main content */}
        <main className="min-w-0 p-6 max-lg:pb-[104px]">
          {/* Mobile topbar */}
          <header className="hidden max-lg:flex items-center justify-between gap-4 mb-4 p-3.5 border border-border rounded-[22px] bg-white/70 dark:bg-[hsl(220_13%_15%/0.7)]">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-[10px] bg-gradient-to-br from-emerald-500 to-blue-600 flex items-center justify-center">
                <span className="text-white font-bold text-sm">R</span>
              </div>
              <strong className="text-lg">Reg-GPT</strong>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={handleThemeToggle}
                className="flex items-center justify-center size-8 rounded-lg text-muted-foreground hover:text-foreground transition-colors"
                title={theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'}
              >
                <span className={`inline-flex transition-transform duration-500 ease-out ${spinning ? 'rotate-[360deg] scale-110' : 'rotate-0 scale-100'}`}>
                  {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
                </span>
              </button>
            </div>
          </header>

          <div className="min-h-full">{children}</div>
        </main>

        {/* Mobile bottom nav */}
        <nav className="fixed left-4 right-4 bottom-4 z-40 hidden max-lg:grid grid-cols-7 gap-1 p-2 border border-border rounded-3xl bg-white/90 shadow-lg backdrop-blur-[20px]" aria-label="Mobile navigation">
          {navDefs.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex flex-col items-center justify-center gap-1 min-h-[56px] p-1.5 border rounded-2xl text-center text-[10px] font-bold transition-all duration-150 ${
                  isActive
                    ? 'bg-white/80 border-primary/20 text-foreground'
                    : 'border-transparent text-muted-foreground'
                }`
              }
            >
              {item.icon}
              <span className="truncate w-full">{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  )
}
