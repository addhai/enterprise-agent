import { useCallback, useEffect, useState } from 'react'
import { fetchJson, postJson } from './api'
import { StatCard } from './StatCard'
import type { HealthStatus } from './types'

export function HealthTab({ token }: { token: string }) {
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
// Monitoring Tab — 监控大屏（对标阿里云客服工作台运营监控）
// 消费真实后端指标端点：
//   GET /api/v1/metrics/all     业务 + 质量核心
//   GET /api/v1/metrics/risk    风险（幻觉/注入/低质/未解决）
//   GET /api/v1/metrics/system 系统（运行时长/DB/CPU/内存/WS 会话）
// 数据全部由对话链路真实打点（routes/nodes/output_guard 写入 EvaluationTracker）
// ============================================================

