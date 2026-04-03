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
import { Save, Shield, Lock, Key, Clock, Globe } from 'lucide-react'
import type { SecuritySummary } from '../types'

export default function Security() {
  const { toast, showToast } = useToast()

  const load = useCallback(() => api.getSecurity(), [])
  const { data, loading, error, reload } = useDataLoader<SecuritySummary | null>({
    initialData: null,
    load,
  })

  const [form, setForm] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.saveSecurity(form)
      showToast('安全设置已保存')
      setForm({})
      void reload()
    } catch (err) {
      showToast(err instanceof Error ? err.message : '保存失败', 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <ToastNotice toast={toast} />
      <PageHeader title="安全设置" description="管理登录凭证、会话和安全策略" onRefresh={reload} />

      <StateShell variant="page" loading={loading} error={error} onRetry={reload}>
        {data && (
          <div className="space-y-6">
            <Card>
              <CardContent className="p-6">
                <h3 className="text-base font-semibold mb-4 flex items-center gap-2">
                  <Shield className="size-5 text-blue-500" />
                  安全概览
                </h3>
                <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
                  <StatusItem icon={<Lock className="size-5" />} label="用户名" value={data.username} />
                  <StatusItem icon={<Key className="size-5" />} label="密码哈希" value={
                    <Badge variant={data.password_hash_set ? 'default' : 'destructive'} className={data.password_hash_set ? 'bg-emerald-500 text-white' : ''}>
                      {data.password_hash_set ? '已设置' : '未设置'}
                    </Badge>
                  } />
                  <StatusItem icon={<Key className="size-5" />} label="API Token" value={
                    <Badge variant={data.api_token_set ? 'default' : 'secondary'} className={data.api_token_set ? 'bg-emerald-500 text-white' : ''}>
                      {data.api_token_set ? '已设置' : '未设置'}
                    </Badge>
                  } />
                  <StatusItem icon={<Clock className="size-5" />} label="会话时长" value={`${data.session_minutes} 分钟`} />
                  <StatusItem icon={<Shield className="size-5" />} label="CSRF保护" value={
                    <Badge variant={data.csrf_enabled ? 'default' : 'secondary'} className={data.csrf_enabled ? 'bg-emerald-500 text-white' : ''}>
                      {data.csrf_enabled ? '已启用' : '已禁用'}
                    </Badge>
                  } />
                  <StatusItem icon={<Globe className="size-5" />} label="速率限制" value={`${data.login_rate_limit}次/${data.login_window_seconds}秒`} />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="p-6 space-y-4">
                <h3 className="text-base font-semibold mb-2">修改凭证</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm font-medium text-foreground mb-1.5 block">新用户名</label>
                    <Input
                      placeholder="留空不修改"
                      value={form.username ?? ''}
                      onChange={e => setForm(prev => ({ ...prev, username: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium text-foreground mb-1.5 block">新密码</label>
                    <Input
                      type="password"
                      placeholder="留空不修改"
                      value={form.password ?? ''}
                      onChange={e => setForm(prev => ({ ...prev, password: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium text-foreground mb-1.5 block">API Token</label>
                    <Input
                      placeholder="留空不修改"
                      value={form.api_token ?? ''}
                      onChange={e => setForm(prev => ({ ...prev, api_token: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium text-foreground mb-1.5 block">会话时长(分钟)</label>
                    <Input
                      type="number"
                      placeholder={String(data.session_minutes)}
                      value={form.session_minutes ?? ''}
                      onChange={e => setForm(prev => ({ ...prev, session_minutes: e.target.value }))}
                    />
                  </div>
                </div>
                <div className="pt-4 border-t border-border">
                  <Button onClick={handleSave} disabled={saving}>
                    <Save className="size-4" />
                    {saving ? '保存中…' : '保存设置'}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </StateShell>
    </>
  )
}

function StatusItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 p-4 rounded-xl bg-muted/50">
      <div className="flex items-center justify-center size-10 rounded-lg bg-blue-500/10 text-blue-500">
        {icon}
      </div>
      <div className="min-w-0">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="text-sm font-bold mt-0.5">{value}</div>
      </div>
    </div>
  )
}
