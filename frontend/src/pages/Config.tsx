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

type Tab = 'basic' | 'email' | 'email-domains' | 'network' | 'cpa' | 'codex-proxy' | 'runtime'

const tabs: { key: Tab; label: string }[] = [
  { key: 'basic', label: '基础配置' },
  { key: 'email', label: '邮箱设置' },
  { key: 'email-domains', label: '邮箱域名' },
  { key: 'network', label: '网络设置' },
  { key: 'cpa', label: 'CPA连接' },
  { key: 'codex-proxy', label: 'CodexProxy' },
  { key: 'runtime', label: '运行设置' },
]

// ─── 通用字段组件 ───

function Field({ label, desc, children }: { label: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b border-border last:border-0">
      <div className="min-w-0">
        <div className="text-sm font-medium text-foreground">{label}</div>
        {desc && <div className="text-xs text-muted-foreground mt-0.5">{desc}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function NumberField({ label, desc, value, onChange, min, max }: {
  label: string; desc?: string; value: number; onChange: (v: number) => void; min?: number; max?: number
}) {
  return (
    <Field label={label} desc={desc}>
      <Input type="number" value={value} min={min} max={max} onChange={e => onChange(Number(e.target.value))} className="w-[140px]" />
    </Field>
  )
}

function TextField({ label, desc, value, onChange, placeholder }: {
  label: string; desc?: string; value: string; onChange: (v: string) => void; placeholder?: string
}) {
  return (
    <Field label={label} desc={desc}>
      <Input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} className="w-[280px]" />
    </Field>
  )
}

function ToggleField({ label, desc, value, onChange }: {
  label: string; desc?: string; value: boolean; onChange: (v: boolean) => void
}) {
  return (
    <Field label={label} desc={desc}>
      <button
        onClick={() => onChange(!value)}
        className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-sm font-semibold transition-colors ${
          value ? 'bg-emerald-500/10 text-emerald-600' : 'bg-muted text-muted-foreground'
        }`}
      >
        {value ? <ToggleRight className="size-4" /> : <ToggleLeft className="size-4" />}
        {value ? '启用' : '禁用'}
      </button>
    </Field>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="text-base font-semibold text-foreground pt-4 pb-2 first:pt-0">{children}</h3>
}

// ─── 辅助：安全读取嵌套字段 ───

function get(obj: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce((o: any, k) => (o && typeof o === 'object' ? o[k] : undefined), obj)
}

function set(obj: Record<string, unknown>, path: string, value: unknown): Record<string, unknown> {
  const draft = JSON.parse(JSON.stringify(obj))
  const keys = path.split('.')
  let cur = draft
  for (let i = 0; i < keys.length - 1; i++) {
    if (!cur[keys[i]] || typeof cur[keys[i]] !== 'object') cur[keys[i]] = {}
    cur = cur[keys[i]]
  }
  cur[keys[keys.length - 1]] = value
  return draft
}

// ─── 各 Tab 专用表单 ───

function BasicForm({ data, onChange }: { data: Record<string, unknown>; onChange: (d: Record<string, unknown>) => void }) {
  const s = (p: string, v: unknown) => onChange(set(data, p, v))
  return (
    <>
      <SectionTitle>WebUI 服务</SectionTitle>
      <TextField label="监听地址" desc="WebUI 绑定的 IP，0.0.0.0 允许外部访问" value={String(get(data, 'webui.host') ?? '127.0.0.1')} onChange={v => s('webui.host', v)} placeholder="127.0.0.1" />
      <NumberField label="端口" desc="WebUI 监听端口" value={Number(get(data, 'webui.port') ?? 5050)} onChange={v => s('webui.port', v)} min={1} max={65535} />
    </>
  )
}

function EmailForm({ data, onChange }: { data: Record<string, unknown>; onChange: (d: Record<string, unknown>) => void }) {
  const s = (p: string, v: unknown) => onChange(set(data, p, v))
  return (
    <>
      <SectionTitle>邮箱选择</SectionTitle>
      <Field label="选择模式" desc="random_enabled = 加权随机，first_enabled = 选第一个启用的">
        <select
          value={String(get(data, 'email.selection_mode') ?? 'random_enabled')}
          onChange={e => s('email.selection_mode', e.target.value)}
          className="w-[200px] h-9 px-3 rounded-lg border border-input bg-background text-sm"
        >
          <option value="random_enabled">加权随机</option>
          <option value="first_enabled">优先选择</option>
        </select>
      </Field>

      <SectionTitle>OTP 验证码</SectionTitle>
      <NumberField label="等待超时 (秒)" desc="首次等待验证码的最大时间" value={Number(get(data, 'email.otp.wait_timeout_seconds') ?? 120)} onChange={v => s('email.otp.wait_timeout_seconds', v)} min={10} />
      <NumberField label="重试超时 (秒)" desc="验证码失败后重试等待时间" value={Number(get(data, 'email.otp.retry_wait_timeout_seconds') ?? 60)} onChange={v => s('email.otp.retry_wait_timeout_seconds', v)} min={10} />

      <SectionTitle>权重评分</SectionTitle>
      <NumberField label="默认分数" value={Number(get(data, 'email.weight.default_score') ?? 100)} onChange={v => s('email.weight.default_score', v)} min={1} />
      <NumberField label="最低分数" value={Number(get(data, 'email.weight.min_score') ?? 20)} onChange={v => s('email.weight.min_score', v)} min={1} />
      <NumberField label="最高分数" value={Number(get(data, 'email.weight.max_score') ?? 200)} onChange={v => s('email.weight.max_score', v)} min={1} />
      <NumberField label="成功加分" desc="每次成功后增加的分数" value={Number(get(data, 'email.weight.success_delta') ?? 8)} onChange={v => s('email.weight.success_delta', v)} min={1} />
      <NumberField label="失败扣分" desc="每次失败后扣除的分数" value={Number(get(data, 'email.weight.failure_delta') ?? 20)} onChange={v => s('email.weight.failure_delta', v)} min={1} />
    </>
  )
}

function NetworkForm({ data, onChange }: { data: Record<string, unknown>; onChange: (d: Record<string, unknown>) => void }) {
  const s = (p: string, v: unknown) => onChange(set(data, p, v))
  return (
    <>
      <SectionTitle>网络代理</SectionTitle>
      <ToggleField label="启用代理" desc="注册请求是否走代理" value={Boolean(get(data, 'network.enabled'))} onChange={v => s('network.enabled', v)} />
      <TextField label="代理地址" desc="HTTP(S) 代理 URL" value={String(get(data, 'network.proxy') ?? '')} onChange={v => s('network.proxy', v)} placeholder="http://127.0.0.1:7890" />
    </>
  )
}

function CpaForm({ data, onChange }: { data: Record<string, unknown>; onChange: (d: Record<string, unknown>) => void }) {
  const s = (p: string, v: unknown) => onChange(set(data, p, v))
  return (
    <>
      <SectionTitle>CPA 连接</SectionTitle>
      <ToggleField label="启用 CPA" desc="开启后注册成功的 Token 自动同步到 CPA 站点" value={Boolean(get(data, 'cpa.enabled'))} onChange={v => s('cpa.enabled', v)} />
      <TextField label="管理地址" desc="CPA 站点的管理 URL" value={String(get(data, 'cpa.management_url') ?? '')} onChange={v => s('cpa.management_url', v)} placeholder="https://your-cpa-site.com" />
      <TextField label="管理 Token" desc="CPA 站点的认证 Token" value={String(get(data, 'cpa.management_token') ?? '')} onChange={v => s('cpa.management_token', v)} />

      <SectionTitle>上传代理</SectionTitle>
      <Field label="上传代理模式" desc="Token 上传时使用的代理策略">
        <select
          value={String(get(data, 'cpa.upload_proxy_mode') ?? 'default')}
          onChange={e => s('cpa.upload_proxy_mode', e.target.value)}
          className="w-[160px] h-9 px-3 rounded-lg border border-input bg-background text-sm"
        >
          <option value="default">默认</option>
          <option value="direct">直连</option>
          <option value="custom">自定义</option>
        </select>
      </Field>
      <TextField label="自定义代理" desc="upload_proxy_mode = custom 时使用" value={String(get(data, 'cpa.custom_proxy') ?? '')} onChange={v => s('cpa.custom_proxy', v)} />
      <NumberField label="超时 (秒)" value={Number(get(data, 'cpa.timeout') ?? 15)} onChange={v => s('cpa.timeout', v)} min={1} />

      <SectionTitle>健康探测</SectionTitle>
      <ToggleField label="主动探测" desc="是否主动检测远程账号健康状态" value={Boolean(get(data, 'cpa.active_probe'))} onChange={v => s('cpa.active_probe', v)} />
      <Field label="探测模式" desc="auto = OpenAI + Codex 双探测">
        <select
          value={String(get(data, 'cpa.health_probe_mode') ?? 'auto')}
          onChange={e => s('cpa.health_probe_mode', e.target.value)}
          className="w-[140px] h-9 px-3 rounded-lg border border-input bg-background text-sm"
        >
          <option value="auto">自动</option>
          <option value="openai">OpenAI</option>
          <option value="codex">Codex</option>
        </select>
      </Field>
      <NumberField label="探测超时 (秒)" value={Number(get(data, 'cpa.probe_timeout') ?? 8)} onChange={v => s('cpa.probe_timeout', v)} min={1} />
      <NumberField label="探测并发数" value={Number(get(data, 'cpa.probe_workers') ?? 12)} onChange={v => s('cpa.probe_workers', v)} min={1} />
      <NumberField label="删除并发数" value={Number(get(data, 'cpa.delete_workers') ?? 8)} onChange={v => s('cpa.delete_workers', v)} min={1} />
      <NumberField label="最大探测数" desc="0 = 不限制" value={Number(get(data, 'cpa.max_active_probes') ?? 120)} onChange={v => s('cpa.max_active_probes', v)} min={0} />
      <ToggleField label="成功后自动同步" value={Boolean(get(data, 'cpa.auto_sync_on_success'))} onChange={v => s('cpa.auto_sync_on_success', v)} />
    </>
  )
}

function CodexProxyForm({ data, onChange }: { data: Record<string, unknown>; onChange: (d: Record<string, unknown>) => void }) {
  const s = (p: string, v: unknown) => onChange(set(data, p, v))
  return (
    <>
      <SectionTitle>CodexProxy 连接</SectionTitle>
      <ToggleField label="启用 CodexProxy" desc="开启后注册成功的 refresh_token 自动上传到 CodexProxy 号池" value={Boolean(get(data, 'codex_proxy.enabled'))} onChange={v => s('codex_proxy.enabled', v)} />
      <TextField label="服务地址" desc="CodexProxy 的 API 地址" value={String(get(data, 'codex_proxy.base_url') ?? '')} onChange={v => s('codex_proxy.base_url', v)} placeholder="http://host:port" />
      <TextField label="Admin Key" desc="X-Admin-Key 认证密钥" value={String(get(data, 'codex_proxy.admin_key') ?? '')} onChange={v => s('codex_proxy.admin_key', v)} />
      <TextField label="上传代理" desc="上传时使用的代理地址（留空则跟随全局代理）" value={String(get(data, 'codex_proxy.upload_proxy_url') ?? '')} onChange={v => s('codex_proxy.upload_proxy_url', v)} placeholder="http://127.0.0.1:7890" />
      <ToggleField label="成功后自动上传" desc="注册成功后自动将 refresh_token 上传到 CodexProxy" value={Boolean(get(data, 'codex_proxy.auto_sync_on_success'))} onChange={v => s('codex_proxy.auto_sync_on_success', v)} />
      <NumberField label="超时 (秒)" value={Number(get(data, 'codex_proxy.timeout') ?? 15)} onChange={v => s('codex_proxy.timeout', v)} min={1} />
    </>
  )
}

function RuntimeForm({ data, onChange }: { data: Record<string, unknown>; onChange: (d: Record<string, unknown>) => void }) {
  const s = (p: string, v: unknown) => onChange(set(data, p, v))
  return (
    <>
      <SectionTitle>运行参数</SectionTitle>
      <NumberField label="并发数" desc="同时运行的注册 Worker 数量" value={Number(get(data, 'run.workers') ?? 1)} onChange={v => s('run.workers', v)} min={1} />
      <NumberField label="目标数量" desc="注册成功多少个后停止，0 = 不限" value={Number(get(data, 'run.max_success') ?? 0)} onChange={v => s('run.max_success', v)} min={0} />
      <ToggleField label="单次模式" desc="开启后每个 Worker 只注册一次" value={Boolean(get(data, 'run.once'))} onChange={v => s('run.once', v)} />

      <SectionTitle>注册间隔</SectionTitle>
      <NumberField label="最小间隔 (秒)" desc="两次注册之间的最短等待时间" value={Number(get(data, 'run.sleep_min') ?? 5)} onChange={v => s('run.sleep_min', v)} min={1} />
      <NumberField label="最大间隔 (秒)" desc="两次注册之间的最长等待时间" value={Number(get(data, 'run.sleep_max') ?? 30)} onChange={v => s('run.sleep_max', v)} min={1} />

      <SectionTitle>OTP 超时</SectionTitle>
      <NumberField label="等待超时 (秒)" value={Number(get(data, 'email.otp.wait_timeout_seconds') ?? 120)} onChange={v => s('email.otp.wait_timeout_seconds', v)} min={10} />
      <NumberField label="重试超时 (秒)" value={Number(get(data, 'email.otp.retry_wait_timeout_seconds') ?? 60)} onChange={v => s('email.otp.retry_wait_timeout_seconds', v)} min={10} />
    </>
  )
}

// ─── 主组件 ───

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

  const renderForm = () => {
    if (!currentData) return null
    const onChange = (d: Record<string, unknown>) => setFormData(d)
    switch (tab) {
      case 'basic': return <BasicForm data={currentData} onChange={onChange} />
      case 'email': return <EmailForm data={currentData} onChange={onChange} />
      case 'network': return <NetworkForm data={currentData} onChange={onChange} />
      case 'cpa': return <CpaForm data={currentData} onChange={onChange} />
      case 'codex-proxy': return <CodexProxyForm data={currentData} onChange={onChange} />
      case 'runtime': return <RuntimeForm data={currentData} onChange={onChange} />
      default: return null
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
              <CardContent className="p-6">
                {renderForm()}
                <div className="flex gap-3 pt-5 mt-4 border-t border-border">
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

// ─── 邮箱域名 Tab ───

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
