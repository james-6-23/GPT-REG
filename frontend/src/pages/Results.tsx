import { useCallback } from 'react'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import StateShell from '../components/StateShell'
import { useDataLoader } from '../hooks/useDataLoader'
import { Card, CardContent } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { FileText, User } from 'lucide-react'
import type { ResultsData } from '../types'

export default function Results() {
  const load = useCallback(() => api.getResults(), [])
  const { data, loading, error, reload } = useDataLoader<ResultsData | null>({
    initialData: null,
    load,
  })

  return (
    <>
      <PageHeader title="结果概览" description="查看最近注册的 Token 和账号信息" onRefresh={reload} />

      <StateShell variant="page" loading={loading} error={error} onRetry={reload}>
        {data && (
          <div className="space-y-6">
            <Card>
              <CardContent className="p-6">
                <h3 className="text-base font-semibold mb-4 flex items-center gap-2">
                  <FileText className="size-5 text-blue-500" />
                  最近 Token 文件 ({data.recent_tokens.length})
                </h3>
                {data.recent_tokens.length === 0 ? (
                  <p className="text-sm text-muted-foreground">暂无 Token 文件</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>文件名</TableHead>
                        <TableHead>大小</TableHead>
                        <TableHead>修改时间</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.recent_tokens.map((t, i) => (
                        <TableRow key={i}>
                          <TableCell className="font-medium">{t.filename}</TableCell>
                          <TableCell>{formatSize(t.size)}</TableCell>
                          <TableCell className="text-muted-foreground">{t.modified}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-6">
                <h3 className="text-base font-semibold mb-4 flex items-center gap-2">
                  <User className="size-5 text-emerald-500" />
                  最近账号 ({data.recent_accounts.length})
                </h3>
                {data.recent_accounts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">暂无账号记录</p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>邮箱</TableHead>
                        <TableHead>密码</TableHead>
                        <TableHead>Token</TableHead>
                        <TableHead>创建时间</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.recent_accounts.map((a, i) => (
                        <TableRow key={i}>
                          <TableCell className="font-medium">{a.email}</TableCell>
                          <TableCell className="font-mono text-xs">{a.password}</TableCell>
                          <TableCell className="font-mono text-xs max-w-[200px] truncate">{a.token || '—'}</TableCell>
                          <TableCell className="text-muted-foreground">{a.created_at}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </StateShell>
    </>
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
