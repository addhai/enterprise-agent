import { useEffect, useState } from 'react'
import { fetchJson, formatDate, formatDuration } from './api'
import { StatCard } from './StatCard'
import type { DashboardKpi, RealtimeActivity } from './types'

export function DashboardTab({ token }: { token: string }) {
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

