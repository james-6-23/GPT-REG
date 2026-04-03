import { useCallback } from 'react'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import StateShell from '../components/StateShell'
import StatCard from '../components/StatCard'
import { useDataLoader } from '../hooks/useDataLoader'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Mail, Cpu, Trophy, XCircle, Clock, Hash, FileText, Activity
} from 'lucide-react'
import type { DashboardData } from '../types'

export default function Dashboard() {
  const load = useCallback(() => api.getDashboard(), [])
  const { data, loading, error, reload } = useDataLoader<DashboardData | null>({
    initialData: null,
    load,
  })

  const s = data?.summary
  const rt = data?.runtime

  return (
    <StateShell variant="page" loading={loading} error={error} onRetry={reload}>
      <>
        <PageHeader title="总览" description="Reg-GPT 注册引擎运行状态总览" onRefresh={reload} />

        {s && (
          <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-4 mb-6">
            <StatCard icon={<Mail className="size-[22px]" />} iconClass="blue" label="启用邮箱" value={s.email_enabled} />
            <StatCard icon={<Cpu className="size-[22px]" />} iconClass="purple" label="工作线程" value={s.workers} />
            <StatCard icon={<Trophy className="size-[22px]" />} iconClass="green" label="成功次数" value={s.successes} sub={`共尝试 ${s.attempts} 次`} />
            <StatCard icon={<XCircle className="size-[22px]" />} iconClass="red" label="失败次数" value={s.failures} />
            <StatCard icon={<Hash className="size-[22px]" />} iconClass="amber" label="Token 数" value={s.token_count} />
            <StatCard icon={<FileText className="size-[22px]" />} iconClass="blue" label="账号数" value={s.accounts_count} />
          </div>
        )}

        {rt && (
          <div className="space-y-6">
            <Card>
              <CardContent className="p-6">
                <h3 className="text-base font-semibold text-foreground mb-4">运行状态</h3>
                <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
                  <InfoItem icon={<Activity className="size-5" />} iconBg="bg-emerald-500/10 text-emerald-500" label="状态" value={
                    <Badge variant={rt.running ? 'default' : 'secondary'} className={rt.running ? 'bg-emerald-500 text-white' : ''}>
                      {rt.running ? '运行中' : '已停止'}
                    </Badge>
                  } />
                  <InfoItem icon={<Cpu className="size-5" />} iconBg="bg-blue-500/10 text-blue-500" label="阶段" value={rt.phase} />
                  <InfoItem icon={<Clock className="size-5" />} iconBg="bg-amber-500/10 text-amber-500" label="启动时间" value={rt.started_at || '—'} />
                  <InfoItem icon={<Mail className="size-5" />} iconBg="bg-purple-500/10 text-purple-500" label="最后邮箱" value={rt.last_email || '—'} />
                  <InfoItem icon={<Hash className="size-5" />} iconBg="bg-cyan-500/10 text-cyan-500" label="活跃线程" value={String(rt.workers_active)} />
                  <InfoItem icon={<Activity className="size-5" />} iconBg="bg-red-500/10 text-red-500" label="PID" value={rt.pid ? String(rt.pid) : '—'} />
                </div>
              </CardContent>
            </Card>

            {s && (
              <Card>
                <CardContent className="p-6">
                  <h3 className="text-base font-semibold text-foreground mb-4">配置概要</h3>
                  <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
                    <InfoItem icon={<Activity className="size-5" />} iconBg="bg-blue-500/10 text-blue-500" label="代理" value={s.proxy} />
                    <InfoItem icon={<Clock className="size-5" />} iconBg="bg-amber-500/10 text-amber-500" label="休眠窗口" value={s.sleep_window} />
                    <InfoItem icon={<Trophy className="size-5" />} iconBg="bg-emerald-500/10 text-emerald-500" label="最大成功数" value={s.max_success === 0 ? '无限制' : String(s.max_success)} />
                    <InfoItem icon={<Clock className="size-5" />} iconBg="bg-purple-500/10 text-purple-500" label="配置更新" value={s.config_updated_at} />
                  </div>
                </CardContent>
              </Card>
            )}

            {data?.recent_tokens && data.recent_tokens.length > 0 && (
              <Card>
                <CardContent className="p-6">
                  <h3 className="text-base font-semibold text-foreground mb-4">最近 Token 文件</h3>
                  <div className="space-y-2">
                    {data.recent_tokens.slice(0, 5).map((t, i) => (
                      <div key={i} className="flex items-center justify-between p-3 rounded-xl bg-muted/50">
                        <span className="text-sm font-medium truncate">{t.filename}</span>
                        <span className="text-xs text-muted-foreground shrink-0 ml-4">{t.modified}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}
      </>
    </StateShell>
  )
}

function InfoItem({ icon, iconBg, label, value }: { icon: React.ReactNode; iconBg: string; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 p-4 rounded-xl bg-muted/50">
      <div className={`flex items-center justify-center size-10 rounded-lg ${iconBg}`}>
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="text-sm font-bold mt-0.5">{value}</div>
      </div>
    </div>
  )
}
