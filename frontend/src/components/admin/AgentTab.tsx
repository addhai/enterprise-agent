import { useCallback, useEffect, useState } from 'react'
import { checkResponse, postJson, formatDuration } from './api'
import type { Props, HandoffItem } from './types'

export function AgentTab({ token, user }: { token: string; user: Props['user'] }) {
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

