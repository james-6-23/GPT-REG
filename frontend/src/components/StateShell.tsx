import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { AlertCircle, Inbox } from 'lucide-react'

interface StateShellProps {
  children: ReactNode
  loading?: boolean
  error?: string | null
  isEmpty?: boolean
  onRetry?: () => void
  action?: ReactNode
  variant?: 'page' | 'section'
  loadingTitle?: string
  loadingDescription?: string
  errorTitle?: string
  emptyTitle?: string
  emptyDescription?: string
}

export default function StateShell({
  children,
  loading = false,
  error,
  isEmpty = false,
  onRetry,
  action,
  variant = 'section',
  loadingTitle,
  loadingDescription,
  errorTitle,
  emptyTitle,
  emptyDescription,
}: StateShellProps) {
  const minH = variant === 'page' ? 'min-h-[320px]' : 'min-h-[220px]'

  if (loading) {
    return (
      <div className={`flex flex-col items-center justify-center gap-3 p-10 border border-border rounded-3xl bg-white/40 text-center ${minH}`} role="status" aria-live="polite">
        <div className="size-16 flex items-center justify-center rounded-full bg-white/60">
          <div className="spinner" />
        </div>
        <strong className="text-lg font-bold text-foreground">{loadingTitle ?? '加载中'}</strong>
        <p className="max-w-[420px] text-sm leading-relaxed text-muted-foreground">{loadingDescription ?? '正在同步数据…'}</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`flex flex-col items-center justify-center gap-3 p-10 border border-border rounded-3xl bg-white/40 text-center ${minH}`} role="alert">
        <div className="size-16 flex items-center justify-center rounded-full bg-destructive/12 text-destructive">
          <AlertCircle className="size-6" />
        </div>
        <strong className="text-lg font-bold text-foreground">{errorTitle ?? '加载失败'}</strong>
        <p className="max-w-[420px] text-sm leading-relaxed text-muted-foreground">{error}</p>
        {(onRetry || action) ? (
          <div className="flex items-center justify-center gap-2.5 flex-wrap">
            {onRetry ? <Button variant="outline" onClick={onRetry}>重试</Button> : null}
            {action}
          </div>
        ) : null}
      </div>
    )
  }

  if (isEmpty) {
    return (
      <div className={`flex flex-col items-center justify-center gap-3 p-10 border border-border rounded-3xl bg-white/40 text-center ${minH}`}>
        <div className="size-16 flex items-center justify-center rounded-full bg-[hsl(var(--info-bg))] text-[hsl(var(--info))]">
          <Inbox className="size-6" />
        </div>
        <strong className="text-lg font-bold text-foreground">{emptyTitle ?? '暂无数据'}</strong>
        <p className="max-w-[420px] text-sm leading-relaxed text-muted-foreground">{emptyDescription ?? '暂无内容'}</p>
        {action ? <div className="flex items-center justify-center gap-2.5 flex-wrap">{action}</div> : null}
      </div>
    )
  }

  return <>{children}</>
}
