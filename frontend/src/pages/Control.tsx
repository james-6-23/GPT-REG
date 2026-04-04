import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import StateShell from '../components/StateShell'
import ToastNotice from '../components/ToastNotice'
import { useDataLoader } from '../hooks/useDataLoader'
import { useToast } from '../hooks/useToast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Play, Square, RotateCcw, Activity, Cpu, Trophy, XCircle, Clock, Radio, HardDrive } from 'lucide-react'
import type { ControlData } from '../types'

export default function Control() {
  const { toast, showToast } = useToast()
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [sseConnected, setSseConnected] = useState(false)

  const load = useCallback(() => api.getControl(), [])
  const { data, setData, loading, error, reload } = useDataLoader<ControlData | null>({
    initialData: null,
    load,
  })

  // SSE 实时推送
  const esRef = useRef<EventSource | null>(null)
  useEffect(() => {
    const es = new EventSource('/api/control/stream')
    esRef.current = es

    es.onopen = () => setSseConnected(true)

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data)
        if (parsed.data) {
          setData(parsed.data as ControlData)
        }
      } catch {
        // 忽略解析错误
      }
    }

    es.onerror = () => {
      setSseConnected(false)
    }

    return () => {
      es.close()
      esRef.current = null
      setSseConnected(false)
    }
  }, [setData])

  const handleAction = async (action: string) => {
    setActionLoading(action)
    try {
      const res = await api.controlAction(action)
      showToast(String(res.message || '操作成功'))
    } catch (err) {
      showToast(err instanceof Error ? err.message : '操作失败', 'error')
    } finally {
      setActionLoading(null)
    }
  }

  const actionIcons: Record<string, React.ReactNode> = {
    start: <Play className="size-4" />,
    stop: <Square className="size-4" />,
    restart: <RotateCcw className="size-4" />,
  }

  return (
    <>
      <ToastNotice toast={toast} />
      <PageHeader title="运行控制" description="管理 Reg-GPT 引擎的启动、停止和重启" onRefresh={reload} actions={
        <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${sseConnected ? 'text-emerald-500' : 'text-muted-foreground'}`}>
          <Radio className="size-3.5" />
          {sseConnected ? '实时' : '离线'}
        </span>
      } />

      <StateShell variant="page" loading={loading} error={error} onRetry={reload}>
        {data && (
          <div className="space-y-6">
            {/* 引擎状态 */}
            <Card>
              <CardContent className="p-6">
                <h3 className="text-base font-semibold mb-4">引擎状态</h3>
                <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-3">
                  <InfoBlock icon={<Activity className="size-5" />} iconBg="bg-emerald-500/10 text-emerald-500" label="状态" value={
                    <Badge variant={data.running ? 'default' : 'secondary'} className={data.running ? 'bg-emerald-500 text-white' : ''}>
                      {data.running ? '运行中' : '已停止'}
                    </Badge>
                  } />
                  <InfoBlock icon={<Cpu className="size-5" />} iconBg="bg-blue-500/10 text-blue-500" label="阶段" value={data.phase} />
                  <InfoBlock icon={<Clock className="size-5" />} iconBg="bg-amber-500/10 text-amber-500" label="启动时间" value={data.started_at || '—'} />
                  <InfoBlock icon={<Activity className="size-5" />} iconBg="bg-purple-500/10 text-purple-500" label="PID" value={data.pid ? String(data.pid) : '—'} />
                  <InfoBlock icon={<Trophy className="size-5" />} iconBg="bg-emerald-500/10 text-emerald-500" label="成功" value={String(data.successes)} />
                  <InfoBlock icon={<XCircle className="size-5" />} iconBg="bg-red-500/10 text-red-500" label="失败" value={String(data.failures)} />
                  <InfoBlock icon={<HardDrive className="size-5" />} iconBg="bg-cyan-500/10 text-cyan-500" label="内存" value={
                    <MemoryDisplay memory={(data as Record<string, unknown>).memory as Record<string, number> | undefined} />
                  } />
                </div>
              </CardContent>
            </Card>

            {/* 控制按钮 */}
            <Card>
              <CardContent className="p-6">
                <h3 className="text-base font-semibold mb-4">控制操作</h3>
                <div className="flex flex-wrap gap-3">
                  {data.actions.map(action => (
                    <Button
                      key={action.id}
                      variant={action.id === 'stop' ? 'destructive' : action.id === 'start' ? 'default' : 'outline'}
                      disabled={!action.enabled || actionLoading !== null}
                      onClick={() => handleAction(action.id)}
                    >
                      {actionLoading === action.id ? (
                        <div className="spinner !size-4 !border-2" />
                      ) : (
                        actionIcons[action.id] ?? <Play className="size-4" />
                      )}
                      {action.label}
                    </Button>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* 工作线程 - 两列网格 */}
            {data.worker_slots && data.worker_slots.length > 0 && (
              <Card>
                <CardContent className="p-6">
                  <h3 className="text-base font-semibold mb-4">工作线程 ({data.worker_slots.length})</h3>
                  <div className="grid grid-cols-2 max-lg:grid-cols-1 gap-3">
                    {data.worker_slots.map(slot => (
                      <div key={slot.worker_id} className="p-4 rounded-xl bg-muted/50 border border-border">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-semibold">线程 #{slot.worker_id}</span>
                          <div className="flex items-center gap-2">
                            {slot.phase && <Badge variant="outline" className="text-[11px]">{slot.phase}</Badge>}
                          </div>
                        </div>
                        {slot.email && (
                          <div className="text-xs text-muted-foreground mb-2 truncate">{slot.email}</div>
                        )}
                        {slot.lines.length > 0 && (
                          <div className="log-viewer bg-background/50 rounded-lg p-2 max-h-[100px] overflow-auto">
                            {slot.lines.map((line, i) => (
                              <div key={i} className="text-xs text-muted-foreground leading-relaxed font-mono">{line}</div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}
      </StateShell>
    </>
  )
}

function InfoBlock({ icon, iconBg, label, value }: { icon: React.ReactNode; iconBg: string; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 p-3.5 rounded-xl bg-muted/50">
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

function MemoryDisplay({ memory }: { memory?: Record<string, number> }) {
  if (!memory || !memory.used_mb) return <span className="text-muted-foreground">—</span>
  const used = memory.used_mb
  const limit = memory.limit_mb
  const pct = memory.percent
  const color = pct > 80 ? 'text-red-500' : pct > 60 ? 'text-amber-500' : 'text-foreground'
  return (
    <span className={color}>
      {used >= 1024 ? `${(used / 1024).toFixed(1)} GB` : `${used} MB`}
      {limit > 0 && <span className="text-muted-foreground font-normal"> / {limit >= 1024 ? `${(limit / 1024).toFixed(1)} GB` : `${limit} MB`} ({pct}%)</span>}
    </span>
  )
}
