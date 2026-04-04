import type { ApiResponse, DashboardData, ResultsData, ControlData, LogsData, SecuritySummary } from './types'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body !== undefined && options.body !== null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(path, {
    ...options,
    headers,
    credentials: 'same-origin',
  })

  if (!res.ok) {
    const body = await res.text()
    let msg = `HTTP ${res.status}`
    try {
      const parsed = JSON.parse(body)
      if (parsed.message) msg = parsed.message
    } catch {
      if (body.trim()) msg = body
    }
    throw new Error(msg)
  }

  return (await res.json()) as T
}

export const api = {
  // Dashboard
  getDashboard: () =>
    request<ApiResponse<DashboardData>>('/api/dashboard').then(r => r.data!),

  // Config
  getConfig: () =>
    request<{ status: string; config: Record<string, unknown> }>('/api/config').then(r => r.config),

  saveConfig: (data: Record<string, unknown>) =>
    request<{ status: string; message: string; config: Record<string, unknown> }>('/api/config', {
      method: 'POST',
      body: JSON.stringify({ config: data }),
    }),

  getConfigSection: (section: string) =>
    request<ApiResponse>(`/api/config/${section}`).then(r => r.data),

  saveConfigSection: (section: string, data: Record<string, unknown>) =>
    request<ApiResponse>(`/api/config/${section}`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Email
  resetEmailWeights: (payload: { all?: boolean; key?: string }) =>
    request<ApiResponse>('/api/email/weights/reset', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  toggleEmailDomain: (key: string, enabled: boolean) =>
    request<ApiResponse>('/api/email/domains/toggle', {
      method: 'POST',
      body: JSON.stringify({ key, enabled }),
    }),

  // Results
  getResults: () =>
    request<ApiResponse<ResultsData>>('/api/results').then(r => r.data!),

  // Security
  getSecurity: () =>
    request<ApiResponse<SecuritySummary>>('/api/security').then(r => r.data!),

  saveSecurity: (data: Record<string, unknown>) =>
    request<ApiResponse>('/api/security', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Logs
  getLogs: (limit = 200) =>
    request<ApiResponse<LogsData>>(`/api/logs?limit=${limit}`).then(r => r.data!),

  // Control
  getControl: () =>
    request<ApiResponse<ControlData>>('/api/control').then(r => r.data!),

  controlAction: (action: string) =>
    request<Record<string, unknown>>(`/api/control/${action}`, { method: 'POST' }),

  // CodexProxy
  testCodexProxy: () =>
    request<ApiResponse>('/api/codex-proxy/test', { method: 'POST' }),

  getCodexProxyAccounts: () =>
    request<ApiResponse>('/api/codex-proxy/accounts').then(r => r.data),

  uploadCodexProxy: (payload: { refresh_tokens?: string; name?: string; refresh_token?: string; name_prefix?: string; proxy_url?: string }) =>
    request<ApiResponse>('/api/codex-proxy/upload', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  deleteCodexProxyAccount: (name: string) =>
    request<ApiResponse>('/api/codex-proxy/accounts/delete', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
}
