import type { ApiResponse, DashboardData, ResultsData, ControlData, LogsData, SecuritySummary, CpaAccountsData } from './types'

export const AUTH_REQUIRED_EVENT = 'reggpt:auth-required'

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

  if (res.status === 401 || res.status === 302) {
    window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT))
    throw new Error('登录已过期，请重新登录')
  }

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
  // Auth
  login: (username: string, password: string, _csrfToken?: string) =>
    fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      credentials: 'same-origin',
    }),

  logout: (_csrfToken?: string) =>
    fetch('/api/logout', {
      method: 'POST',
      credentials: 'same-origin',
    }),

  checkAuth: () =>
    fetch('/api/auth/check', { credentials: 'same-origin' }).then(res => res.ok),

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

  // CPA
  getCpaOverview: () =>
    request<ApiResponse>('/api/cpa/overview').then(r => r.data),

  getCpaAccounts: (params: Record<string, string | number | boolean>) => {
    const sp = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== undefined) sp.set(k, String(v))
    })
    return request<ApiResponse<CpaAccountsData>>(`/api/cpa/accounts?${sp.toString()}`).then(r => r.data!)
  },

  testCpa: () =>
    request<ApiResponse>('/api/cpa/test', { method: 'POST' }),

  syncCpa: (limit: number) =>
    request<ApiResponse>('/api/cpa/sync', {
      method: 'POST',
      body: JSON.stringify({ limit }),
    }),

  startHealthTask: (payload: { names?: string[]; cleanup?: boolean }) =>
    request<ApiResponse>('/api/cpa/health/start', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getHealthStatus: () =>
    request<ApiResponse>('/api/cpa/health/status'),

  cleanupHealth: (names?: string[]) =>
    request<ApiResponse>('/api/cpa/health/cleanup', {
      method: 'POST',
      body: JSON.stringify({ names }),
    }),

  deleteCpaAccounts: (names: string[]) =>
    request<ApiResponse>('/api/cpa/accounts/delete', {
      method: 'POST',
      body: JSON.stringify({ names }),
    }),

  toggleCpaAccounts: (names: string[], disabled: boolean) =>
    request<ApiResponse>('/api/cpa/accounts/toggle', {
      method: 'POST',
      body: JSON.stringify({ names, disabled }),
    }),

  updateCpaAccountFields: (name: string, priority?: number, note?: string) =>
    request<ApiResponse>('/api/cpa/accounts/fields', {
      method: 'POST',
      body: JSON.stringify({ name, priority, note }),
    }),

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
}
