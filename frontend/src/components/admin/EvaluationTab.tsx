import { useCallback, useEffect, useState } from 'react'
import { fetchApi, fetchJson, postJson, formatDate } from './api'
import { StatCard } from './StatCard'
import type { EvalDataset, EvalRun } from './types'

export function EvaluationTab({ token, hasPermission }: { token: string; hasPermission: (p: string) => boolean }) {
  const [datasets, setDatasets] = useState<EvalDataset[]>([])
  const [runs, setRuns] = useState<EvalRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeView, setActiveView] = useState<'datasets' | 'runs'>('datasets')
  const [selectedDataset, setSelectedDataset] = useState<EvalDataset | null>(null)
  const [selectedRun, setSelectedRun] = useState<EvalRun | null>(null)
  const canManage = hasPermission('evaluation:manage')

  const load = useCallback(() => {
    Promise.all([
      fetchJson('/admin/evaluation/datasets', token).catch(() => ({ datasets: [] })),
      fetchJson('/admin/evaluation/runs', token).catch(() => ({ runs: [] })),
    ])
      .then(([dsData, runData]) => {
        setDatasets(dsData.datasets || [])
        setRuns(runData.runs || [])
        setError('')
      })
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => { load() }, [load])

  const triggerRun = async (datasetId: string) => {
    if (!canManage) return
    if (!confirm('确认触发评估运行？')) return
    try {
      await postJson('/admin/evaluation/runs', token, { dataset_id: datasetId })
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '触发失败')
    }
  }

  const deleteDataset = async (id: string) => {
    if (!canManage) return
    if (!confirm('确认删除该数据集？')) return
    try {
      await fetchApi(`/admin/evaluation/datasets/${id}`, token, { method: 'DELETE' })
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败')
    }
  }

  if (loading) return <div className="admin-loading">加载评估数据...</div>
  if (error) return <div className="admin-error">{error}</div>

  return (
    <div>
      <div className="metrics-grid">
        <StatCard label="数据集总数" value={String(datasets.length)} />
        <StatCard label="评估运行总数" value={String(runs.length)} />
        <StatCard label="运行中" value={String(runs.filter(r => r.status === 'running').length)} color="#f59e0b" />
        <StatCard label="已完成" value={String(runs.filter(r => r.status === 'completed').length)} color="#10b981" />
      </div>

      <div className="health-controls">
        <div className="tab-switcher">
          <button className={`tab-btn ${activeView === 'datasets' ? 'active' : ''}`} onClick={() => { setActiveView('datasets'); setSelectedDataset(null); setSelectedRun(null) }}>数据集</button>
          <button className={`tab-btn ${activeView === 'runs' ? 'active' : ''}`} onClick={() => { setActiveView('runs'); setSelectedDataset(null); setSelectedRun(null) }}>运行历史</button>
        </div>
        <button className="btn-secondary-small" onClick={load}>🔄 刷新</button>
      </div>

      {activeView === 'datasets' && !selectedDataset && (
        <div className="sessions-container" style={{ marginTop: 16 }}>
          <h3 className="detail-title">评估数据集</h3>
          <div className="sessions-list">
            {datasets.length === 0 ? (
              <div className="sessions-placeholder"><p>暂无数据集</p></div>
            ) : datasets.map(ds => (
              <div key={ds.id} className="session-item" style={{ display: 'block', padding: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ fontWeight: 600 }}>{ds.name}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{ds.description || '无描述'}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
                      {Array.isArray(ds.samples) ? ds.samples.length : 0} 个样本 · 创建于 {formatDate(ds.created_at)}
                    </div>
                  </div>
                  <div>
                    {canManage && (
                      <button className="btn-primary" style={{ marginRight: 8, padding: '4px 12px' }} onClick={() => triggerRun(ds.id)}>
                        ▶ 运行
                      </button>
                    )}
                    <button className="btn-secondary-small" onClick={() => setSelectedDataset(ds)}>查看</button>
                    {canManage && (
                      <button className="btn-secondary-small kb-danger-btn" onClick={() => deleteDataset(ds.id)}>删除</button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeView === 'datasets' && selectedDataset && (
        <div className="sessions-container" style={{ marginTop: 16 }}>
          <button className="btn-secondary-small" onClick={() => setSelectedDataset(null)} style={{ marginBottom: 12 }}>← 返回列表</button>
          <h3 className="detail-title">{selectedDataset.name}</h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: 13 }}>{selectedDataset.description}</p>
          <div style={{ marginTop: 12 }}>
            <h4 style={{ fontSize: 14, marginBottom: 8 }}>样本列表</h4>
            <pre className="code-block">
              {JSON.stringify(selectedDataset.samples, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {activeView === 'runs' && !selectedRun && (
        <div className="sessions-container" style={{ marginTop: 16 }}>
          <h3 className="detail-title">评估运行历史</h3>
          <div className="sessions-list">
            {runs.length === 0 ? (
              <div className="sessions-placeholder"><p>暂无运行记录</p></div>
            ) : runs.map(run => (
              <div key={run.id} className="session-item" style={{ display: 'block', padding: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ fontWeight: 600 }}>{run.dataset_name || run.dataset_id}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                      开始: {formatDate(run.started_at)} · 耗时: {run.finished_at ? `${((run.finished_at - run.started_at)).toFixed(1)}s` : '进行中'}
                    </div>
                  </div>
                  <div>
                    <span className={`role-badge ${run.status === 'completed' ? 'published' : run.status === 'running' ? 'running' : 'disabled'}`}>
                      {run.status}
                    </span>
                    <button className="btn-secondary-small" style={{ marginLeft: 8 }} onClick={() => setSelectedRun(run)}>查看报告</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeView === 'runs' && selectedRun && (
        <div className="sessions-container" style={{ marginTop: 16 }}>
          <button className="btn-secondary-small" onClick={() => setSelectedRun(null)} style={{ marginBottom: 12 }}>← 返回列表</button>
          <h3 className="detail-title">评估报告</h3>
          <div className="metrics-grid">
            {Object.entries(selectedRun.summary || {}).map(([k, v]) => (
              <StatCard key={k} label={k} value={typeof v === 'number' ? v.toFixed(3) : String(v)} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ============================================================
// Workflow Tab — 工作流管理（P3-P4）
// ============================================================

