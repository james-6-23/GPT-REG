import { useCallback, useState } from 'react'
import { api } from '../api'
import PageHeader from '../components/PageHeader'
import StateShell from '../components/StateShell'
import ToastNotice from '../components/ToastNotice'
import { useDataLoader } from '../hooks/useDataLoader'
import { useToast } from '../hooks/useToast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Save, RotateCcw, ToggleLeft, ToggleRight } from 'lucide-react'
import type { DomainWeightItem } from '../types'

type Tab = 'basic' | 'email' | 'email-domains' | 'network' | 'cpa' | 'runtime'

const tabs: { key: Tab; label: string }[] = [
  { key: 'basic', label: '基础配置' },
  { key: 'email', label: '邮箱设置' },
  { key: 'email-domains', label: '邮箱域名' },
  { key: 'network', label: '网络设置' },
  { key: 'cpa', label: 'CPA连接' },
  { key: 'runtime', label: '运行设置' },
]

export default function Config() {
  const [tab, setTab] = useState<Tab>('basic')
  const { toast, showToast } = useToast()

  const load = useCallback(() => api.getConfigSection(tab), [tab])
  const { data, loading, error, reload } = useDataLoader<Record<string, unknown> | null>({
    initialData: null,
    load,
  })

  const [saving, setSaving] = useState(false)
  const [formData, setFormData] = useState<Record<string, unknown> | null>(null)

  const currentData = formData ?? data

  const handleFieldChange = (path: string, value: unknown) => {
    const draft = JSON.parse(JSON.stringify(currentData || {}))
    const keys = path.split('.')
    let obj = draft
    for (let i = 0; i < keys.length - 1; i++) {
      if (!obj[keys[i]]) obj[keys[i]] = {}
      obj = obj[keys[i]]
    }
    obj[keys[keys.length - 1]] = value
    setFormData(draft)
  }

  const handleSave = async () => {
    if (!currentData) return
    setSaving(true)
    try {
      await api.saveConfigSection(tab, currentData as Record<string, unknown>)
      showToast('配置已保存')
      setFormData(null)
      void reload()
    } catch (err) {
      showToast(err instanceof Error ? err.message : '保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  const handleResetWeights = async (key?: string) => {
    try {
      await api.resetEmailWeights(key ? { key } : { all: true })
      showToast(key ? '邮箱权重已重置' : '所有邮箱权重已重置')
      void reload()
    } catch (err) {
      showToast(err instanceof Error ? err.message : '重置失败', 'error')
    }
  }

  const handleToggleDomain = async (key: string, enabled: boolean) => {
    try {
      await api.toggleEmailDomain(key, enabled)
      showToast('域名状态已更新')
      void reload()
    } catch (err) {
      showToast(err instanceof Error ? err.message : '操作失败', 'error')
    }
  }

  return (
    <>
      <ToastNotice toast={toast} />
      <PageHeader title="配置中心" description="管理 Reg-GPT 的所有配置项" onRefresh={() => { setFormData(null); void reload() }} />

      <div className="flex gap-2 mb-6 flex-wrap">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => { setTab(t.key); setFormData(null) }}
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

      <StateShell loading={loading} error={error} onRetry={reload}>
        <>
          {tab === 'email-domains' ? (
            <EmailDomainsSection
              data={currentData}
              onResetWeights={handleResetWeights}
              onToggleDomain={handleToggleDomain}
            />
          ) : (
            <Card>
              <CardContent className="p-6 space-y-4">
                {currentData && renderFields(currentData, '', handleFieldChange)}
                <div className="flex gap-3 pt-4 border-t border-border">
                  <Button onClick={handleSave} disabled={saving}>
                    <Save className="size-4" />
                    {saving ? '保存中…' : '保存配置'}
                  </Button>
                  <Button variant="outline" onClick={() => { setFormData(null); void reload() }}>
                    <RotateCcw className="size-4" />
                    重置
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      </StateShell>
    </>
  )
}

function renderFields(
  data: Record<string, unknown>,
  prefix: string,
  onChange: (path: string, value: unknown) => void,
  depth = 0
): React.ReactNode {
  const skipKeys = ['providers', 'enabled_count', 'config_path', 'domain_weight_items', 'domain_weight_summary']
  return Object.entries(data).map(([key, value]) => {
    if (skipKeys.includes(key)) return null
    const path = prefix ? `${prefix}.${key}` : key

    if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      return (
        <div key={path} className={depth > 0 ? 'ml-4 pl-4 border-l border-border' : ''}>
          <h4 className="text-sm font-semibold text-foreground mb-3 mt-2">{key}</h4>
          {renderFields(value as Record<string, unknown>, path, onChange, depth + 1)}
        </div>
      )
    }

    if (typeof value === 'boolean') {
      return (
        <div key={path} className="flex items-center justify-between py-2">
          <label className="text-sm text-foreground">{key}</label>
          <button
            onClick={() => onChange(path, !value)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              value ? 'bg-emerald-500/10 text-emerald-600' : 'bg-muted text-muted-foreground'
            }`}
          >
            {value ? '启用' : '禁用'}
          </button>
        </div>
      )
    }

    if (typeof value === 'number') {
      return (
        <div key={path} className="flex items-center justify-between gap-4 py-2">
          <label className="text-sm text-foreground shrink-0">{key}</label>
          <Input
            type="number"
            value={value}
            onChange={e => onChange(path, Number(e.target.value))}
            className="max-w-[200px]"
          />
        </div>
      )
    }

    return (
      <div key={path} className="flex items-center justify-between gap-4 py-2">
        <label className="text-sm text-foreground shrink-0">{key}</label>
        <Input
          type="text"
          value={String(value ?? '')}
          onChange={e => onChange(path, e.target.value)}
          className="max-w-[400px]"
        />
      </div>
    )
  })
}

function EmailDomainsSection({
  data,
  onResetWeights,
  onToggleDomain,
}: {
  data: Record<string, unknown> | null
  onResetWeights: (key?: string) => void
  onToggleDomain: (key: string, enabled: boolean) => void
}) {
  const items = (data?.domain_weight_items ?? []) as DomainWeightItem[]
  const summary = (data?.domain_weight_summary ?? {}) as Record<string, number>

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-base font-semibold">域名权重概览</h3>
            <Button variant="outline" size="sm" onClick={() => onResetWeights()}>
              <RotateCcw className="size-3.5" />
              重置所有权重
            </Button>
          </div>
          <div className="grid grid-cols-4 gap-4">
            <div className="p-3 rounded-xl bg-muted/50 text-center">
              <div className="text-xs text-muted-foreground">总数</div>
              <div className="text-lg font-bold">{summary.total ?? 0}</div>
            </div>
            <div className="p-3 rounded-xl bg-emerald-500/10 text-center">
              <div className="text-xs text-muted-foreground">启用</div>
              <div className="text-lg font-bold text-emerald-600">{summary.enabled ?? 0}</div>
            </div>
            <div className="p-3 rounded-xl bg-red-500/10 text-center">
              <div className="text-xs text-muted-foreground">禁用</div>
              <div className="text-lg font-bold text-red-600">{summary.disabled ?? 0}</div>
            </div>
            <div className="p-3 rounded-xl bg-blue-500/10 text-center">
              <div className="text-xs text-muted-foreground">平均分</div>
              <div className="text-lg font-bold text-blue-600">{summary.avg_score ?? 0}</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-6">
          <h3 className="text-base font-semibold mb-4">域名列表</h3>
          {items.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无域名权重记录</p>
          ) : (
            <div className="space-y-2">
              {items.map(item => (
                <div key={item.key} className="flex items-center justify-between p-3 rounded-xl bg-muted/50 gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium truncate">{item.label || item.key}</div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      得分: {item.score} · 上次: {item.last_result || '—'} · 更新: {item.updated_at || '—'}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant={item.disabled ? 'destructive' : 'default'} className={!item.disabled ? 'bg-emerald-500 text-white' : ''}>
                      {item.disabled ? '已禁用' : '已启用'}
                    </Badge>
                    <button
                      onClick={() => onToggleDomain(item.key, item.disabled)}
                      className="p-1.5 rounded-lg hover:bg-accent transition-colors"
                      title={item.disabled ? '启用' : '禁用'}
                    >
                      {item.disabled ? <ToggleLeft className="size-5 text-muted-foreground" /> : <ToggleRight className="size-5 text-emerald-500" />}
                    </button>
                    <button
                      onClick={() => onResetWeights(item.key)}
                      className="p-1.5 rounded-lg hover:bg-accent transition-colors"
                      title="重置权重"
                    >
                      <RotateCcw className="size-4 text-muted-foreground" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
