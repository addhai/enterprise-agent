// 共享类型定义 —— 从 AdminDashboard.tsx 抽离，供 admin/ 下各 Tab 组件复用。
// 数据源：src/api/* 返回结构；本文件仅类型声明，无运行逻辑。

export interface Props {
  user: { id: string; username: string; email?: string; role?: string } | null
  token: string | null
  onLoginClick: () => void
  onBack: () => void
}

export interface RbacInfo {
  role: string
  role_label: string
  permissions: string[]
}

export interface DashboardKpi {
  sessions: {
    total: number
    active_today: number
    today_new: number
    waiting_human: number
    human_chat: number
    ai_resolution_rate: number
    avg_turns: number
  }
  tickets: {
    total: number
    open: number
    in_progress: number
    unassigned: number
    urgent: number
  }
  satisfaction: {
    avg_score: number
    csat_rate: number
    total: number
  }
  customers: {
    total: number
    active_today: number
  }
  sessions_week: { date: string; count: number }[]
}

export interface RealtimeActivity {
  recent_sessions: {
    session_id: string
    user_id: string
    mode: string
    last_active: number
    turn_count: number
    preview: string
  }[]
  waiting_queue: {
    session_id: string
    user_id: string
    wait_time: number
    last_message_preview: string
  }[]
  waiting_count: number
}

export interface TicketComment {
  id: string
  author: string
  content: string
  created_at: string
}

export interface TicketItem {
  id: string
  tenant_id: string
  user_id: string
  title: string
  description: string
  category: string
  priority: string
  status: string
  assignee?: string
  tags: string[]
  created_at: string
  updated_at: string
  closed_at?: string
  comments: TicketComment[]
}

export interface CustomerItem {
  user_id: string
  username: string
  email?: string
  phone?: string
  company?: string
  plan: string
  status: string
  tags: string[]
  note: string
  first_seen_at: number
  last_seen_at: number
  session_count: number
  ticket_count: number
  satisfaction_score?: number
  satisfaction_count: number
  total_messages: number
}

export interface CustomerSession {
  session_id: string
  mode: string
  created_at: number
  last_active: number
  turn_count: number
  last_message_preview: string
}

export interface CustomerDetail {
  customer: CustomerItem
  sessions: CustomerSession[]
  tickets: TicketItem[]
  satisfaction: SatisfactionRecord[]
}

export interface CustomerTimelineEvent {
  type: string
  title: string
  time: number
  detail: string
}

export interface SatisfactionRecord {
  id: string
  session_id: string
  user_id: string
  score: number
  tags: string[]
  comment: string
  agent_id?: string
  created_at: number
}

export interface NotificationItem {
  id: string
  type: string
  level: string
  title: string
  message: string
  target_roles: string[]
  target_users: string[]
  link?: string
  read_by: string[]
  created_at: number
  is_read?: boolean
}

export interface RbacUser {
  user_id: string
  username: string
  avatar: string
  role: string
  status: string
  created_at: number
}

export interface RoleInfo {
  role: string
  label: string
  description: string
  permissions: string[]
}

export interface ChannelData {
  name: string
  enabled: boolean
  description?: string
  config?: Record<string, any>
}

export interface SessionItemData {
  session_id: string
  user_id: string
  mode: string
  created_at: number
  last_active: number
  turn_count: number
  last_message_preview: string
  conversation_history?: { role: string; content: string; timestamp?: number }[]
  assigned_agent?: string
}

export interface HandoffItem {
  session_id: string
  user_id: string
  mode: string
  wait_time?: number
  last_message_preview?: string
  turn_count?: number
  last_active?: number
  assigned_agent?: string
  handoff_context?: {
    summary?: string
    reason?: string
    urgency?: 'critical' | 'high' | 'normal' | 'low'
    attempted_solutions?: { steps?: string[] }
    user_profile?: { user_id?: string; plan?: string }
    current_blocker?: { items?: { severity: string; type: string; detail: string }[] }
    conversation?: { role: string; content: string }[]
  }
}

export interface AgentHealthInfo {
  agent_id: string
  name: string
  url: string
  status: 'online' | 'offline'
  last_heartbeat_age_sec: number
  circuit_state: 'closed' | 'open' | 'half_open'
  failures: number
}

export interface HealthStatus {
  threshold_seconds: number
  scan_interval_seconds: number
  probe_enabled: boolean
  probe_interval_seconds: number
  total_agents: number
  online_agents: number
  offline_agents: number
  agents: AgentHealthInfo[]
  circuit_breakers: Record<string, { failures: number; state: string }>
}

export interface MetricsAll {
  total_requests: number
  total_sessions: number
  resolved: number
  unresolved: number
  resolution_rate: number
  uptime_seconds: number
  avg_latency_ms: number
  avg_quality_score: number
  escalation_rate: number
  avg_turns: number
  safety_events?: Record<string, number>
  prompt_injections_blocked?: number
  safety_violations?: number
  hallucinations_detected?: number
  hallucinations_blocked?: number
}

export interface MetricsRisk {
  escalation_rate: number
  low_quality_rate: number
  unresolved_rate: number
  avg_quality_score: number
  tracked_sessions: number
  total_requests: number
  prompt_injections_blocked?: number
  safety_violations?: number
  hallucinations_detected?: number
  hallucinations_blocked?: number
  safety_events?: Record<string, number>
  instrumented: boolean
}

export interface DbInfo { reachable: boolean; backend: string; error?: string }
export interface MetricsSystem {
  status: string
  uptime_seconds: number
  database: DbInfo
  cpu_percent: number | null
  memory_percent: number | null
  active_sessions: number | null
  online_agents: number | null
  sessions_by_mode?: Record<string, number>
  pid: number
}

export interface ConfigField {
  name: string
  type: string
  default: unknown
  value: unknown
  is_sensitive: boolean
  configured?: boolean
  is_default?: boolean
}

export interface ConfigCategory {
  key: string
  label: string
  description: string
  fields: ConfigField[]
}

export interface FeatureFlag {
  name: string
  enabled: boolean
  is_default: boolean
  category: string
  category_label: string
}

export interface EvalDataset {
  id: string
  name: string
  description: string
  samples: unknown[]
  created_at: number
}

export interface EvalRun {
  id: string
  dataset_id: string
  dataset_name: string
  status: string
  started_at: number
  finished_at: number | null
  summary: Record<string, number>
}

export interface WorkflowInfo {
  id: string
  name: string
  description: string
  version: number
  is_published: boolean
  is_default: boolean
  node_count: number
  edge_count: number
  updated_at: number
}

export type TabKey = 'dashboard' | 'tickets' | 'customers' | 'satisfaction' | 'notifications' | 'rbac' | 'channels' | 'sessions' | 'agent' | 'health' | 'monitoring' | 'config' | 'evaluation' | 'workflow' | 'knowledge'

export interface KBSetItem {
  id: string
  name: string
  description: string
  kb_version: string
  kb_type: string
  similarity_threshold: number
  weight: number
  document_count: number
  total_chunks: number
  created_at: string
  updated_at: string
  created_by: string
}

export interface KBDocItem {
  id: string
  kb_id: string
  title: string
  file_path: string
  source_type: string
  status: string
  parse_status: string
  chunk_count: number
  doc_format: string
  file_size: number
  kb_version: string
  kb_type: string
  upload_method: string
  similarity_threshold: number
  weight: number
  created_at: string
  indexed_at?: string
}

export interface KBHitResult {
  content: string
  score: number
  source: string
  metadata?: Record<string, any>
}
