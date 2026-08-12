import { useCallback, useEffect, useState } from 'react'
import { fetchApi, fetchJson, postJson, formatDate } from './api'
import { StatCard } from './StatCard'
import type { WorkflowInfo } from './types'

export function WorkflowTab({ token, hasPermission }: { token: string; hasPermission: (p: string) => boolean }) {
  const [workflows, setWorkflows] = useState<WorkflowInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedWf, setSelectedWf] = useState<WorkflowInfo | null>(null)
  const [wfDetail, setWfDetail] = useState<unknown>(null)
  const [nodeTypes, setNodeTypes] = useState<unknown[]>([])
  const canManage = hasPermission('workflow:manage')

  const load = useCallback(() => {
    Promise.all([
      fetchJson('/admin/workflows', token).catch(() => ({ workflows: [] })),
      fetchJson('/admin/workflows/meta/node-types', token).catch(() => ({ node_types: [] })),
    ])
      .then(([wfData, ntData]) => {
        setWorkflows(wfData.workflows || [])
        setNodeTypes(ntData.node_types || [])
        setError('')
      })
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => { load() }, [load])

  const viewDetail = async (wf: WorkflowInfo) => {
    setSelectedWf(wf)
    try {
      const data = await fetchJson(`/admin/workflows/${wf.id}`, token)
      setWfDetail(data)
    } catch (err) {
      alert(err instanceof Error ? err.message : '加载详情失败')
    }
  }

  const publishWorkflow = async (id: string) => {
    if (!canManage) return
    if (!confirm('确认发布该工作流？发布后将立即生效。')) return
    try {
      await postJson(`/admin/workflows/${id}/publish`, token, {})
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '发布失败')
    }
  }

  const validateWorkflow = async (id: string) => {
    try {
      const result = await postJson(`/admin/workflows/${id}/validate`, token, {})
      alert(`校验结果: ${JSON.stringify(result)}`)
    } catch (err) {
      alert(err instanceof Error ? err.message : '校验失败')
    }
  }

  const cloneWorkflow = async (id: string) => {
    if (!canManage) return
    const name = prompt('请输入克隆后的工作流名称：')
    if (!name) return
    try {
      await postJson(`/admin/workflows/${id}/clone`, token, { name })
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '克隆失败')
    }
  }

  const deleteWorkflow = async (id: string) => {
    if (!canManage) return
    if (!confirm('确认删除该工作流？此操作不可撤销。')) return
    try {
      await fetchApi(`/admin/workflows/${id}`, token, { method: 'DELETE' })
      setSelectedWf(null)
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败')
    }
  }

  if (loading) return <div className="admin-loading">加载工作流...</div>
  if (error) return <div className="admin-error">{error}</div>

  return (
    <div>
      <div className="metrics-grid">
        <StatCard label="工作流总数" value={String(workflows.length)} />
        <StatCard label="已发布" value={String(workflows.filter(w => w.is_published).length)} color="#10b981" />
        <StatCard label="默认工作流" value={String(workflows.filter(w => w.is_default).length)} color="#3b82f6" />
        <StatCard label="节点类型" value={String(nodeTypes.length)} />
      </div>

      <div className="health-controls">
        <button className="btn-secondary-small" onClick={load}>🔄 刷新</button>
      </div>

      {!selectedWf ? (
        <div className="sessions-container" style={{ marginTop: 16 }}>
          <h3 className="detail-title">工作流列表</h3>
          <div className="sessions-list">
            {workflows.length === 0 ? (
              <div className="sessions-placeholder"><p>暂无工作流</p></div>
            ) : workflows.map(wf => (
              <div key={wf.id} className="session-item" style={{ display: 'block', padding: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
                      {wf.name}
                      {wf.is_default && <span className="role-badge default-wf">默认</span>}
                      {wf.is_published && <span className="role-badge published">已发布</span>}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>{wf.description || '无描述'}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                      v{wf.version} · {wf.node_count} 节点 · {wf.edge_count} 边 · 更新于 {formatDate(wf.updated_at)}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    <button className="btn-secondary-small" onClick={() => viewDetail(wf)}>查看</button>
                    <button className="btn-secondary-small" onClick={() => validateWorkflow(wf.id)}>校验</button>
                    {canManage && (
                      <>
                        {!wf.is_published && <button className="btn-secondary-small" onClick={() => publishWorkflow(wf.id)}>发布</button>}
                        <button className="btn-secondary-small" onClick={() => cloneWorkflow(wf.id)}>克隆</button>
                        {!wf.is_default && <button className="btn-secondary-small kb-danger-btn" onClick={() => deleteWorkflow(wf.id)}>删除</button>}
                      </>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="sessions-container" style={{ marginTop: 16 }}>
          <button className="btn-secondary-small" onClick={() => setSelectedWf(null)} style={{ marginBottom: 12 }}>← 返回列表</button>
          <h3 className="detail-title">{selectedWf.name} 详情</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{selectedWf.description}</p>
          <div style={{ marginTop: 12 }}>
            <h4 style={{ fontSize: 14, marginBottom: 8 }}>工作流定义（JSON）</h4>
            <pre className="code-block">
              {JSON.stringify(wfDetail, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}

// ============================================================
// Main component
// ============================================================

