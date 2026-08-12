import { useCallback, useEffect, useState } from 'react'
import { fetchJson, putJson, formatDate } from './api'
import type { Props, RbacUser, RoleInfo } from './types'
import { USER_STATUSES } from './constants'

export function RbacTab({ token, user, hasPermission }: { token: string; user: Props['user']; hasPermission: (p: string) => boolean }) {
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

  const roleUserCount = (role: string) => users.filter(u => u.role === role).length

  const RESOURCES: { key: string; label: string }[] = [
    { key: 'dashboard', label: '仪表盘' },
    { key: 'customer', label: '客户' },
    { key: 'ticket', label: '工单' },
    { key: 'knowledge', label: '知识库' },
    { key: 'channel', label: '渠道' },
    { key: 'user', label: '用户' },
    { key: 'notification', label: '通知' },
    { key: 'monitor', label: '监控' },
    { key: 'config', label: '配置' },
    { key: 'evaluation', label: '评估' },
    { key: 'workflow', label: '工作流' },
  ]
  const hasRes = (perms: string[], res: string) => perms.some(p => p.startsWith(res + ':'))

  return (
    <div>
      <div className="filter-bar">
        <span className="notification-count">共 {users.length} 位用户 · {roles.length} 个角色</span>
        <button className="refresh-btn" onClick={fetchAll} disabled={loading}>刷新</button>
      </div>

      <h3 className="detail-title" style={{ marginTop: 16 }}>角色概览</h3>
      <div className="role-grid">
        {roles.map(r => (
          <div key={r.role} className="role-card">
            <div className="role-card-head">
              <span className={`role-badge role-${r.role}`}>{r.label}</span>
              <span className="role-card-count">{roleUserCount(r.role)} 人</span>
            </div>
            <div className="role-card-desc">{r.description}</div>
            <div className="role-card-perms">{r.permissions.length} 项权限点</div>
          </div>
        ))}
      </div>

      <h3 className="detail-title" style={{ marginTop: 20 }}>权限矩阵</h3>
      <div className="sessions-table-wrap">
        <table className="sessions-table rbac-matrix">
          <thead>
            <tr>
              <th>角色</th>
              {RESOURCES.map(res => <th key={res.key} title={res.label}>{res.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {roles.map(r => (
              <tr key={r.role}>
                <td><span className={`role-badge role-${r.role}`}>{r.label}</span></td>
                {RESOURCES.map(res => (
                  <td key={res.key} className="rbac-cell">
                    {hasRes(r.permissions, res.key)
                      ? <span className="rbac-dot on" title="有权限">●</span>
                      : <span className="rbac-dot off" title="无权限">○</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="detail-title" style={{ marginTop: 20 }}>用户列表</h3>
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

