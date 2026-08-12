import { useCallback, useEffect, useState } from 'react'
import { fetchApi, fetchJson, putJson, formatDate, formatDateShort } from './api'
import type { CustomerItem, CustomerDetail, CustomerTimelineEvent } from './types'
import { CUSTOMER_STATUSES } from './constants'

export function CustomersTab({ token, hasPermission }: { token: string; hasPermission: (p: string) => boolean }) {
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

  useEffect(() => {
    if (customers.length && !selectedId) {
      openDetail(customers[0])
    }
  }, [customers, selectedId])

  const detailView = selectedId ? (
    <div className="detail-panel split-detail-panel">
      {detailLoading && <div className="admin-loading">加载客户详情...</div>}
      {!detailLoading && !detail && <div className="detail-empty"><p>未找到客户</p></div>}
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
  ) : (
    <div className="detail-empty">
      <div className="detail-empty-icon">👤</div>
      <p>选择一个客户查看详情</p>
    </div>
  )

  return (
    <div className="split-layout">
      <div className="split-list-col">
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
                  <tr key={c.user_id} className={`session-row ${selectedId === c.user_id ? 'selected' : ''}`} onClick={() => openDetail(c)}>
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
      <div className="split-detail-col">
        {detailView}
      </div>
    </div>
  )
}

// ============================================================
// Satisfaction
// ============================================================

