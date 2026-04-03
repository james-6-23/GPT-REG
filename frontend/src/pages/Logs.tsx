import { useCallback, useRef, useEffect } from 'react'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import StateShell from '../components/StateShell'
import { useDataLoader } from '../hooks/useDataLoader'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Activity, FileText, Clock } from 'lucide-react'
import type { LogsData } from '../types'

export default function Logs() {
  const logContainerRef = useRef<HTMLDivElement>(null)

  const load = useCallback(() => api.getLogs(300), [])
  const { data, loading, error, reload } = useDataLoader<LogsData | null>({
    initialData: null,
    load,
  })

  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [data?.lines])

  return (
    <>
      <PageHeader title="日志监控" description="查看引擎运行日志和最近事件" onRefresh={reload} />

      <StateShell variant="page" loading={loading} error={error} onRetry={reload}>
        {data && (
          <div className="space-y-6">
            <div className="flex flex-wrap gap-3 items-center">
              <Badge variant={data.running ? 'default' : 'secondary'} className={data.running ? 'bg-emerald-500 text-white' : ''}>
                {data.running ? '运行中' : '已停止'}
              </Badge>
              <span className="text-sm text-muted-foreground flex items-center gap-1">
                <Activity className="size-3.5" /> 阶段: {data.phase}
              </span>
              <span className="text-sm text-muted-foreground flex items-center gap-1">
                <Clock className="size-3.5" /> 更新: {data.updated_at}
              </span>
              <span className="text-sm text-muted-foreground flex items-center gap-1">
                <FileText className="size-3.5" /> {data.log_file}
              </span>
            </div>

            <Card>
              <CardContent className="p-0">
                <div
                  ref={logContainerRef}
                  className="log-viewer h-[500px] overflow-auto p-4 bg-background"
                >
                  {data.lines.length === 0 ? (
                    <div className="text-center text-muted-foreground py-8">暂无日志</div>
                  ) : (
                    data.lines.map((line, i) => (
                      <div
                        key={i}
                        className={`py-0.5 border-b border-border/30 last:border-0 ${
                          line.includes('ERROR') || line.includes('error')
                            ? 'text-red-500'
                            : line.includes('WARN') || line.includes('warn')
                            ? 'text-amber-500'
                            : line.includes('SUCCESS') || line.includes('success')
                            ? 'text-emerald-500'
                            : 'text-muted-foreground'
                        }`}
                      >
                        {line}
                      </div>
                    ))
                  )}
                </div>
              </CardContent>
            </Card>

            {data.recent_events && data.recent_events.length > 0 && (
              <Card>
                <CardContent className="p-6">
                  <h3 className="text-base font-semibold mb-4">最近事件</h3>
                  <div className="space-y-2">
                    {data.recent_events.slice(0, 20).map((event, i) => (
                      <div key={i} className="flex items-start gap-3 p-3 rounded-xl bg-muted/50">
                        <div className="text-xs text-muted-foreground font-mono whitespace-nowrap">
                          {String(event.time || event.timestamp || '')}
                        </div>
                        <div className="text-sm flex-1 min-w-0 truncate">
                          {String(event.message || event.event || JSON.stringify(event))}
                        </div>
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
