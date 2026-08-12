import { useCallback, useEffect, useState } from 'react'
import { fetchJson, postJson, formatDate } from './api'
import type { NotificationItem } from './types'

export function NotificationsTab({ token }: { token: string }) {
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

