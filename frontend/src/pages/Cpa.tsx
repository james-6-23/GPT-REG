import { useCallback, useState } from 'react'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import StateShell from '../components/StateShell'
import ToastNotice from '../components/ToastNotice'
import { useDataLoader } from '../hooks/useDataLoader'
import { useToast } from '../hooks/useToast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import {
  Server, RefreshCw, Trash2, ToggleLeft, ToggleRight, HeartPulse, ChevronLeft, ChevronRight
} from 'lucide-react'
import type { CpaAccount } from '../types'

type Tab = 'overview' | 'accounts' | 'health'

const tabs: { key: Tab; label: string }[] = [
  { key: 'overview', label: '概览' },
  { key: 'accounts', label: '账号列表' },
  { key: 'health', label: '健康检查' },
]

export default function Cpa() {
  const [tab, setTab] = useState<Tab>('overview')
  const { toast, showToast } = useToast()

  return (
    <>
      <ToastNotice toast={toast} />
      <PageHeader title="CPA管理" description="管理 CPA 账号池的连接、同步和健康检查" />

      <div className="flex gap-2 mb-6 flex-wrap">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-xl text-sm font-semibold transition-all ${
              tab === t.key
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'bg-muted text-muted-foreground hover:bg-accent hover:text-foreground'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && <CpaOverview showToast={showToast} />}
      {tab === 'accounts' && <CpaAccounts showToast={showToast} />}
      {tab === 'health' && <CpaHealth showToast={showToast} />}
    </>
  )
}

