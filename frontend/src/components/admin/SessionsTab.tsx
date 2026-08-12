import { useCallback, useEffect, useState } from 'react'
import { fetchApi, fetchJson, formatDate } from './api'
import type { SessionItemData } from './types'

export function SessionsTab({ token }: { token: string }) {
  const [sessions, setSessions] = useState<SessionItemData[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedSession, setSelectedSession] = useState<SessionItemData | null>(null)
  const [sessionDetailLoading, setSessionDetailLoading] = useState(false)

  const fetchSessions = useCallback(() => {
    setLoading(true)
    fetchJson('/admin/sessions', token)
      .then(data => setSessions((data.sessions || data || []) as SessionItemData[]))
      .catch(() => setSessions([]))
      .finally(() => setLoading(false))
  }, [token])

  const fetchSessionDetail = (sessionId: string) => {
    setSessionDetailLoading(true)
    setSelectedSession(null)
    fetchJson(`/admin/sessions/${sessionId}`, token)
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

      {/* LangGraph 五路径路由轨迹（概念示意，真实会话数据为空时展示） */}
      <div className="sessions-container" style={{ marginTop: 16 }}>
        <h3 className="detail-title">LangGraph 五路径路由轨迹</h3>
        <p className="hint" style={{ marginBottom: 12 }}>每条会话进入后，由意图识别节点选择以下五条路径之一处理。当前环境暂无真实会话数据，下方为路由概念示意。</p>
        <div className="route-flow">
          <div className="route-node route-start">用户消息</div>
          <div className="route-arrow">↓</div>
          <div className="route-node route-router">意图识别 / 路由决策</div>
          <div className="route-branches">
            <div className="route-branch">
              <span className="route-edge direct" />
              <div className="route-card">
                <div className="route-card-name" style={{ color: 'var(--brand-teal)' }}>① Direct 直答</div>
                <div className="route-card-desc">高频简单问答，模型直出，不触发检索与工具</div>
              </div>
            </div>
            <div className="route-branch">
              <span className="route-edge rag" />
              <div className="route-card">
                <div className="route-card-name" style={{ color: 'var(--brand-blue)' }}>② RAG 知识问答</div>
                <div className="route-card-desc">向量检索知识库，召回片段经阈值过滤后生成答案</div>
              </div>
            </div>
            <div className="route-branch">
              <span className="route-edge tool" />
              <div className="route-card">
                <div className="route-card-name" style={{ color: '#fbbf24' }}>③ Tool 工具调用</div>
                <div className="route-card-desc">调用真实云 API（ECS/RDS/SLB/Redis/云监控）查询或诊断</div>
              </div>
            </div>
            <div className="route-branch">
              <span className="route-edge agent" />
              <div className="route-card">
                <div className="route-card-name" style={{ color: 'var(--brand-purple)' }}>④ Agent 多步编排</div>
                <div className="route-card-desc">复杂任务多轮规划，串联多个工具与子目标</div>
              </div>
            </div>
            <div className="route-branch">
              <span className="route-edge human" />
              <div className="route-card">
                <div className="route-card-name" style={{ color: '#f87171' }}>⑤ Human 转人工</div>
                <div className="route-card-desc">低置信 / 高风险 / 用户要求，转接坐席工作台</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ============================================================
// Agent workspace
// ============================================================

