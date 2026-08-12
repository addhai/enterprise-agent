import { useCallback, useEffect, useState } from 'react'
import { fetchJson } from './api'
import { StatCard } from './StatCard'
import type { MetricsAll, MetricsRisk, MetricsSystem } from './types'

export function MonitoringTab({ token }: { token: string }) {
  const [all, setAll] = useState<MetricsAll | null>(null)
  const [risk, setRisk] = useState<MetricsRisk | null>(null)
  const [sys, setSys] = useState<MetricsSystem | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [updatedAt, setUpdatedAt] = useState<number | null>(null)

  const load = useCallback(() => {
    Promise.all([
      fetchJson('/metrics/all', token).catch(() => null),
      fetchJson('/metrics/risk', token).catch(() => null),
      fetchJson('/metrics/system', token).catch(() => null),
    ]).then(([a, r, s]) => {
      if (a) setAll(a as MetricsAll)
      if (r) setRisk(r as MetricsRisk)
      if (s) setSys(s as MetricsSystem)
      setUpdatedAt(Date.now())
      setError('')
    }).catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!autoRefresh) return
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [autoRefresh, load])

  const pct = (v: number | null | undefined) => (v == null || isNaN(v)) ? '-' : `${(v * 100).toFixed(1)}%`
  const num = (v: number | null | undefined) => (v == null || isNaN(v)) ? '-' : String(v)
  const fmtUptime = (sec?: number) => {
    if (sec == null) return '-'
    const h = Math.floor(sec / 3600)
    const m = Math.floor((sec % 3600) / 60)
    const s = Math.floor(sec % 60)
    return `${h}小时${m}分${s}秒`
  }

  if (loading && !all && !risk && !sys) return <div className="admin-loading">加载监控指标...</div>
  if (error && !all && !risk && !sys) return <div className="admin-error">{error}</div>

  // 风险等级：综合升级率/低质率/未解决率
  const riskScore = Math.max(
    risk?.escalation_rate ?? 0,
    risk?.low_quality_rate ?? 0,
    risk?.unresolved_rate ?? 0,
  )
  const riskLevel = riskScore > 0.5 ? { label: '高危', color: '#ef4444' } : riskScore > 0.2 ? { label: '预警', color: '#f59e0b' } : { label: '健康', color: '#10b981' }

  const safetyEvents = risk?.safety_events || all?.safety_events || {}

  return (
    <div>
      {/* 控制栏 */}
      <div className="health-controls">
        <div className="monitor-updated">
          {updatedAt ? `最后更新：${new Date(updatedAt).toLocaleTimeString('zh-CN')}` : ''}
          {error && <span className="monitor-warn"> · 部分端点不可用</span>}
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <label className="auto-refresh-toggle">
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
            <span>每 5 秒自动刷新</span>
          </label>
          <button className="btn-secondary-small" onClick={load}>🔄 刷新</button>
        </div>
      </div>

      {/* 概览横幅 */}
      <div className="monitor-banner">
        <span className="monitor-risk-badge" style={{ background: riskLevel.color, color: '#fff' }}>
          风险等级：{riskLevel.label}
        </span>
        <span className="monitor-banner-text">
          指标由后端对话链路实时聚合（业务 / 质量 / 风险 / 系统）。Prometheus 抓取端点：<code>GET /api/v1/metrics/prometheus</code>
        </span>
      </div>

      {/* 业务指标 */}
      <h3 className="detail-title">📊 业务指标</h3>
      <div className="metrics-grid">
        <StatCard label="累计请求" value={num(all?.total_requests)} />
        <StatCard label="会话总数" value={num(all?.total_sessions)} />
        <StatCard label="已解决" value={num(all?.resolved)} color="#10b981" />
        <StatCard label="未解决" value={num(all?.unresolved)} color={all && all.unresolved > 0 ? '#f59e0b' : undefined} />
        <StatCard label="解决率" value={pct(all?.resolution_rate)} color="#10b981" />
        <StatCard label="转人工率" value={pct(all?.escalation_rate)} color="#f59e0b" />
        <StatCard label="平均轮次" value={num(all?.avg_turns)} />
        <StatCard label="平均时延(ms)" value={num(all?.avg_latency_ms)} />
      </div>

      {/* 质量指标 */}
      <h3 className="detail-title" style={{ marginTop: 18 }}>✨ 质量指标</h3>
      <div className="metrics-grid">
        <StatCard label="平均质量分" value={num(all?.avg_quality_score)} color="#6366f1" />
        <StatCard label="低风险回复占比" value={pct(risk ? 1 - risk.low_quality_rate : null)} color="#10b981" />
      </div>

      {/* 风险指标 */}
      <h3 className="detail-title" style={{ marginTop: 18 }}>🛡️ 风险指标</h3>
      <div className="metrics-grid">
        <StatCard label="低质量回复率" value={pct(risk?.low_quality_rate)} color={risk && risk.low_quality_rate > 0.2 ? '#ef4444' : '#10b981'} />
        <StatCard label="未解决率" value={pct(risk?.unresolved_rate)} color={risk && risk.unresolved_rate > 0.2 ? '#f59e0b' : '#10b981'} />
        <StatCard label="Prompt 注入拦截" value={num(risk?.prompt_injections_blocked ?? all?.prompt_injections_blocked)} color="#ef4444" />
        <StatCard label="安全违规" value={num(risk?.safety_violations ?? all?.safety_violations)} color="#ef4444" />
        <StatCard label="幻觉检测" value={num(risk?.hallucinations_detected ?? all?.hallucinations_detected)} color="#f59e0b" />
        <StatCard label="幻觉拦截" value={num(risk?.hallucinations_blocked ?? all?.hallucinations_blocked)} color="#10b981" />
      </div>
      {Object.keys(safetyEvents).length > 0 && (
        <div className="monitor-events">
          {Object.entries(safetyEvents).map(([k, v]) => (
            <span key={k} className="monitor-event-pill">{k}：{v}</span>
          ))}
        </div>
      )}

      {/* 系统指标 */}
      <h3 className="detail-title" style={{ marginTop: 18 }}>⚙️ 系统指标</h3>
      <div className="metrics-grid">
        <StatCard label="运行时长" value={fmtUptime(sys?.uptime_seconds)} />
        <StatCard
          label="数据库"
          value={sys?.database?.reachable ? '可达' : '不可达'}
          color={sys?.database?.reachable ? '#10b981' : '#ef4444'}
        />
        <StatCard label="DB 后端" value={sys?.database?.backend || '-'} />
        <StatCard label="CPU 占用" value={sys?.cpu_percent == null ? 'N/A' : `${sys.cpu_percent.toFixed(1)}%`} />
        <StatCard label="内存占用" value={sys?.memory_percent == null ? 'N/A' : `${sys.memory_percent.toFixed(1)}%`} />
        <StatCard label="活跃会话" value={num(sys?.active_sessions)} color="#6366f1" />
        <StatCard label="在线坐席" value={num(sys?.online_agents)} color="#10b981" />
        <StatCard label="进程 PID" value={num(sys?.pid)} />
      </div>
      {sys?.sessions_by_mode && Object.keys(sys.sessions_by_mode).length > 0 && (
        <div className="monitor-events">
          <span className="monitor-event-pill">会话模式分布：</span>
          {Object.entries(sys.sessions_by_mode).map(([mode, c]) => (
            <span key={mode} className="monitor-event-pill">{mode}：{c}</span>
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================
// Config Tab — 配置中心（P6）
// ============================================================

