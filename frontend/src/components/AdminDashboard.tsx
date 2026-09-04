import { useCallback, useEffect, useState, useMemo } from 'react'
import { ApiError } from './admin/api'
import type { Props, RbacInfo, TabKey } from './admin/types'
import { DashboardTab, TicketsTab, CustomersTab, SatisfactionTab, NotificationsTab, RbacTab, ChannelsTab, SessionsTab, AgentTab, HealthTab, MonitoringTab, ConfigTab, EvaluationTab, WorkflowTab, KnowledgeTab } from './admin'

const TABS: { key: TabKey; label: string; permission: string; group: string }[] = [
  { key: 'dashboard', label: '仪表盘', permission: 'dashboard:view', group: '概览' },
  { key: 'tickets', label: '工单看板', permission: 'ticket:view', group: '业务运营' },
  { key: 'customers', label: '客户管理', permission: 'customer:view', group: '业务运营' },
  { key: 'satisfaction', label: '满意度', permission: 'satisfaction:view', group: '业务运营' },
  { key: 'notifications', label: '通知中心', permission: 'notification:view', group: '业务运营' },
  { key: 'sessions', label: '会话管理', permission: 'agent:workspace', group: 'AI 与 Agent' },
  { key: 'agent', label: '人工坐席', permission: 'agent:workspace', group: 'AI 与 Agent' },
  { key: 'knowledge', label: '知识库', permission: 'agent:workspace', group: 'AI 与 Agent' },
  { key: 'health', label: 'Agent 监控', permission: 'agent:workspace', group: 'AI 与 Agent' },
  { key: 'workflow', label: '工作流', permission: 'workflow:view', group: 'AI 与 Agent' },
  { key: 'evaluation', label: '评估管理', permission: 'evaluation:view', group: 'AI 与 Agent' },
  { key: 'monitoring', label: '监控大屏', permission: 'monitor:view', group: '系统管理' },
  { key: 'rbac', label: '权限管理', permission: 'user:view', group: '系统管理' },
  { key: 'channels', label: '渠道管理', permission: 'channel:view', group: '系统管理' },
  { key: 'config', label: '配置中心', permission: 'config:view', group: '系统管理' },
]

const TAB_GROUP_ORDER = ['概览', '业务运营', 'AI 与 Agent', '系统管理']

export default function AdminDashboard({ user, token, onLoginClick, onBack }: Props) {
  const [rbac, setRbac] = useState<RbacInfo | null>(null)
  const [rbacLoading, setRbacLoading] = useState(false)
  const [rbacError, setRbacError] = useState('')
  const [loginRequired, setLoginRequired] = useState(false)
  const [activeTab, setActiveTab] = useState<TabKey>(() => {
    // 从 URL hash 读取初始 tab（支持 #/admin/tickets 深链）
    const hash = window.location.hash
    const match = hash.match(/^#\/admin\/(\w+)$/)
    if (match) {
      const key = match[1] as TabKey
      if (TABS.find(t => t.key === key)) return key
    }
    return 'dashboard'
  })

  useEffect(() => {
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
  }, [token])

  const hasPermission = useCallback((permission: string) => {
    return !!rbac && rbac.permissions.includes(permission)
  }, [rbac])

  const visibleTabs = useMemo(() => TABS.filter(t => hasPermission(t.permission)), [hasPermission])

  const groupedTabs = useMemo(() => {
    const groups: { group: string; items: typeof TABS }[] = []
    for (const g of TAB_GROUP_ORDER) {
      const items = visibleTabs.filter(t => t.group === g)
      if (items.length > 0) groups.push({ group: g, items })
    }
    return groups
  }, [visibleTabs])

  // 子页面路由：tab 切换时更新 URL hash，支持浏览器前进/后退导航
  const handleTabChange = useCallback((key: TabKey) => {
    setActiveTab(key)
    const newHash = `#/admin/${key}`
    if (window.location.hash !== newHash) {
      window.location.hash = newHash
    }
  }, [])

  useEffect(() => {
    const onHashChange = () => {
      const hash = window.location.hash
      const match = hash.match(/^#\/admin\/(\w+)$/)
      if (match) {
        const key = match[1] as TabKey
        if (TABS.find(t => t.key === key)) setActiveTab(key)
      } else if (hash === '#/admin' || hash === '') {
        setActiveTab('dashboard')
      }
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    if (visibleTabs.length > 0 && !visibleTabs.find(t => t.key === activeTab)) {
      handleTabChange(visibleTabs[0].key)
    }
  }, [visibleTabs, activeTab, handleTabChange])

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
      case 'monitoring': return <MonitoringTab token={token} />
      case 'config': return <ConfigTab token={token} hasPermission={hasPermission} />
      case 'evaluation': return <EvaluationTab token={token} hasPermission={hasPermission} />
      case 'workflow': return <WorkflowTab token={token} hasPermission={hasPermission} />
      case 'knowledge': return <KnowledgeTab token={token} user={user} hasPermission={hasPermission} />
      default: return null
    }
  }

  return (
    <div className="admin-layout" data-testid="admin-dashboard">
      <header className="admin-topbar">
        <div className="admin-topbar-left">
          <button className="admin-back-btn" onClick={onBack}>← 返回首页</button>
          <div className="admin-brand-mini">
            <div className="nav-logo">E</div>
            <span className="nav-title">Enterprise<span className="brand-highlight">AI</span></span>
          </div>
        </div>
        <div className="admin-topbar-right">
          {user && (
            <>
              <span className="admin-user-name">{user.username}</span>
              {rbac && <span className={`role-badge role-${rbac.role}`}>{rbac.role_label}</span>}
            </>
          )}
        </div>
      </header>

      <div className="admin-body">
        <aside className="admin-sidebar">
          <p className="section-label">Admin Dashboard</p>
          <h2 className="admin-title">管理后台</h2>
          <nav className="admin-tabs">
            {groupedTabs.map(({ group, items }) => (
              <div key={group} className="tab-group">
                <div className="tab-group-label">{group}</div>
                {items.map(t => (
                  <button
                    key={t.key}
                    data-testid={`admin-tab-${t.key}`}
                    className={`tab-btn ${activeTab === t.key ? 'active' : ''}`}
                    onClick={() => handleTabChange(t.key)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            ))}
          </nav>
        </aside>

        <main className="admin-main">
          {loginRequired && (
            <div className="sessions-placeholder">
              <p>请先登录以访问管理后台</p>
              <button className="btn-primary" style={{ marginTop: 16 }} onClick={onLoginClick}>去登录</button>
            </div>
          )}

          {rbacLoading && <div className="admin-loading">加载权限中...</div>}
          {rbacError && <div className="admin-error">{rbacError}</div>}

          {!rbacLoading && !rbacError && !loginRequired && rbac && (
            <div className="tab-content">
              {visibleTabs.length === 0 ? (
                <div className="sessions-placeholder"><p>当前账号无任何权限</p></div>
              ) : (
                renderTabContent()
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
