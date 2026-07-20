import { useCallback, useEffect, useMemo, useState } from 'react'

// ============================================================
// Props
// ============================================================

interface Props {
  isOpen: boolean
  onClose: () => void
  user: { id: string; username: string; email?: string; role?: string } | null
  token: string | null
  onLoginClick: () => void
}

// ============================================================
// Shared types
// ============================================================

interface RbacInfo {
  role: string
  role_label: string
  permissions: string[]
}

interface DashboardKpi {
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

interface RealtimeActivity {
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

interface TicketComment {
  id: string
  author: string
  content: string
  created_at: string
}

interface TicketItem {
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

interface CustomerItem {
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

interface CustomerSession {
  session_id: string
  mode: string
  created_at: number
  last_active: number
  turn_count: number
  last_message_preview: string
}

interface CustomerDetail {
  customer: CustomerItem
  sessions: CustomerSession[]
  tickets: TicketItem[]
  satisfaction: SatisfactionRecord[]
}

interface CustomerTimelineEvent {
  type: string
  title: string
  time: number
  detail: string
}

interface SatisfactionRecord {
  id: string
  session_id: string
  user_id: string
  score: number
  tags: string[]
  comment: string
  agent_id?: string
  created_at: number
}

interface SatisfactionStats {
  total: number
  average_score: number
  csat_rate: number
  distribution: Record<string, number>
  recent_trend: { date: string; avg_score: number; count: number }[]
}

interface NotificationItem {
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

interface RbacUser {
  user_id: string
  username: string
  avatar: string
  role: string
  status: string
  created_at: number
}

interface RoleInfo {
  role: string
  label: string
  description: string
  permissions: string[]
}

interface ChannelData {
  name: string
  enabled: boolean
  description?: string
  config?: Record<string, any>
}

interface SessionItemData {
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

interface HandoffItem {
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

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// ============================================================
// API helpers
// ============================================================

async function checkResponse(response: Response) {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new ApiError(response.status, data.detail || data.message || `请求失败 (${response.status})`)
  }
  return response.json()
}

async function fetchApi(path: string, token: string, options: RequestInit = {}) {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (options.body && typeof options.body === 'string') {
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: { ...headers, ...(options.headers as Record<string, string> || {}) },
  })
  return checkResponse(response)
}

async function fetchJson(path: string, token: string) {
  return fetchApi(path, token)
}

async function postJson(path: string, token: string, body: unknown) {
  return fetchApi(path, token, { method: 'POST', body: JSON.stringify(body) })
}

async function putJson(path: string, token: string, body: unknown) {
  return fetchApi(path, token, { method: 'PUT', body: JSON.stringify(body) })
}

// ============================================================
// Formatting helpers
// ============================================================

function formatDate(ts: number | string | undefined) {
  if (ts === undefined || ts === null || ts === '') return '-'
  const d = typeof ts === 'string' ? new Date(ts) : new Date(ts * 1000)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleString('zh-CN')
}

function formatDuration(seconds?: number) {
  if (seconds === undefined || seconds === null) return '-'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}分${s < 10 ? '0' : ''}${s}秒`
}

function formatDateShort(ts: number | string | undefined) {
  if (ts === undefined || ts === null || ts === '') return '-'
  const d = typeof ts === 'string' ? new Date(ts) : new Date(ts * 1000)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleDateString('zh-CN')
}

// ============================================================
// StatCard
// ============================================================

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ color: color || 'var(--brand-teal-dark)' }}>{value}</div>
    </div>
  )
}

// ============================================================
// Dashboard
// ============================================================

function DashboardTab({ token }: { token: string }) {
  const [kpi, setKpi] = useState<DashboardKpi | null>(null)
  const [realtime, setRealtime] = useState<RealtimeActivity | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([
      fetchJson('/dashboard/kpi', token),
      fetchJson('/dashboard/realtime', token),
    ])
      .then(([k, r]) => {
        if (cancelled) return
        setKpi(k as DashboardKpi)
        setRealtime(r as RealtimeActivity)
      })
      .catch(err => { if (!cancelled) setError(err instanceof Error ? err.message : '加载失败') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token])

  if (loading) return <div className="admin-loading">加载中...</div>
  if (error) return <div className="admin-error">{error}</div>
  if (!kpi || !realtime) return null

  const maxWeek = Math.max(1, ...kpi.sessions_week.map(d => d.count))

  return (
    <div>
      <div className="metrics-grid">
        <StatCard label="总会话" value={String(kpi.sessions.total)} />
        <StatCard label="今日活跃" value={String(kpi.sessions.active_today)} />
        <StatCard label="今日新建" value={String(kpi.sessions.today_new)} />
        <StatCard label="待人工接入" value={String(kpi.sessions.waiting_human)} color="#f59e0b" />
        <StatCard label="人工服务中" value={String(kpi.sessions.human_chat)} color="#667eea" />
        <StatCard label="AI 解决率" value={`${kpi.sessions.ai_resolution_rate}%`} color="#22c55e" />
        <StatCard label="平均轮数" value={String(kpi.sessions.avg_turns)} color="#a855f7" />
        <StatCard label="待处理工单" value={String(kpi.tickets.open)} color="#ef4444" />
        <StatCard label="未分配工单" value={String(kpi.tickets.unassigned)} color="#f97316" />
        <StatCard label="满意度均分" value={String(kpi.satisfaction.avg_score)} color="#14b8a6" />
        <StatCard label="客户总数" value={String(kpi.customers.total)} />
        <StatCard label="今日活跃客户" value={String(kpi.customers.active_today)} />
      </div>

      <div className="dashboard-section">
        <h3 className="dashboard-section-title">近 7 天会话趋势</h3>
        {kpi.sessions_week.length === 0 ? (
          <p className="hint">暂无数据</p>
        ) : (
          <div className="trend-bars">
            {kpi.sessions_week.map(d => (
              <div key={d.date} className="trend-bar-item">
                <div className="trend-bar-track">
                  <div
                    className="trend-bar-fill"
                    style={{ height: `${Math.max(4, (d.count / maxWeek) * 100)}%` }}
                  />
                </div>
                <span className="trend-bar-label">{d.date}</span>
                <span className="trend-bar-value">{d.count}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="dashboard-split">
        <div className="dashboard-panel">
          <h3 className="dashboard-section-title">最近活动</h3>
          {realtime.recent_sessions.length === 0 ? (
            <p className="hint">暂无活动</p>
          ) : (
            <ul className="recent-list">
              {realtime.recent_sessions.map(s => (
                <li key={s.session_id} className="recent-item">
                  <span className="recent-item-title">{s.user_id}</span>
                  <span className="recent-item-meta">
                    {s.preview || '无消息'} · {formatDate(s.last_active)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="dashboard-panel">
          <h3 className="dashboard-section-title">
            等待人工接入
            <span className="badge badge-warning">{realtime.waiting_count}</span>
          </h3>
          {realtime.waiting_queue.length === 0 ? (
            <p className="hint">暂无等待</p>
          ) : (
            <ul className="recent-list">
              {realtime.waiting_queue.map(w => (
                <li key={w.session_id} className="recent-item">
                  <span className="recent-item-title">{w.user_id}</span>
                  <span className="recent-item-meta">
                    等待 {formatDuration(w.wait_time)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

// ============================================================
// Tickets
// ============================================================

const TICKET_STATUSES = [
  { value: '', label: '全部状态' },
  { value: 'open', label: '待处理' },
  { value: 'in_progress', label: '处理中' },
  { value: 'resolved', label: '已解决' },
  { value: 'closed', label: '已关闭' },
  { value: 'cancelled', label: '已取消' },
]

const TICKET_PRIORITIES = [
  { value: '', label: '全部优先级' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'urgent', label: '紧急' },
]

function TicketsTab({ token, user, hasPermission }: { token: string; user: Props['user']; hasPermission: (p: string) => boolean }) {
  const [tickets, setTickets] = useState<TicketItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [priorityFilter, setPriorityFilter] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<TicketItem | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [comment, setComment] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [statusEdit, setStatusEdit] = useState('')

  const fetchList = useCallback(() => {
    setLoading(true)
    setError('')
    const params = new URLSearchParams()
    if (statusFilter) params.set('status', statusFilter)
    if (priorityFilter) params.set('priority', priorityFilter)
    if (search.trim()) params.set('search', search.trim())
    params.set('limit', '100')
    fetchJson(`/tickets?${params.toString()}`, token)
      .then(data => setTickets((data.tickets || []) as TicketItem[]))
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token, statusFilter, priorityFilter, search])

  useEffect(() => { fetchList() }, [fetchList])

  const openDetail = (ticket: TicketItem) => {
    setSelected(ticket)
    setStatusEdit(ticket.status)
    setComment('')
    if (!ticket.comments || ticket.comments.length === 0) {
      setDetailLoading(true)
      fetchJson(`/tickets/${ticket.id}`, token)
        .then(data => {
          setSelected(data as TicketItem)
          setStatusEdit((data as TicketItem).status)
        })
        .catch(() => setSelected(ticket))
        .finally(() => setDetailLoading(false))
    }
  }

  const refreshSelected = async (ticketId: string) => {
    const data = await fetchJson(`/tickets/${ticketId}`, token)
    setSelected(data as TicketItem)
    setStatusEdit((data as TicketItem).status)
  }

  const assignToMe = async () => {
    if (!selected || !user) return
    setActionLoading(true)
    try {
      await postJson(`/tickets/${selected.id}/assign`, token, { assignee: user.username })
      await refreshSelected(selected.id)
      fetchList()
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    } finally {
      setActionLoading(false)
    }
  }

  const updateStatus = async () => {
    if (!selected || !statusEdit) return
    setActionLoading(true)
    try {
      await putJson(`/tickets/${selected.id}`, token, { status: statusEdit })
      await refreshSelected(selected.id)
      fetchList()
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    } finally {
      setActionLoading(false)
    }
  }

  const addComment = async () => {
    if (!selected || !comment.trim()) return
    setActionLoading(true)
    try {
      await postJson(`/tickets/${selected.id}/comments`, token, { content: comment.trim() })
      setComment('')
      await refreshSelected(selected.id)
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    } finally {
      setActionLoading(false)
    }
  }

  const closeTicket = async () => {
    if (!selected) return
    setActionLoading(true)
    try {
      await postJson(`/tickets/${selected.id}/close`, token, {})
      await refreshSelected(selected.id)
      fetchList()
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    } finally {
      setActionLoading(false)
    }
  }

  const canAssign = hasPermission('ticket:assign')
  const canManage = hasPermission('ticket:manage')

  if (selected) {
    return (
      <div className="detail-panel">
        <div className="detail-header">
          <button className="back-btn" onClick={() => setSelected(null)}>← 返回列表</button>
          <div className="detail-actions">
            {canAssign && selected.status !== 'closed' && selected.assignee !== user?.username && (
              <button className="btn-primary-small" onClick={assignToMe} disabled={actionLoading}>分配给我</button>
            )}
            {canAssign && selected.status !== 'closed' && (
              <button className="btn-secondary-small" onClick={closeTicket} disabled={actionLoading}>关闭工单</button>
            )}
          </div>
        </div>
        {detailLoading && <div className="admin-loading">加载详情...</div>}
        {!detailLoading && (
          <>
            <div className="detail-grid">
              <div><span className="detail-label">工单ID</span><span className="detail-value">{selected.id}</span></div>
              <div><span className="detail-label">客户</span><span className="detail-value">{selected.user_id}</span></div>
              <div><span className="detail-label">分类</span><span className="detail-value">{selected.category}</span></div>
              <div><span className="detail-label">优先级</span><span className={`badge priority-${selected.priority}`}>{selected.priority}</span></div>
              <div><span className="detail-label">状态</span><span className={`badge status-${selected.status}`}>{selected.status}</span></div>
              <div><span className="detail-label">负责人</span><span className="detail-value">{selected.assignee || '-'}</span></div>
              <div><span className="detail-label">创建时间</span><span className="detail-value">{formatDate(selected.created_at)}</span></div>
              <div><span className="detail-label">标签</span><span className="detail-value">{selected.tags.join(', ') || '-'}</span></div>
            </div>
            <div className="detail-section">
              <h4>描述</h4>
              <p>{selected.description || '无描述'}</p>
            </div>
            {canManage && selected.status !== 'closed' && (
              <div className="detail-section">
                <h4>状态变更</h4>
                <div className="filter-bar">
                  <select value={statusEdit} onChange={e => setStatusEdit(e.target.value)} className="filter-select">
                    {TICKET_STATUSES.filter(s => s.value).map(s => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                  <button className="btn-primary-small" onClick={updateStatus} disabled={actionLoading || statusEdit === selected.status}>更新状态</button>
                </div>
              </div>
            )}
            {canManage && selected.status !== 'closed' && (
              <div className="detail-section">
                <h4>添加评论</h4>
                <div className="comment-input-row">
                  <input
                    type="text"
                    value={comment}
                    onChange={e => setComment(e.target.value)}
                    placeholder="输入跟进内容..."
                    className="filter-input"
                    disabled={actionLoading}
                  />
                  <button className="btn-primary-small" onClick={addComment} disabled={actionLoading || !comment.trim()}>提交</button>
                </div>
              </div>
            )}
            <div className="detail-section">
              <h4>评论记录 ({selected.comments.length})</h4>
              {selected.comments.length === 0 ? (
                <p className="hint">暂无评论</p>
              ) : (
                <div className="comment-list">
                  {selected.comments.map(c => (
                    <div key={c.id} className="comment-item">
                      <div className="comment-header">
                        <span className="comment-author">{c.author}</span>
                        <span className="comment-time">{formatDate(c.created_at)}</span>
                      </div>
                      <p className="comment-content">{c.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    )
  }

  return (
    <div>
      <div className="filter-bar">
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="filter-select">
          {TICKET_STATUSES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <select value={priorityFilter} onChange={e => setPriorityFilter(e.target.value)} className="filter-select">
          {TICKET_PRIORITIES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="搜索标题 / 描述 / 客户ID"
          className="filter-input"
        />
        <button className="refresh-btn" onClick={fetchList} disabled={loading}>刷新</button>
      </div>
      {loading && <div className="admin-loading">加载工单...</div>}
      {error && <div className="admin-error">{error}</div>}
      {!loading && !error && tickets.length === 0 && (
        <div className="sessions-placeholder"><p>暂无工单</p></div>
      )}
      {!loading && !error && tickets.length > 0 && (
        <div className="sessions-table-wrap">
          <table className="sessions-table">
            <thead>
              <tr>
                <th>标题</th>
                <th>客户</th>
                <th>优先级</th>
                <th>状态</th>
                <th>负责人</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map(t => (
                <tr key={t.id} className="session-row" onClick={() => openDetail(t)}>
                  <td className="ticket-title">{t.title}</td>
                  <td>{t.user_id}</td>
                  <td><span className={`badge priority-${t.priority}`}>{t.priority}</span></td>
                  <td><span className={`badge status-${t.status}`}>{t.status}</span></td>
                  <td>{t.assignee || '-'}</td>
                  <td>{formatDateShort(t.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ============================================================
// Customers
// ============================================================

const CUSTOMER_STATUSES = [
  { value: '', label: '全部状态' },
  { value: 'active', label: '正常' },
  { value: 'inactive', label: ' inactive' },
  { value: 'suspended', label: '已停用' },
]

function CustomersTab({ token, hasPermission }: { token: string; hasPermission: (p: string) => boolean }) {
  const [customers, setCustomers] = useState<CustomerItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [planFilter, setPlanFilter] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<CustomerDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [timeline, setTimeline] = useState<CustomerTimelineEvent[]>([])
  const [tagInput, setTagInput] = useState('')
  const [noteInput, setNoteInput] = useState('')
  const [statusInput, setStatusInput] = useState('')
  const [saving, setSaving] = useState(false)

  const canManage = hasPermission('customer:manage')

  const fetchList = useCallback(() => {
    setLoading(true)
    setError('')
    const params = new URLSearchParams()
    if (search.trim()) params.set('search', search.trim())
    if (planFilter) params.set('plan', planFilter)
    if (tagFilter.trim()) params.set('tag', tagFilter.trim())
    params.set('limit', '100')
    fetchJson(`/customers?${params.toString()}`, token)
      .then(data => setCustomers((data.customers || []) as CustomerItem[]))
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token, search, planFilter, tagFilter])

  useEffect(() => { fetchList() }, [fetchList])

  const fetchDetail = useCallback(async (userId: string) => {
    setDetailLoading(true)
    try {
      const [d, t] = await Promise.all([
        fetchJson(`/customers/${userId}`, token),
        fetchJson(`/customers/${userId}/timeline`, token),
      ])
      const cd = d as CustomerDetail
      setDetail(cd)
      setTagInput(cd.customer.tags.join(', '))
      setNoteInput(cd.customer.note)
      setStatusInput(cd.customer.status)
      setTimeline((t.events || []) as CustomerTimelineEvent[])
    } catch (err) {
      alert(err instanceof Error ? err.message : '加载详情失败')
    } finally {
      setDetailLoading(false)
    }
  }, [token])

  const openDetail = (c: CustomerItem) => {
    setSelectedId(c.user_id)
    setDetail(null)
    fetchDetail(c.user_id)
  }

  const saveTags = async () => {
    if (!detail) return
    setSaving(true)
    try {
      const tags = tagInput.split(',').map(s => s.trim()).filter(Boolean)
      await putJson(`/customers/${detail.customer.user_id}/tags`, token, { tags })
      await fetchDetail(detail.customer.user_id)
      fetchList()
    } catch (err) {
      alert(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const saveNote = async () => {
    if (!detail) return
    setSaving(true)
    try {
      await putJson(`/customers/${detail.customer.user_id}/note`, token, { note: noteInput })
      await fetchDetail(detail.customer.user_id)
    } catch (err) {
      alert(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const saveStatus = async () => {
    if (!detail || !statusInput) return
    setSaving(true)
    try {
      await fetchApi(`/customers/${detail.customer.user_id}/status?status=${statusInput}`, token, { method: 'PUT' })
      await fetchDetail(detail.customer.user_id)
      fetchList()
    } catch (err) {
      alert(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (selectedId) {
    return (
      <div className="detail-panel">
        <div className="detail-header">
          <button className="back-btn" onClick={() => setSelectedId(null)}>← 返回列表</button>
        </div>
        {detailLoading && <div className="admin-loading">加载客户详情...</div>}
        {!detailLoading && detail && (
          <>
            <div className="customer-profile">
              <div className="profile-avatar-large">{detail.customer.username.charAt(0).toUpperCase()}</div>
              <div className="customer-profile-info">
                <h3>{detail.customer.username} <span className={`badge status-${detail.customer.status}`}>{detail.customer.status}</span></h3>
                <p className="profile-email">{detail.customer.user_id} {detail.customer.email ? `· ${detail.customer.email}` : ''}</p>
                <p className="profile-meta">计划：{detail.customer.plan} · 会话：{detail.customer.session_count} · 工单：{detail.customer.ticket_count} · 满意度：{detail.customer.satisfaction_score ?? '-'}</p>
              </div>
            </div>

            {canManage && (
              <div className="detail-section">
                <h4>编辑信息</h4>
                <div className="edit-grid">
                  <div className="edit-field">
                    <label>标签（逗号分隔）</label>
                    <input type="text" value={tagInput} onChange={e => setTagInput(e.target.value)} className="filter-input" />
                    <button className="btn-primary-small" onClick={saveTags} disabled={saving}>保存标签</button>
                  </div>
                  <div className="edit-field">
                    <label>备注</label>
                    <textarea value={noteInput} onChange={e => setNoteInput(e.target.value)} className="agent-reply-input" rows={2} />
                    <button className="btn-primary-small" onClick={saveNote} disabled={saving}>保存备注</button>
                  </div>
                  <div className="edit-field">
                    <label>状态</label>
                    <select value={statusInput} onChange={e => setStatusInput(e.target.value)} className="filter-select">
                      {CUSTOMER_STATUSES.filter(s => s.value).map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select>
                    <button className="btn-primary-small" onClick={saveStatus} disabled={saving || statusInput === detail.customer.status}>保存状态</button>
                  </div>
                </div>
              </div>
            )}

            <div className="dashboard-split">
              <div className="dashboard-panel">
                <h4 className="dashboard-section-title">会话历史 ({detail.sessions.length})</h4>
                {detail.sessions.length === 0 ? <p className="hint">无会话</p> : (
                  <ul className="recent-list compact">
                    {detail.sessions.map(s => (
                      <li key={s.session_id} className="recent-item">
                        <span className="recent-item-title">{s.session_id.slice(0, 12)}</span>
                        <span className="recent-item-meta">{s.mode} · {s.turn_count} 轮 · {formatDate(s.last_active)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="dashboard-panel">
                <h4 className="dashboard-section-title">工单历史 ({detail.tickets.length})</h4>
                {detail.tickets.length === 0 ? <p className="hint">无工单</p> : (
                  <ul className="recent-list compact">
                    {detail.tickets.map(t => (
                      <li key={t.id} className="recent-item">
                        <span className="recent-item-title">{t.title}</span>
                        <span className="recent-item-meta"><span className={`badge status-${t.status}`}>{t.status}</span> · {formatDateShort(t.created_at)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <div className="detail-section">
              <h4>满意度记录</h4>
              {detail.satisfaction.length === 0 ? <p className="hint">暂无评价</p> : (
                <div className="comment-list">
                  {detail.satisfaction.map(r => (
                    <div key={r.id} className="comment-item">
                      <div className="comment-header">
                        <span className="comment-author">{r.score} 星</span>
                        <span className="comment-time">{formatDate(r.created_at)}</span>
                      </div>
                      <p className="comment-content">{r.comment || r.tags.join(', ') || '无文字评价'}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="detail-section">
              <h4>时间线</h4>
              {timeline.length === 0 ? <p className="hint">暂无事件</p> : (
                <div className="timeline">
                  {timeline.map((e, idx) => (
                    <div key={idx} className={`timeline-item type-${e.type}`}>
                      <div className="timeline-dot" />
                      <div className="timeline-content">
                        <div className="timeline-title">{e.title}</div>
                        <div className="timeline-detail">{e.detail}</div>
                        <div className="timeline-time">{formatDate(e.time)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    )
  }

  return (
    <div>
      <div className="filter-bar">
        <input type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索用户名 / ID / 邮箱" className="filter-input" />
        <input type="text" value={planFilter} onChange={e => setPlanFilter(e.target.value)} placeholder="计划" className="filter-input small" />
        <input type="text" value={tagFilter} onChange={e => setTagFilter(e.target.value)} placeholder="标签" className="filter-input small" />
        <button className="refresh-btn" onClick={fetchList} disabled={loading}>刷新</button>
      </div>
      {loading && <div className="admin-loading">加载客户...</div>}
      {error && <div className="admin-error">{error}</div>}
      {!loading && !error && customers.length === 0 && <div className="sessions-placeholder"><p>暂无客户</p></div>}
      {!loading && !error && customers.length > 0 && (
        <div className="sessions-table-wrap">
          <table className="sessions-table">
            <thead>
              <tr><th>客户</th><th>计划</th><th>状态</th><th>标签</th><th>最近活跃</th><th>会话/工单</th></tr>
            </thead>
            <tbody>
              {customers.map(c => (
                <tr key={c.user_id} className="session-row" onClick={() => openDetail(c)}>
                  <td>
                    <div className="customer-cell">
                      <span className="customer-avatar">{c.username.charAt(0).toUpperCase()}</span>
                      <div>
                        <div className="customer-name">{c.username}</div>
                        <div className="customer-id">{c.user_id}</div>
                      </div>
                    </div>
                  </td>
                  <td>{c.plan}</td>
                  <td><span className={`badge status-${c.status}`}>{c.status}</span></td>
                  <td>{c.tags.join(', ') || '-'}</td>
                  <td>{formatDateShort(c.last_seen_at)}</td>
                  <td>{c.session_count} / {c.ticket_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ============================================================
// Satisfaction
// ============================================================

function SatisfactionTab({ token }: { token: string }) {
  const [records, setRecords] = useState<SatisfactionRecord[]>([])
  const [stats, setStats] = useState<SatisfactionStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    Promise.all([
      fetchJson('/satisfaction?limit=100', token),
      fetchJson('/satisfaction/stats?days=7', token),
    ])
      .then(([r, s]) => {
        setRecords((r.records || []) as SatisfactionRecord[])
        setStats(s as SatisfactionStats)
      })
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token])

  if (loading) return <div className="admin-loading">加载满意度...</div>
  if (error) return <div className="admin-error">{error}</div>

  return (
    <div>
      {stats && (
        <div className="metrics-grid">
          <StatCard label="评价总数" value={String(stats.total)} />
          <StatCard label="平均评分" value={String(stats.average_score)} />
          <StatCard label="CSAT 率" value={`${stats.csat_rate}%`} />
          {Object.entries(stats.distribution).sort().map(([score, count]) => (
            <StatCard key={score} label={`${score} 星`} value={String(count)} />
          ))}
        </div>
      )}
      <div className="sessions-container" style={{ marginTop: 16 }}>
        <h3 className="detail-title">评价记录</h3>
        {records.length === 0 ? <p className="hint">暂无评价</p> : (
          <div className="comment-list">
            {records.map(r => (
              <div key={r.id} className="comment-item">
                <div className="comment-header">
                  <span className="comment-author">{r.score} 星 · {r.user_id}</span>
                  <span className="comment-time">{formatDate(r.created_at)}</span>
                </div>
                <p className="comment-content">{r.comment || r.tags.join(', ') || '无文字评价'}</p>
                {r.agent_id && <span className="hint">客服：{r.agent_id}</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ============================================================
// Notifications
// ============================================================

function NotificationsTab({ token }: { token: string }) {
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchAll = useCallback(() => {
    setLoading(true)
    setError('')
    Promise.all([
      fetchJson('/notifications?limit=100', token),
      fetchJson('/notifications/unread-count', token),
    ])
      .then(([n, u]) => {
        setNotifications((n.notifications || []) as NotificationItem[])
        setUnreadCount((u.unread_count || 0) as number)
      })
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => { fetchAll() }, [fetchAll])

  const markRead = async (id: string) => {
    try {
      await postJson(`/notifications/${id}/read`, token, {})
      fetchAll()
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    }
  }

  const markAllRead = async () => {
    try {
      await postJson('/notifications/read-all', token, {})
      fetchAll()
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    }
  }

  return (
    <div>
      <div className="filter-bar">
        <span className="notification-count">未读通知：<span className="badge badge-warning">{unreadCount}</span></span>
        <button className="btn-primary-small" onClick={markAllRead}>全部已读</button>
        <button className="refresh-btn" onClick={fetchAll} disabled={loading}>刷新</button>
      </div>
      {loading && <div className="admin-loading">加载通知...</div>}
      {error && <div className="admin-error">{error}</div>}
      {!loading && !error && notifications.length === 0 && <div className="sessions-placeholder"><p>暂无通知</p></div>}
      {!loading && !error && notifications.length > 0 && (
        <div className="notification-list">
          {notifications.map(n => (
            <div key={n.id} className={`notification-item ${n.is_read ? 'read' : 'unread'}`}>
              <div className="notification-main">
                <div className="notification-title">{n.title}</div>
                <div className="notification-message">{n.message}</div>
                <div className="notification-meta">{n.type} · {formatDate(n.created_at)}</div>
              </div>
              {!n.is_read && (
                <button className="btn-secondary-small" onClick={() => markRead(n.id)}>标记已读</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================
// RBAC
// ============================================================

const USER_STATUSES = ['active', 'inactive', 'suspended']

function RbacTab({ token, user, hasPermission }: { token: string; user: Props['user']; hasPermission: (p: string) => boolean }) {
  const [users, setUsers] = useState<RbacUser[]>([])
  const [roles, setRoles] = useState<RoleInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const canManage = hasPermission('user:manage')

  const fetchAll = useCallback(() => {
    setLoading(true)
    setError('')
    Promise.all([
      fetchJson('/rbac/users', token),
      fetchJson('/rbac/roles', token),
    ])
      .then(([u, r]) => {
        setUsers((u.users || []) as RbacUser[])
        setRoles((r.roles || []) as RoleInfo[])
      })
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => { fetchAll() }, [fetchAll])

  const updateRole = async (userId: string, role: string) => {
    try {
      await putJson(`/rbac/users/${userId}/role`, token, { role })
      fetchAll()
    } catch (err) {
      alert(err instanceof Error ? err.message : '修改失败')
    }
  }

  const updateStatus = async (userId: string, status: string) => {
    try {
      await putJson(`/rbac/users/${userId}/status`, token, { status })
      fetchAll()
    } catch (err) {
      alert(err instanceof Error ? err.message : '修改失败')
    }
  }

  return (
    <div>
      <div className="filter-bar">
        <span className="notification-count">共 {users.length} 位用户</span>
        <button className="refresh-btn" onClick={fetchAll} disabled={loading}>刷新</button>
      </div>
      {loading && <div className="admin-loading">加载用户...</div>}
      {error && <div className="admin-error">{error}</div>}
      {!loading && !error && users.length === 0 && <div className="sessions-placeholder"><p>暂无用户</p></div>}
      {!loading && !error && users.length > 0 && (
        <div className="sessions-table-wrap">
          <table className="sessions-table">
            <thead>
              <tr><th>用户名</th><th>角色</th><th>状态</th><th>创建时间</th></tr>
            </thead>
            <tbody>
              {users.map(u => {
                const isSelf = u.user_id === user?.id
                return (
                  <tr key={u.user_id}>
                    <td>
                      <div className="customer-cell">
                        <span className="customer-avatar">{u.username.charAt(0).toUpperCase()}</span>
                        <div>
                          <div className="customer-name">{u.username}</div>
                          <div className="customer-id">{u.user_id}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      {canManage && !isSelf ? (
                        <select
                          value={u.role}
                          onChange={e => updateRole(u.user_id, e.target.value)}
                          className="filter-select"
                        >
                          {roles.map(r => <option key={r.role} value={r.role}>{r.label}</option>)}
                        </select>
                      ) : (
                        <span className={`role-badge role-${u.role}`}>{roles.find(r => r.role === u.role)?.label || u.role}</span>
                      )}
                    </td>
                    <td>
                      {canManage && !isSelf ? (
                        <select
                          value={u.status}
                          onChange={e => updateStatus(u.user_id, e.target.value)}
                          className="filter-select"
                        >
                          {USER_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                        </select>
                      ) : (
                        <span className={`badge status-${u.status}`}>{u.status}</span>
                      )}
                    </td>
                    <td>{formatDate(u.created_at)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ============================================================
// Channels
// ============================================================

function ChannelsTab({ token }: { token: string }) {
  const [channels, setChannels] = useState<ChannelData[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedChannel, setExpandedChannel] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [saveMsg, setSaveMsg] = useState<{ channel: string; type: 'success' | 'error'; text: string } | null>(null)
  const [testMsg, setTestMsg] = useState<{ channel: string; type: 'success' | 'error'; text: string } | null>(null)

  const [chatwootForm, setChatwootForm] = useState({
    base_url: '',
    api_token: '',
    account_id: '1',
    inbox_id: '1',
    webhook_token: '',
    enabled: false,
  })
  const [feishuForm, setFeishuForm] = useState({
    app_id: '',
    app_secret: '',
    enabled: false,
  })

  const loadChannels = useCallback(() => {
    setLoading(true)
    fetch('/api/v1/admin/channels', { headers: { Authorization: `Bearer ${token}` } })
      .then(checkResponse)
      .then(data => {
        const list = (data.channels || data || []) as ChannelData[]
        setChannels(list)
        const cw = list.find(c => c.name === 'chatwoot')
        if (cw?.config) {
          setChatwootForm(prev => ({
            ...prev,
            base_url: cw.config.base_url || '',
            account_id: cw.config.account_id || '1',
            inbox_id: cw.config.inbox_id || '1',
            enabled: cw.enabled,
          }))
        }
        const fs = list.find(c => c.name === 'feishu')
        if (fs?.config) {
          setFeishuForm(prev => ({
            ...prev,
            app_id: fs.config.app_id || '',
            enabled: fs.enabled,
          }))
        }
      })
      .catch(() => {
        setChannels([
          { name: 'web', enabled: true, description: 'Web 端聊天窗口' },
          { name: 'feishu', enabled: false, description: '飞书渠道' },
          { name: 'chatwoot', enabled: false, description: 'Chatwoot 客服平台' },
        ])
      })
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => {
    loadChannels()
  }, [loadChannels])

  const handleSaveChatwoot = async () => {
    setSaving('chatwoot')
    setSaveMsg(null)
    try {
      const body: Record<string, any> = {
        base_url: chatwootForm.base_url,
        account_id: chatwootForm.account_id,
        inbox_id: chatwootForm.inbox_id,
        enabled: chatwootForm.enabled,
      }
      if (chatwootForm.api_token) body.api_token = chatwootForm.api_token
      if (chatwootForm.webhook_token) body.webhook_token = chatwootForm.webhook_token

      const res = await fetch('/api/v1/admin/channels/chatwoot/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.message || '保存失败')
      setSaveMsg({ channel: 'chatwoot', type: 'success', text: '配置已保存' })
      setChannels(prev => prev.map(c => c.name === 'chatwoot' ? { ...c, enabled: data.enabled, config: data.config } : c))
    } catch (err) {
      setSaveMsg({ channel: 'chatwoot', type: 'error', text: err instanceof Error ? err.message : '保存失败' })
    } finally {
      setSaving(null)
      setTimeout(() => setSaveMsg(null), 3000)
    }
  }

  const handleTestChatwoot = async () => {
    setTesting('chatwoot')
    setTestMsg(null)
    try {
      const res = await fetch('/api/v1/admin/channels/chatwoot/test', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      if (data.success) {
        setTestMsg({ channel: 'chatwoot', type: 'success', text: data.message || '连接成功' })
      } else {
        setTestMsg({ channel: 'chatwoot', type: 'error', text: data.message || '连接失败' })
      }
    } catch (err) {
      setTestMsg({ channel: 'chatwoot', type: 'error', text: err instanceof Error ? err.message : '测试失败' })
    } finally {
      setTesting(null)
      setTimeout(() => setTestMsg(null), 5000)
    }
  }

  const handleSaveFeishu = async () => {
    setSaving('feishu')
    setSaveMsg(null)
    try {
      const body: Record<string, any> = {
        app_id: feishuForm.app_id,
        enabled: feishuForm.enabled,
      }
      if (feishuForm.app_secret) body.app_secret = feishuForm.app_secret

      const res = await fetch('/api/v1/admin/channels/feishu/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.message || '保存失败')
      setSaveMsg({ channel: 'feishu', type: 'success', text: '配置已保存' })
      setChannels(prev => prev.map(c => c.name === 'feishu' ? { ...c, enabled: data.enabled, config: data.config } : c))
    } catch (err) {
      setSaveMsg({ channel: 'feishu', type: 'error', text: err instanceof Error ? err.message : '保存失败' })
    } finally {
      setSaving(null)
      setTimeout(() => setSaveMsg(null), 3000)
    }
  }

  const handleTestFeishu = async () => {
    setTesting('feishu')
    setTestMsg(null)
    try {
      const res = await fetch('/api/v1/admin/channels/feishu/test', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json()
      if (data.success) {
        setTestMsg({ channel: 'feishu', type: 'success', text: data.message || '连接成功' })
      } else {
        setTestMsg({ channel: 'feishu', type: 'error', text: data.message || '连接失败' })
      }
    } catch (err) {
      setTestMsg({ channel: 'feishu', type: 'error', text: err instanceof Error ? err.message : '测试失败' })
    } finally {
      setTesting(null)
      setTimeout(() => setTestMsg(null), 5000)
    }
  }

  const getChannelStatus = (name: string): boolean => {
    const ch = channels.find(c => c.name === name || c.name.includes(name) || name.includes(c.name))
    if (ch) return ch.enabled
    if (name === 'web' || name === 'Web 直连') return true
    return false
  }

  const channelConfigs = [
    {
      name: 'Web 直连',
      icon: '🌐',
      desc: '浏览器 WebSocket 直连',
      status: 'active',
      detail: (
        <div className="channel-detail-content">
          <div className="channel-detail-section">
            <div className="channel-detail-icon">✅</div>
            <div>
              <h5>已启用</h5>
              <p>Web 直连是内置功能，无需额外配置。用户访问网站即可直接使用智能客服。</p>
            </div>
          </div>
          <div className="channel-detail-info">
            <div className="info-item"><span className="info-label">连接方式</span><span className="info-value">WebSocket</span></div>
            <div className="info-item"><span className="info-label">状态</span><span className="info-value success">正常运行</span></div>
          </div>
        </div>
      ),
    },
    {
      name: '飞书',
      icon: '📘',
      desc: getChannelStatus('feishu') ? '飞书机器人已配置' : '需要配置飞书开放平台应用',
      status: getChannelStatus('feishu') ? 'active' : 'inactive',
      detail: (
        <div className="channel-detail-content">
          <div className="channel-detail-section">
            <div className="channel-detail-icon">{getChannelStatus('feishu') ? '✅' : '⚠️'}</div>
            <div>
              <h5>{getChannelStatus('feishu') ? '已启用' : '待配置'}</h5>
              <p>通过飞书开放平台创建企业自建应用，将智能客服接入飞书群聊或单聊。</p>
            </div>
          </div>
          <div className="channel-config-form">
            <h5>渠道配置</h5>
            <div className="form-row">
              <label className="form-label">启用飞书渠道</label>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={feishuForm.enabled}
                  onChange={(e) => setFeishuForm(prev => ({ ...prev, enabled: e.target.checked }))}
                  onClick={(e) => e.stopPropagation()}
                />
                <span className="toggle-slider"></span>
              </label>
            </div>
            <div className="form-row">
              <label className="form-label">App ID</label>
              <input
                type="text"
                className="form-input"
                value={feishuForm.app_id}
                onChange={(e) => setFeishuForm(prev => ({ ...prev, app_id: e.target.value }))}
                placeholder="cli_xxxxxxxxxxxxxx"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-row">
              <label className="form-label">App Secret</label>
              <input
                type="password"
                className="form-input"
                value={feishuForm.app_secret}
                onChange={(e) => setFeishuForm(prev => ({ ...prev, app_secret: e.target.value }))}
                placeholder={channels.find(c => c.name === 'feishu')?.config?.app_secret_configured ? '已配置，留空不修改' : '请输入 App Secret'}
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-actions">
              <button
                className="btn btn-secondary"
                onClick={(e) => { e.stopPropagation(); handleTestFeishu(); }}
                disabled={testing === 'feishu'}
              >
                {testing === 'feishu' ? '测试中...' : '测试连接'}
              </button>
              <button
                className="btn btn-primary"
                onClick={(e) => { e.stopPropagation(); handleSaveFeishu(); }}
                disabled={saving === 'feishu'}
              >
                {saving === 'feishu' ? '保存中...' : '保存配置'}
              </button>
            </div>
            {saveMsg?.channel === 'feishu' && (
              <div className={`form-message ${saveMsg.type}`} onClick={(e) => e.stopPropagation()}>
                {saveMsg.text}
              </div>
            )}
            {testMsg?.channel === 'feishu' && (
              <div className={`form-message ${testMsg.type}`} onClick={(e) => e.stopPropagation()}>
                {testMsg.text}
              </div>
            )}
          </div>
          <div className="channel-detail-steps">
            <h5>配置说明</h5>
            <div className="step-list">
              <div className="step-item">
                <div className="step-number">1</div>
                <div className="step-content">
                  <p className="step-title">创建飞书应用</p>
                  <p className="step-desc">前往 <a href="https://open.feishu.cn/" target="_blank" rel="noopener noreferrer">飞书开放平台</a>，创建企业自建应用</p>
                </div>
              </div>
              <div className="step-item">
                <div className="step-number">2</div>
                <div className="step-content">
                  <p className="step-title">获取凭证</p>
                  <p className="step-desc">在应用详情页获取 App ID 和 App Secret 并填入上方</p>
                </div>
              </div>
              <div className="step-item">
                <div className="step-number">3</div>
                <div className="step-content">
                  <p className="step-title">配置事件订阅</p>
                  <p className="step-desc">在飞书开放平台配置消息事件回调地址</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      ),
    },
    {
      name: 'Chatwoot',
      icon: '🪺',
      desc: getChannelStatus('chatwoot') ? 'Chatwoot 客服已接入' : '需要部署 Chatwoot 实例',
      status: getChannelStatus('chatwoot') ? 'active' : 'inactive',
      detail: (
        <div className="channel-detail-content">
          <div className="channel-detail-section">
            <div className="channel-detail-icon">{getChannelStatus('chatwoot') ? '✅' : '🔌'}</div>
            <div>
              <h5>{getChannelStatus('chatwoot') ? '已启用' : '待配置'}</h5>
              <p>Chatwoot 是开源客服系统，可通过 API 与本系统对接，实现多渠道统一管理。</p>
            </div>
          </div>
          <div className="channel-config-form">
            <h5>渠道配置</h5>
            <div className="form-row">
              <label className="form-label">启用 Chatwoot 渠道</label>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={chatwootForm.enabled}
                  onChange={(e) => setChatwootForm(prev => ({ ...prev, enabled: e.target.checked }))}
                  onClick={(e) => e.stopPropagation()}
                />
                <span className="toggle-slider"></span>
              </label>
            </div>
            <div className="form-row">
              <label className="form-label">Chatwoot Base URL</label>
              <input
                type="text"
                className="form-input"
                value={chatwootForm.base_url}
                onChange={(e) => setChatwootForm(prev => ({ ...prev, base_url: e.target.value }))}
                placeholder="https://app.chatwoot.com/api/v1"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-row">
              <label className="form-label">API Token</label>
              <input
                type="password"
                className="form-input"
                value={chatwootForm.api_token}
                onChange={(e) => setChatwootForm(prev => ({ ...prev, api_token: e.target.value }))}
                placeholder={channels.find(c => c.name === 'chatwoot')?.config?.api_token_configured ? '已配置，留空不修改' : '请输入 Agent Bot Token 或 User Token'}
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-row">
              <label className="form-label">Account ID</label>
              <input
                type="text"
                className="form-input"
                value={chatwootForm.account_id}
                onChange={(e) => setChatwootForm(prev => ({ ...prev, account_id: e.target.value }))}
                placeholder="1"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-row">
              <label className="form-label">Inbox ID</label>
              <input
                type="text"
                className="form-input"
                value={chatwootForm.inbox_id}
                onChange={(e) => setChatwootForm(prev => ({ ...prev, inbox_id: e.target.value }))}
                placeholder="1"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-row">
              <label className="form-label">Webhook Token</label>
              <input
                type="password"
                className="form-input"
                value={chatwootForm.webhook_token}
                onChange={(e) => setChatwootForm(prev => ({ ...prev, webhook_token: e.target.value }))}
                placeholder={channels.find(c => c.name === 'chatwoot')?.config?.webhook_token_configured ? '已配置，留空不修改' : '请输入 Webhook 验证 Token'}
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            {channels.find(c => c.name === 'chatwoot')?.config?.webhook_url && (
              <div className="form-row">
                <label className="form-label">Webhook 回调地址</label>
                <div className="form-input readonly" onClick={(e) => e.stopPropagation()}>
                  {window.location.origin}{channels.find(c => c.name === 'chatwoot')?.config?.webhook_url}
                </div>
              </div>
            )}
            <div className="form-actions">
              <button
                className="btn btn-secondary"
                onClick={(e) => { e.stopPropagation(); handleTestChatwoot(); }}
                disabled={testing === 'chatwoot'}
              >
                {testing === 'chatwoot' ? '测试中...' : '测试连接'}
              </button>
              <button
                className="btn btn-primary"
                onClick={(e) => { e.stopPropagation(); handleSaveChatwoot(); }}
                disabled={saving === 'chatwoot'}
              >
                {saving === 'chatwoot' ? '保存中...' : '保存配置'}
              </button>
            </div>
            {saveMsg?.channel === 'chatwoot' && (
              <div className={`form-message ${saveMsg.type}`} onClick={(e) => e.stopPropagation()}>
                {saveMsg.text}
              </div>
            )}
            {testMsg?.channel === 'chatwoot' && (
              <div className={`form-message ${testMsg.type}`} onClick={(e) => e.stopPropagation()}>
                {testMsg.text}
              </div>
            )}
          </div>
          <div className="channel-detail-steps">
            <h5>配置说明</h5>
            <div className="step-list">
              <div className="step-item">
                <div className="step-number">1</div>
                <div className="step-content">
                  <p className="step-title">部署 Chatwoot</p>
                  <p className="step-desc">支持 Docker / 云部署 / 源码部署多种方式</p>
                </div>
              </div>
              <div className="step-item">
                <div className="step-number">2</div>
                <div className="step-content">
                  <p className="step-title">创建 Agent Bot</p>
                  <p className="step-desc">在 Chatwoot 中创建新的 Inbox 和 Agent Bot，获取 Token 填入上方</p>
                </div>
              </div>
              <div className="step-item">
                <div className="step-number">3</div>
                <div className="step-content">
                  <p className="step-title">配置 Webhook</p>
                  <p className="step-desc">将上方 Webhook 回调地址配置到 Chatwoot 的 Webhook 设置中</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      ),
    },
  ]

  return (
    <div className="channel-grid">
      {loading && <div className="admin-loading">加载渠道状态中...</div>}
      {!loading && channelConfigs.map(ch => {
        const isExpanded = expandedChannel === ch.name
        const enabled = getChannelStatus(ch.name)
        return (
          <div
            key={ch.name}
            className={`channel-card expandable ${isExpanded ? 'expanded' : ''}`}
            onClick={() => setExpandedChannel(isExpanded ? null : ch.name)}
          >
            <div className="channel-card-header">
              <span className="channel-icon">{ch.icon}</span>
              <div className="channel-info">
                <h4>{ch.name}</h4>
                <p>{ch.desc}</p>
              </div>
              <span className={`channel-badge ${enabled ? 'active' : 'inactive'}`}>{enabled ? '已启用' : '未配置'}</span>
              <span className="channel-expand-icon">{isExpanded ? '▲' : '▼'}</span>
            </div>
            {isExpanded && <div className="channel-detail">{ch.detail}</div>}
          </div>
        )
      })}
    </div>
  )
}

// ============================================================
// Sessions
// ============================================================

function SessionsTab({ token }: { token: string }) {
  const [sessions, setSessions] = useState<SessionItemData[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedSession, setSelectedSession] = useState<SessionItemData | null>(null)
  const [sessionDetailLoading, setSessionDetailLoading] = useState(false)

  const fetchSessions = useCallback(() => {
    setLoading(true)
    fetch('/api/v1/admin/sessions', { headers: { Authorization: `Bearer ${token}` } })
      .then(checkResponse)
      .then(data => setSessions((data.sessions || data || []) as SessionItemData[]))
      .catch(() => setSessions([]))
      .finally(() => setLoading(false))
  }, [token])

  const fetchSessionDetail = (sessionId: string) => {
    setSessionDetailLoading(true)
    setSelectedSession(null)
    fetch(`/api/v1/admin/sessions/${sessionId}`, { headers: { Authorization: `Bearer ${token}` } })
      .then(checkResponse)
      .then(data => setSelectedSession(data as SessionItemData))
      .catch(() => setSelectedSession(null))
      .finally(() => setSessionDetailLoading(false))
  }

  const deleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('确定要删除这个会话吗？')) return
    try {
      await fetchApi(`/admin/sessions/${sessionId}`, token, { method: 'DELETE' })
      setSessions(prev => prev.filter(s => s.session_id !== sessionId))
      setSelectedSession(null)
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败')
    }
  }

  useEffect(() => { fetchSessions() }, [fetchSessions])

  if (selectedSession) {
    return (
      <div className="session-detail">
        <button className="back-btn" onClick={() => setSelectedSession(null)}>← 返回列表</button>
        {sessionDetailLoading && <div className="admin-loading">加载会话详情中...</div>}
        {!sessionDetailLoading && selectedSession && (
          <>
            <div className="session-detail-header">
              <h3>会话详情</h3>
              <button className="delete-session-btn" onClick={(e) => deleteSession(selectedSession.session_id, e)}>🗑 删除会话</button>
            </div>
            <div className="session-detail-info">
              <p><strong>会话ID：</strong>{selectedSession.session_id}</p>
              <p><strong>用户ID：</strong>{selectedSession.user_id}</p>
              <p><strong>模式：</strong>{selectedSession.mode}</p>
              <p><strong>创建时间：</strong>{formatDate(selectedSession.created_at)}</p>
              <p><strong>最后活跃：</strong>{formatDate(selectedSession.last_active)}</p>
              <p><strong>轮数：</strong>{selectedSession.turn_count}</p>
            </div>
            {selectedSession.conversation_history && selectedSession.conversation_history.length > 0 && (
              <div className="session-messages">
                <h4>消息记录</h4>
                <div className="session-message-list">
                  {selectedSession.conversation_history.map((msg, idx) => (
                    <div key={idx} className={`session-message ${msg.role}`}>
                      <span className="session-message-role">{msg.role === 'user' ? '用户' : msg.role === 'assistant' ? 'AI' : '系统'}</span>
                      <p className="session-message-content">{msg.content}</p>
                      {msg.timestamp && <span className="session-message-time">{formatDate(msg.timestamp)}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    )
  }

  return (
    <div className="sessions-container">
      <div className="sessions-header">
        <h3>会话列表</h3>
        <button className="refresh-btn" onClick={fetchSessions} disabled={loading}>刷新</button>
      </div>
      {loading && <div className="admin-loading">加载会话列表中...</div>}
      {!loading && sessions.length === 0 && <div className="sessions-placeholder"><p>暂无会话数据</p></div>}
      {!loading && sessions.length > 0 && (
        <div className="sessions-table-wrap">
          <table className="sessions-table">
            <thead>
              <tr><th>会话ID</th><th>用户ID</th><th>模式</th><th>最后消息</th><th>最后活跃</th><th>轮数</th><th>操作</th></tr>
            </thead>
            <tbody>
              {sessions.map(session => (
                <tr key={session.session_id} className="session-row" onClick={() => fetchSessionDetail(session.session_id)}>
                  <td className="session-id">{session.session_id}</td>
                  <td>{session.user_id}</td>
                  <td><span className={`session-status ${session.mode}`}>{session.mode}</span></td>
                  <td>{session.last_message_preview || '-'}</td>
                  <td>{formatDate(session.last_active)}</td>
                  <td>{session.turn_count}</td>
                  <td>
                    <button className="delete-row-btn" onClick={(e) => deleteSession(session.session_id, e)}>删除</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ============================================================
// Agent workspace
// ============================================================

function AgentTab({ token, user }: { token: string; user: Props['user'] }) {
  const [handoffQueue, setHandoffQueue] = useState<HandoffItem[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedHandoff, setSelectedHandoff] = useState<HandoffItem | null>(null)
  const [agentReply, setAgentReply] = useState('')
  const [replying, setReplying] = useState(false)

  const agentId = user?.username || 'admin'

  const fetchHandoffQueue = useCallback(() => {
    setLoading(true)
    fetch('/api/v1/admin/handoff/queue', { headers: { Authorization: `Bearer ${token}` } })
      .then(checkResponse)
      .then(data => setHandoffQueue((data.queue || data || []) as HandoffItem[]))
      .catch(() => setHandoffQueue([]))
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => { fetchHandoffQueue() }, [fetchHandoffQueue])

  const handleAccept = async () => {
    if (!selectedHandoff) return
    try {
      await postJson(`/admin/handoff/${selectedHandoff.session_id}/accept`, token, { agent_id: agentId })
      setSelectedHandoff({ ...selectedHandoff, mode: 'human_chat', assigned_agent: agentId })
      fetchHandoffQueue()
    } catch (err) {
      alert(err instanceof Error ? err.message : '接入失败')
    }
  }

  const handleReply = async () => {
    if (!selectedHandoff || !agentReply.trim()) return
    setReplying(true)
    try {
      await postJson(`/admin/handoff/${selectedHandoff.session_id}/reply`, token, { message: agentReply, agent_id: agentId })
      setAgentReply('')
      fetchHandoffQueue()
    } catch (err) {
      alert(err instanceof Error ? err.message : '发送失败')
    } finally {
      setReplying(false)
    }
  }

  const handleClose = async () => {
    if (!selectedHandoff) return
    if (!confirm('确定要结束人工服务吗？')) return
    try {
      await postJson(`/admin/handoff/${selectedHandoff.session_id}/close`, token, { agent_id: agentId })
      setSelectedHandoff(null)
      fetchHandoffQueue()
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    }
  }

  if (selectedHandoff) {
    return (
      <div className="handoff-detail">
        <div className="handoff-detail-header">
          <button className="back-btn" onClick={() => setSelectedHandoff(null)}>← 返回队列</button>
          <div className="handoff-detail-actions">
            {selectedHandoff.mode === 'waiting_human' && (
              <button className="btn-primary-small" onClick={handleAccept} disabled={replying}>✅ 接入会话</button>
            )}
            {selectedHandoff.mode === 'human_chat' && (
              <button className="btn-secondary-small" onClick={handleClose} disabled={replying}>🔚 结束服务</button>
            )}
          </div>
        </div>

        <div className="handoff-context">
          <h4>📋 AI 转接上下文</h4>
          {selectedHandoff.handoff_context ? (
            <div className="context-content">
              <div className="context-section">
                <h5>对话摘要</h5>
                <p className="context-text">{selectedHandoff.handoff_context.summary || '暂无摘要'}</p>
              </div>
              <div className="context-section">
                <h5>转接原因</h5>
                <p className="context-text reason">{selectedHandoff.handoff_context.reason || '用户请求'}</p>
              </div>
              {selectedHandoff.handoff_context.urgency && (
                <div className="context-section">
                  <h5>紧急度</h5>
                  <span className={`urgency-badge ${selectedHandoff.handoff_context.urgency}`}>
                    {selectedHandoff.handoff_context.urgency === 'critical' ? '🔴 紧急' :
                     selectedHandoff.handoff_context.urgency === 'high' ? '🟠 高' :
                     selectedHandoff.handoff_context.urgency === 'normal' ? '🟡 中' : '🟢 低'}
                  </span>
                </div>
              )}
              {selectedHandoff.handoff_context.attempted_solutions && (
                <div className="context-section">
                  <h5>AI 已尝试方案</h5>
                  <ul className="attempted-list">
                    {(selectedHandoff.handoff_context.attempted_solutions.steps || []).map((step, idx) => <li key={idx}>{step}</li>)}
                  </ul>
                </div>
              )}
              {selectedHandoff.handoff_context.user_profile && (
                <div className="context-section">
                  <h5>用户画像</h5>
                  <div className="user-profile-grid">
                    <div className="profile-item">
                      <span className="profile-label">用户ID</span>
                      <span className="profile-value">{selectedHandoff.handoff_context.user_profile.user_id || '-'}</span>
                    </div>
                    <div className="profile-item">
                      <span className="profile-label">订阅计划</span>
                      <span className="profile-value">{selectedHandoff.handoff_context.user_profile.plan || '免费'}</span>
                    </div>
                  </div>
                </div>
              )}
              {selectedHandoff.handoff_context.current_blocker?.items && (
                <div className="context-section">
                  <h5>当前卡点</h5>
                  <div className="blocker-list">
                    {selectedHandoff.handoff_context.current_blocker.items.map((blocker, idx) => (
                      <div key={idx} className={`blocker-item ${blocker.severity}`}>
                        <span className="blocker-type">{blocker.type}</span>
                        <span className="blocker-detail">{blocker.detail}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : <p className="context-empty">暂无转接上下文</p>}
        </div>

        <div className="handoff-messages">
          <h4>💬 完整对话记录</h4>
          <div className="handoff-message-list">
            {(selectedHandoff.handoff_context?.conversation || []).map((msg, idx) => (
              <div key={idx} className={`handoff-msg ${msg.role}`}>
                <span className="handoff-msg-role">{msg.role === 'user' ? '用户' : 'AI客服'}</span>
                <p className="handoff-msg-text">{msg.content}</p>
              </div>
            ))}
          </div>
        </div>

        {selectedHandoff.mode === 'human_chat' && (
          <div className="agent-reply-area">
            <textarea
              className="agent-reply-input"
              value={agentReply}
              onChange={e => setAgentReply(e.target.value)}
              placeholder="输入回复内容..."
              rows={3}
              disabled={replying}
            />
            <button className="btn-primary-small agent-send-btn" onClick={handleReply} disabled={!agentReply.trim() || replying}>
              {replying ? '发送中...' : '📤 发送回复'}
            </button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="agent-workspace">
      <div className="agent-header">
        <div>
          <h3>转接队列</h3>
          <p className="agent-subtitle">等待人工客服接入的会话</p>
        </div>
        <button className="refresh-btn" onClick={fetchHandoffQueue} disabled={loading}>🔄 刷新</button>
      </div>
      {loading && <div className="admin-loading">加载转接队列中...</div>}
      {!loading && handoffQueue.length === 0 && (
        <div className="sessions-placeholder">
          <p>🎉 暂无转接请求</p>
          <p className="hint">所有用户问题都已被 AI 成功解决</p>
        </div>
      )}
      {!loading && handoffQueue.length > 0 && (
        <div className="handoff-list">
          {handoffQueue.map(item => (
            <div key={item.session_id} className={`handoff-card ${item.mode === 'human_chat' ? 'active' : ''}`} onClick={() => { setSelectedHandoff(item); setAgentReply('') }}>
              <div className="handoff-card-header">
                <span className={`handoff-status ${item.mode}`}>
                  {item.mode === 'waiting_human' ? '⏳ 等待接入' : '💬 服务中'}
                </span>
                {item.mode === 'waiting_human' && item.wait_time !== undefined && (
                  <span className="handoff-wait">等待 {formatDuration(item.wait_time)}</span>
                )}
              </div>
              <div className="handoff-user">
                <span className="handoff-user-icon">👤</span>
                <div>
                  <p className="handoff-user-id">{item.user_id}</p>
                  <p className="handoff-preview">{item.last_message_preview || '暂无消息'}</p>
                </div>
              </div>
              <div className="handoff-meta">
                <span>📊 {item.turn_count} 轮对话</span>
                <span>🕐 {item.last_active ? new Date(item.last_active * 1000).toLocaleTimeString('zh-CN') : '-'}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================
// Agent Health Monitor — Agent 健康监控
// ============================================================

interface AgentHealthInfo {
  agent_id: string
  name: string
  url: string
  status: 'online' | 'offline'
  last_heartbeat_age_sec: number
  circuit_state: 'closed' | 'open' | 'half_open'
  failures: number
}

interface HealthStatus {
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

function HealthTab({ token }: { token: string }) {
  const [status, setStatus] = useState<HealthStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [actingAgent, setActingAgent] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)

  const load = useCallback(() => {
    setRefreshing(true)
    fetchJson('/health/agents', token)
      .then(data => { setStatus(data as HealthStatus); setError('') })
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => { setLoading(false); setRefreshing(false) })
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  // 自动刷新：每 10 秒拉一次最新状态
  useEffect(() => {
    if (!autoRefresh) return
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [autoRefresh, load])

  const handleHeartbeat = async (agentId: string) => {
    setActingAgent(agentId)
    try {
      await postJson(`/health/agents/${agentId}/heartbeat`, token, {})
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '上报心跳失败')
    } finally {
      setActingAgent(null)
    }
  }

  const handleResetCircuit = async (agentId: string) => {
    if (!confirm(`确认重置 ${agentId} 的熔断器？`)) return
    setActingAgent(agentId)
    try {
      await postJson(`/health/agents/${agentId}/circuit/reset`, token, {})
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '重置失败')
    } finally {
      setActingAgent(null)
    }
  }

  const statusColor = (s: string) => s === 'online' ? '#10b981' : '#ef4444'
  const circuitColor = (s: string) => s === 'closed' ? '#10b981' : s === 'half_open' ? '#f59e0b' : '#ef4444'
  const circuitLabel = (s: string) => s === 'closed' ? '正常' : s === 'half_open' ? '半开' : '已断开'

  if (loading) return <div className="admin-loading">加载健康状态...</div>
  if (error) return <div className="admin-error">{error}</div>
  if (!status) return null

  return (
    <div>
      {/* 顶部统计 */}
      <div className="metrics-grid">
        <StatCard label="Agent 总数" value={String(status.total_agents)} />
        <StatCard label="在线" value={String(status.online_agents)} color="#10b981" />
        <StatCard label="离线" value={String(status.offline_agents)} color="#ef4444" />
        <StatCard label="心跳阈值(秒)" value={String(status.threshold_seconds)} />
        <StatCard label="扫描间隔(秒)" value={String(status.scan_interval_seconds)} />
        <StatCard label="主动探活" value={status.probe_enabled ? '开启' : '关闭'} />
      </div>

      {/* 控制栏 */}
      <div className="health-controls">
        <label className="auto-refresh-toggle">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={e => setAutoRefresh(e.target.checked)}
          />
          <span>每 10 秒自动刷新</span>
        </label>
        <button className="btn-secondary-small" onClick={load} disabled={refreshing}>
          {refreshing ? '刷新中...' : '🔄 手动刷新'}
        </button>
      </div>

      {/* Agent 卡片列表 */}
      <div className="sessions-container" style={{ marginTop: 16 }}>
        <h3 className="detail-title">Agent 列表</h3>
        {status.agents.length === 0 ? (
          <p className="hint">暂无注册 Agent</p>
        ) : (
          <div className="health-agent-grid">
            {status.agents.map(a => (
              <div key={a.agent_id} className={`health-agent-card status-${a.status}`}>
                <div className="health-agent-header">
                  <div className="health-agent-name">{a.name}</div>
                  <span
                    className="health-status-badge"
                    style={{ background: statusColor(a.status), color: '#fff' }}
                  >
                    ● {a.status === 'online' ? '在线' : '离线'}
                  </span>
                </div>
                <div className="health-agent-id">{a.agent_id}</div>
                <div className="health-agent-meta">
                  <div className="meta-row">
                    <span className="meta-label">URL</span>
                    <span className="meta-value" title={a.url}>{a.url}</span>
                  </div>
                  <div className="meta-row">
                    <span className="meta-label">心跳年龄</span>
                    <span className="meta-value">{a.last_heartbeat_age_sec} 秒</span>
                  </div>
                  <div className="meta-row">
                    <span className="meta-label">熔断状态</span>
                    <span
                      className="meta-value circuit-state"
                      style={{ color: circuitColor(a.circuit_state) }}
                    >
                      {circuitLabel(a.circuit_state)} ({a.failures} 失败)
                    </span>
                  </div>
                </div>
                <div className="health-agent-actions">
                  <button
                    className="btn-secondary-small"
                    onClick={() => handleHeartbeat(a.agent_id)}
                    disabled={actingAgent === a.agent_id}
                  >
                    ❤️ 上报心跳
                  </button>
                  <button
                    className="btn-secondary-small"
                    onClick={() => handleResetCircuit(a.agent_id)}
                    disabled={actingAgent === a.agent_id || a.circuit_state === 'closed'}
                    title={a.circuit_state === 'closed' ? '熔断器正常，无需重置' : '重置熔断器'}
                  >
                    🔧 重置熔断
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 熔断器统计表 */}
      {Object.keys(status.circuit_breakers || {}).length > 0 && (
        <div className="sessions-container" style={{ marginTop: 16 }}>
          <h3 className="detail-title">熔断器统计</h3>
          <div className="comment-list">
            {Object.entries(status.circuit_breakers).map(([aid, info]) => (
              <div key={aid} className="comment-item">
                <div className="comment-header">
                  <span className="comment-author">{aid}</span>
                  <span
                    className="comment-time"
                    style={{ color: circuitColor(info.state) }}
                  >
                    {circuitLabel(info.state)}
                  </span>
                </div>
                <p className="comment-content">累计失败 {info.failures} 次</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ============================================================
// Main component
// ============================================================

type TabKey = 'dashboard' | 'tickets' | 'customers' | 'satisfaction' | 'notifications' | 'rbac' | 'channels' | 'sessions' | 'agent' | 'health'

const TABS: { key: TabKey; label: string; permission: string }[] = [
  { key: 'dashboard', label: '仪表盘', permission: 'dashboard:view' },
  { key: 'tickets', label: '工单看板', permission: 'ticket:view' },
  { key: 'customers', label: '客户管理', permission: 'customer:view' },
  { key: 'satisfaction', label: '满意度', permission: 'satisfaction:view' },
  { key: 'notifications', label: '通知中心', permission: 'notification:view' },
  { key: 'rbac', label: '权限管理', permission: 'user:view' },
  { key: 'channels', label: '渠道管理', permission: 'channel:view' },
  { key: 'sessions', label: '会话管理', permission: 'agent:workspace' },
  { key: 'agent', label: '人工坐席', permission: 'agent:workspace' },
  { key: 'health', label: 'Agent 监控', permission: 'agent:workspace' },
]

export default function AdminDashboard({ isOpen, onClose, user, token, onLoginClick }: Props) {
  const [rbac, setRbac] = useState<RbacInfo | null>(null)
  const [rbacLoading, setRbacLoading] = useState(false)
  const [rbacError, setRbacError] = useState('')
  const [loginRequired, setLoginRequired] = useState(false)
  const [activeTab, setActiveTab] = useState<TabKey>('dashboard')

  useEffect(() => {
    if (!isOpen) return
    setRbac(null)
    setRbacError('')
    setLoginRequired(false)
    if (!token) {
      setLoginRequired(true)
      return
    }
    setRbacLoading(true)
    fetch('/api/v1/rbac/me/permissions', { headers: { Authorization: `Bearer ${token}` } })
      .then(async r => {
        if (r.status === 401 || r.status === 403) {
          setLoginRequired(true)
          throw new ApiError(r.status, '登录已过期或权限不足')
        }
        if (!r.ok) throw new ApiError(r.status, '获取权限失败')
        return r.json()
      })
      .then((data: RbacInfo) => setRbac(data))
      .catch(err => {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          return
        }
        setRbacError(err instanceof Error ? err.message : '获取权限失败')
      })
      .finally(() => setRbacLoading(false))
  }, [isOpen, token])

  const hasPermission = useCallback((permission: string) => {
    return !!rbac && rbac.permissions.includes(permission)
  }, [rbac])

  const visibleTabs = useMemo(() => TABS.filter(t => hasPermission(t.permission)), [hasPermission])

  useEffect(() => {
    if (visibleTabs.length > 0 && !visibleTabs.find(t => t.key === activeTab)) {
      setActiveTab(visibleTabs[0].key)
    }
  }, [visibleTabs, activeTab])

  const renderTabContent = () => {
    if (!token) return null
    switch (activeTab) {
      case 'dashboard': return <DashboardTab token={token} />
      case 'tickets': return <TicketsTab token={token} user={user} hasPermission={hasPermission} />
      case 'customers': return <CustomersTab token={token} hasPermission={hasPermission} />
      case 'satisfaction': return <SatisfactionTab token={token} />
      case 'notifications': return <NotificationsTab token={token} />
      case 'rbac': return <RbacTab token={token} user={user} hasPermission={hasPermission} />
      case 'channels': return <ChannelsTab token={token} />
      case 'sessions': return <SessionsTab token={token} />
      case 'agent': return <AgentTab token={token} user={user} />
      case 'health': return <HealthTab token={token} />
      default: return null
    }
  }

  if (!isOpen) return null

  return (
    <div className="admin-modal-overlay" onClick={onClose}>
      <div className="admin-modal" onClick={e => e.stopPropagation()}>
        <button className="admin-modal-close" onClick={onClose}>×</button>
        <div className="admin-modal-content">
          <p className="section-label">Admin Dashboard</p>
          <h2 className="admin-title">管理后台</h2>
          {user && (
            <div className="admin-user-bar">
              <span className="admin-user-name">{user.username}</span>
              {rbac && <span className={`role-badge role-${rbac.role}`}>{rbac.role_label}</span>}
            </div>
          )}

          {loginRequired && (
            <div className="sessions-placeholder">
              <p>请先登录以访问管理后台</p>
              <button className="btn-primary" style={{ marginTop: 16 }} onClick={onLoginClick}>去登录</button>
            </div>
          )}

          {rbacLoading && <div className="admin-loading">加载权限中...</div>}
          {rbacError && <div className="admin-error">{rbacError}</div>}

          {!rbacLoading && !rbacError && !loginRequired && rbac && (
            <>
              <div className="admin-tabs">
                {visibleTabs.map(t => (
                  <button
                    key={t.key}
                    className={`tab-btn ${activeTab === t.key ? 'active' : ''}`}
                    onClick={() => setActiveTab(t.key)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
              {visibleTabs.length === 0 ? (
                <div className="sessions-placeholder"><p>当前账号无任何权限</p></div>
              ) : (
                <div className="tab-content">{renderTabContent()}</div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