function CpaOverview({ showToast }: { showToast: (msg: string, type?: 'success' | 'error') => void }) {
  const load = useCallback(() => api.getCpaOverview(), [])
  const { data, loading, error, reload } = useDataLoader<Record<string, unknown> | null>({
    initialData: null,
    load,
  })

  const [syncing, setSyncing] = useState(false)
  const [testing, setTesting] = useState(false)

  const handleTest = async () => {
    setTesting(true)
    try {
      const res = await api.testCpa()
      showToast(res.message || '连接测试成功')
    } catch (err) {
      showToast(err instanceof Error ? err.message : '测试失败', 'error')
    } finally {
      setTesting(false)
    }
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      const res = await api.syncCpa(100)
      showToast(res.message || '同步成功')
      void reload()
    } catch (err) {
      showToast(err instanceof Error ? err.message : '同步失败', 'error')
    } finally {
      setSyncing(false)
    }
  }

  return (
    <StateShell loading={loading} error={error} onRetry={reload}>
      {data && (
        <div className="space-y-6">
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-base font-semibold flex items-center gap-2">
                  <Server className="size-5 text-blue-500" />
                  CPA 连接状态
                </h3>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={handleTest} disabled={testing}>
                    {testing ? <div className="spinner !size-3.5 !border-2" /> : <RefreshCw className="size-3.5" />}
                    测试连接
                  </Button>
                  <Button size="sm" onClick={handleSync} disabled={syncing}>
                    {syncing ? <div className="spinner !size-3.5 !border-2" /> : <RefreshCw className="size-3.5" />}
                    同步账号
                  </Button>
                </div>
              </div>
              <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-4">
                {Object.entries(data).map(([key, value]) => (
                  <div key={key} className="p-4 rounded-xl bg-muted/50">
                    <div className="text-xs text-muted-foreground">{key}</div>
                    <div className="text-sm font-bold mt-1">{typeof value === 'boolean' ? (
                      <Badge variant={value ? 'default' : 'secondary'} className={value ? 'bg-emerald-500 text-white' : ''}>
                        {value ? '是' : '否'}
                      </Badge>
                    ) : String(value ?? '—')}</div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </StateShell>
  )
}

function CpaAccounts({ showToast }: { showToast: (msg: string, type?: 'success' | 'error') => void }) {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const load = useCallback(() => api.getCpaAccounts({ page, per_page: 20, search }), [page, search])
  const { data, loading, error, reload } = useDataLoader({
    initialData: null as Awaited<ReturnType<typeof api.getCpaAccounts>> | null,
    load,
  })

  const toggleSelect = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const handleDelete = async () => {
    if (selected.size === 0) return
    try {
      await api.deleteCpaAccounts(Array.from(selected))
      showToast(`已删除 ${selected.size} 个账号`)
      setSelected(new Set())
      void reload()
    } catch (err) {
      showToast(err instanceof Error ? err.message : '删除失败', 'error')
    }
  }

  const handleToggle = async (names: string[], disabled: boolean) => {
    try {
      await api.toggleCpaAccounts(names, disabled)
      showToast('状态已更新')
      void reload()
    } catch (err) {
      showToast(err instanceof Error ? err.message : '操作失败', 'error')
    }
  }

  const accounts: CpaAccount[] = data?.accounts ?? []
  const pagination = data?.pagination

  return (
    <StateShell loading={loading} error={error} onRetry={reload}>
      <div className="space-y-4">
        <div className="flex items-center gap-3 flex-wrap">
          <Input
            placeholder="搜索账号..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
            className="max-w-[280px]"
          />
          <Button variant="outline" size="sm" onClick={reload}>
            <RefreshCw className="size-3.5" /> 刷新
          </Button>
          {selected.size > 0 && (
            <Button variant="destructive" size="sm" onClick={handleDelete}>
              <Trash2 className="size-3.5" /> 删除 ({selected.size})
            </Button>
          )}
        </div>

        <Card>
          <CardContent className="p-0">
            {accounts.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">暂无账号</div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">
                      <input
                        type="checkbox"
                        checked={selected.size === accounts.length && accounts.length > 0}
                        onChange={e => {
                          if (e.target.checked) setSelected(new Set(accounts.map(a => a.name)))
                          else setSelected(new Set())
                        }}
                        className="rounded"
                      />
                    </TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead>邮箱</TableHead>
                    <TableHead>提供商</TableHead>
                    <TableHead>健康状态</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>优先级</TableHead>
                    <TableHead>操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {accounts.map(account => (
                    <TableRow key={account.name}>
                      <TableCell>
                        <input
                          type="checkbox"
                          checked={selected.has(account.name)}
                          onChange={() => toggleSelect(account.name)}
                          className="rounded"
                        />
                      </TableCell>
                      <TableCell className="font-medium">{account.name}</TableCell>
                      <TableCell>{account.email}</TableCell>
                      <TableCell>{account.provider}</TableCell>
                      <TableCell>
                        <Badge variant={account.health_status === 'healthy' ? 'default' : account.health_status === 'unhealthy' ? 'destructive' : 'secondary'}
                          className={account.health_status === 'healthy' ? 'bg-emerald-500 text-white' : ''}>
                          {account.health_status || '未知'}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant={account.disabled ? 'destructive' : 'default'}
                          className={!account.disabled ? 'bg-emerald-500 text-white' : ''}>
                          {account.disabled ? '已禁用' : '已启用'}
                        </Badge>
                      </TableCell>
                      <TableCell>{account.priority}</TableCell>
                      <TableCell>
                        <button
                          onClick={() => handleToggle([account.name], !account.disabled)}
                          className="p-1.5 rounded-lg hover:bg-accent transition-colors"
                          title={account.disabled ? '启用' : '禁用'}
                        >
                          {account.disabled
                            ? <ToggleLeft className="size-5 text-muted-foreground" />
                            : <ToggleRight className="size-5 text-emerald-500" />}
                        </button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {pagination && pagination.total_pages > 1 && (
          <div className="flex items-center justify-center gap-3">
            <Button variant="outline" size="sm" disabled={!pagination.has_prev} onClick={() => setPage(p => p - 1)}>
              <ChevronLeft className="size-4" /> 上一页
            </Button>
            <span className="text-sm text-muted-foreground">
              第 {pagination.page} / {pagination.total_pages} 页 · 共 {pagination.total} 条
            </span>
            <Button variant="outline" size="sm" disabled={!pagination.has_next} onClick={() => setPage(p => p + 1)}>
              下一页 <ChevronRight className="size-4" />
            </Button>
          </div>
        )}
      </div>
    </StateShell>
  )
}

function CpaHealth({ showToast }: { showToast: (msg: string, type?: 'success' | 'error') => void }) {
  const load = useCallback(() => api.getHealthStatus(), [])
  const { data, loading, error, reload } = useDataLoader<Record<string, unknown> | null>({
    initialData: null,
    load,
  })

  const [starting, setStarting] = useState(false)

  const handleStart = async () => {
    setStarting(true)
    try {
      const res = await api.startHealthTask({})
      showToast(res.message || '健康检查已启动')
      setTimeout(() => void reload(), 2000)
    } catch (err) {
      showToast(err instanceof Error ? err.message : '启动失败', 'error')
    } finally {
      setStarting(false)
    }
  }

  return (
    <StateShell loading={loading} error={error} onRetry={reload}>
      <div className="space-y-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold flex items-center gap-2">
                <HeartPulse className="size-5 text-red-500" />
                健康检查
              </h3>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={reload}>
                  <RefreshCw className="size-3.5" /> 刷新
                </Button>
                <Button size="sm" onClick={handleStart} disabled={starting}>
                  {starting ? <div className="spinner !size-3.5 !border-2" /> : <HeartPulse className="size-3.5" />}
                  启动检查
                </Button>
              </div>
            </div>
            {data ? (
              <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-4">
                {Object.entries(data).map(([key, value]) => (
                  <div key={key} className="p-4 rounded-xl bg-muted/50">
                    <div className="text-xs text-muted-foreground">{key}</div>
                    <div className="text-sm font-bold mt-1">{String(value ?? '—')}</div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">暂无健康检查数据</p>
            )}
          </CardContent>
        </Card>
      </div>
    </StateShell>
  )
}
