import { useCallback, useEffect, useState } from 'react'
import { fetchJson, postJson, putJson, formatDate, formatDateShort } from './api'
import type { Props, TicketItem } from './types'
import { TICKET_STATUSES, TICKET_PRIORITIES } from './constants'

export function TicketsTab({ token, user, hasPermission }: { token: string; user: Props['user']; hasPermission: (p: string) => boolean }) {
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

  useEffect(() => {
    if (tickets.length && !selected) {
      setSelected(tickets[0])
      setStatusEdit(tickets[0].status)
    }
  }, [tickets, selected])

  const detailView = selected ? (
    <div className="detail-panel split-detail-panel">
      <div className="detail-header">
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
  ) : (
    <div className="detail-empty">
      <div className="detail-empty-icon">🎫</div>
      <p>选择一个工单查看详情</p>
    </div>
  )

  return (
    <div className="split-layout">
      <div className="split-list-col">
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
                  <tr key={t.id} className={`session-row ${selected?.id === t.id ? 'selected' : ''}`} onClick={() => openDetail(t)}>
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
      <div className="split-detail-col">
        {detailView}
      </div>
    </div>
  )
}

// ============================================================
// Customers
// ============================================================

