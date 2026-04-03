export type ToastType = 'success' | 'error'

export interface ToastState {
  msg: string
  type: ToastType
}

export interface DashboardSummary {
  proxy: string
  email_enabled: number
  workers: number
  max_success: number
  sleep_window: string
  token_count: number
  accounts_count: number
  config_updated_at: string
  attempts: number
  successes: number
  failures: number
}

export interface DashboardRuntime {
  running: boolean
  mode: string
  message: string
  pid: number | null
  started_at: string
  last_exit_code: number | null
  phase: string
  workers_active: number
  last_email: string
}

export interface DashboardPaths {
  script_dir: string
  runtime_root: string
  entry_script: string
  config_path: string
  token_dir: string
  accounts_csv: string
  runtime_log: string
  runtime_state: string
}

export interface TokenItem {
  filename: string
  size: number
  modified: string
  path: string
}

export interface DashboardData {
  summary: DashboardSummary
  runtime: DashboardRuntime
  paths: DashboardPaths
  recent_tokens: TokenItem[]
}

export interface AccountRow {
  email: string
  password: string
  token: string
  created_at: string
}

export interface ResultsData {
  recent_tokens: TokenItem[]
  recent_accounts: AccountRow[]
}

export interface ControlAction {
  id: string
  label: string
  enabled: boolean
  variant: string
}

export interface WorkerSlot {
  worker_id: number
  lines: string[]
  phase?: string
  email?: string
  started_at?: string
}

export interface ControlData {
  running: boolean
  message: string
  pid: number | null
  started_at: string
  last_exit_code: number | null
  phase: string
  attempts: number
  successes: number
  failures: number
  actions: ControlAction[]
  worker_slots: WorkerSlot[]
}

export interface LogsData {
  lines: string[]
  recent_events: Array<Record<string, unknown>>
  running: boolean
  phase: string
  updated_at: string
  log_file: string
  state_file: string
}

export interface EmailProvider {
  type: string
  label: string
  enabled: boolean
  [key: string]: unknown
}

export interface DomainWeightItem {
  key: string
  label: string
  score: number
  disabled: boolean
  last_result: string
  last_reason: string
  last_success_at: string
  last_failed_at: string
  updated_at: string
}

export interface DomainWeightSummary {
  total: number
  enabled: number
  disabled: number
  avg_score: number
}

export interface CpaOverviewData {
  connected: boolean
  management_url: string
  total_accounts: number
  pending_sync: number
  synced: number
  [key: string]: unknown
}

export interface CpaAccount {
  name: string
  email: string
  provider: string
  health_status: string
  disabled: boolean
  priority: number
  note: string
  last_checked_at: string
  [key: string]: unknown
}

export interface CpaPagination {
  page: number
  per_page: number
  total: number
  total_pages: number
  has_prev: boolean
  has_next: boolean
}

export interface CpaAccountsData {
  ok: boolean
  accounts: CpaAccount[]
  pagination: CpaPagination
  filters: Record<string, string>
  filter_options: {
    providers: string[]
    health_statuses: string[]
    disabled_states: string[]
  }
  message: string
}

export interface SecuritySummary {
  username: string
  password_hash_set: boolean
  api_token_set: boolean
  session_secret_set: boolean
  session_minutes: number
  secure_cookie: boolean
  login_rate_limit: number
  login_window_seconds: number
  csrf_enabled: boolean
  trusted_origins: string[]
}

export interface ApiResponse<T = unknown> {
  status: 'success' | 'error'
  message?: string
  data?: T
  config?: Record<string, unknown>
}
