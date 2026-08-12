import { useCallback, useEffect, useState } from 'react'
import { fetchApi, fetchJson, postJson, formatDate } from './api'
import type { Props, KBSetItem, KBDocItem, KBHitResult } from './types'

export function KnowledgeTab({ token, user, hasPermission }: { token: string; user: Props['user']; hasPermission: (p: string) => boolean }) {
  const [kbs, setKbs] = useState<KBSetItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ name: '', description: '', kb_type: 'document' })
  const [creating, setCreating] = useState(false)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [docs, setDocs] = useState<KBDocItem[]>([])
  const [docsLoading, setDocsLoading] = useState(false)
  const [docsError, setDocsError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [hitQuery, setHitQuery] = useState('')
  const [hitResults, setHitResults] = useState<KBHitResult[]>([])
  const [hitLoading, setHitLoading] = useState(false)

  const [docSourceType, setDocSourceType] = useState<'document' | 'url' | 'text'>('document')
  const [docUrl, setDocUrl] = useState('')
  const [docText, setDocText] = useState('')
  const [docTitle, setDocTitle] = useState('')
  const [addingDoc, setAddingDoc] = useState(false)

  const isAdmin = user?.role === 'admin'
  const canEdit = hasPermission('agent:workspace')

  const totalDocs = kbs.reduce((s, k) => s + (k.document_count || 0), 0)
  const totalChunks = kbs.reduce((s, k) => s + (k.total_chunks || 0), 0)
  const avgThreshold = kbs.length ? kbs.reduce((s, k) => s + (Number(k.similarity_threshold) || 0), 0) / kbs.length : 0

  const fetchList = useCallback(() => {
    setLoading(true)
    setError('')
    fetchJson('/admin/knowledge', token)
      .then((d: any) => setKbs((d.knowledge_bases || []) as KBSetItem[]))
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => { fetchList() }, [fetchList])

  const fetchDocs = useCallback((kbId: string) => {
    setDocsLoading(true)
    setDocsError('')
    fetchJson(`/admin/knowledge/${kbId}/documents`, token)
      .then((d: any) => setDocs((d.documents || []) as KBDocItem[]))
      .catch(err => setDocsError(err instanceof Error ? err.message : '加载文档失败'))
      .finally(() => setDocsLoading(false))
  }, [token])

  const selectKb = (kb: KBSetItem) => {
    setSelectedId(kb.id)
    setHitResults([])
    fetchDocs(kb.id)
  }

  const createKb = async () => {
    if (!form.name.trim()) { alert('请输入知识库名称'); return }
    setCreating(true)
    try {
      await postJson('/admin/knowledge', token, {
        name: form.name.trim(),
        description: form.description.trim(),
        kb_type: form.kb_type,
      })
      setShowCreate(false)
      setForm({ name: '', description: '', kb_type: 'document' })
      fetchList()
    } catch (err) {
      alert(err instanceof Error ? err.message : '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const deleteKb = async (kb: KBSetItem) => {
    if (!confirm(`确认删除知识库「${kb.name}」？其下所有文档也会被删除，不可恢复。`)) return
    try {
      await fetchApi(`/admin/knowledge/${kb.id}`, token, { method: 'DELETE' })
      if (selectedId === kb.id) setSelectedId(null)
      fetchList()
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败')
    }
  }

  const reindexKb = async (kb: KBSetItem) => {
    try {
      await postJson(`/admin/knowledge/${kb.id}/reindex`, token, {})
      alert('已触发重建索引')
      if (selectedId === kb.id) fetchDocs(kb.id)
    } catch (err) {
      alert(err instanceof Error ? err.message : '操作失败')
    }
  }

  const uploadDoc = async (file?: File) => {
    if (!selectedId || !file) return
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      await fetchApi(`/admin/knowledge/${selectedId}/documents/upload`, token, { method: 'POST', body: fd })
      fetchDocs(selectedId)
    } catch (err) {
      alert(err instanceof Error ? err.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const addDocBySource = async () => {
    if (!selectedId) return
    if (docSourceType === 'url') {
      if (!/^https?:\/\//i.test(docUrl.trim())) { alert('请输入以 http:// 或 https:// 开头的网页 URL'); return }
    } else if (docSourceType === 'text') {
      if (!docText.trim()) { alert('请输入文本内容'); return }
    }
    setAddingDoc(true)
    try {
      const payload: any = { source_type: docSourceType, title: docTitle.trim() }
      if (docSourceType === 'url') payload.file_path = docUrl.trim()
      if (docSourceType === 'text') payload.content = docText.trim()
      await postJson(`/admin/knowledge/${selectedId}/documents`, token, payload)
      setDocUrl(''); setDocText(''); setDocTitle('')
      fetchDocs(selectedId)
    } catch (err) {
      alert(err instanceof Error ? err.message : '添加失败')
    } finally {
      setAddingDoc(false)
    }
  }

  const deleteDoc = async (doc: KBDocItem) => {
    if (!selectedId) return
    if (!confirm(`确认删除文档「${doc.title}」？`)) return
    try {
      await fetchApi(`/admin/knowledge/${selectedId}/documents/${doc.id}`, token, { method: 'DELETE' })
      fetchDocs(selectedId)
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败')
    }
  }

  const runHitTest = async () => {
    if (!selectedId || !hitQuery.trim()) return
    setHitLoading(true)
    try {
      const d = await postJson(`/admin/knowledge/${selectedId}/hit_test`, token, { query: hitQuery.trim(), top_k: 5 }) as any
      setHitResults(d.hits || [])
    } catch (err) {
      alert(err instanceof Error ? err.message : '命中测试失败')
    } finally {
      setHitLoading(false)
    }
  }

  const selectedKb = kbs.find(k => k.id === selectedId) || null

  return (
    <div>
      <div className="filter-bar">
        <button className="btn-primary-small" onClick={() => setShowCreate(v => !v)} disabled={!canEdit}>新建知识库</button>
        <button className="refresh-btn" onClick={fetchList} disabled={loading}>刷新</button>
      </div>

      <div className="metrics-grid" style={{ marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-label">知识库总数</div>
          <div className="stat-value">{kbs.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">文档总数</div>
          <div className="stat-value">{totalDocs}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">切片总数</div>
          <div className="stat-value">{totalChunks}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">平均相似度阈值</div>
          <div className="stat-value">{avgThreshold.toFixed(2)}</div>
        </div>
      </div>

      {showCreate && (
        <div className="kb-form">
          <div style={{ marginBottom: 8 }}>
            <label style={{ display: 'block', marginBottom: 4 }}>名称</label>
            <input className="filter-input" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="如：产品手册知识库" />
          </div>
          <div style={{ marginBottom: 8 }}>
            <label style={{ display: 'block', marginBottom: 4 }}>描述</label>
            <input className="filter-input" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} placeholder="可选" />
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: 'block', marginBottom: 4 }}>类型</label>
            <select className="filter-input" value={form.kb_type} onChange={e => setForm(f => ({ ...f, kb_type: e.target.value }))}>
              <option value="document">文档</option>
              <option value="data">数据/表格</option>
              <option value="image">图片</option>
              <option value="audio_video">音视频</option>
            </select>
          </div>
          <button className="btn-primary-small" onClick={createKb} disabled={creating}>{creating ? '创建中...' : '创建'}</button>
          <button className="btn-secondary-small" style={{ marginLeft: 8 }} onClick={() => setShowCreate(false)}>取消</button>
        </div>
      )}

      {loading && <div className="admin-loading">加载知识库...</div>}
      {error && <div className="admin-error">{error}</div>}
      {!loading && !error && kbs.length === 0 && <div className="sessions-placeholder"><p>暂无知识库，点击「新建知识库」开始</p></div>}

      {!loading && !error && kbs.length > 0 && (
        <div className="kb-grid">
          {kbs.map(kb => (
            <div key={kb.id} onClick={() => selectKb(kb)}
              className={`kb-card${selectedId === kb.id ? ' selected' : ''}`}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="kb-card-name">{kb.name}</span>
                <span className={`badge status-${kb.kb_type}`}>{kb.kb_type}</span>
              </div>
              {kb.description && <div className="kb-card-desc">{kb.description}</div>}
              <div className="kb-card-meta">
                <span>文档 {kb.document_count}</span>
                <span>切片 {kb.total_chunks}</span>
                <span>阈值 {kb.similarity_threshold}</span>
              </div>
              <div className="kb-card-actions" onClick={e => e.stopPropagation()}>
                <button className="btn-secondary-small" onClick={() => reindexKb(kb)}>重建索引</button>
                {isAdmin && (
                  <button className="btn-secondary-small kb-danger-btn" onClick={() => deleteKb(kb)}>删除</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedKb && (
        <div style={{ marginTop: 20 }}>
          <h3 className="detail-title">文档列表 · {selectedKb.name}</h3>
          <div style={{ marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div className="filter-bar" style={{ marginBottom: 0 }}>
              <button className={`kb-src-btn${docSourceType === 'document' ? ' active' : ''}`} onClick={() => setDocSourceType('document')} disabled={addingDoc}>上传文档</button>
              <button className={`kb-src-btn${docSourceType === 'url' ? ' active' : ''}`} onClick={() => setDocSourceType('url')} disabled={addingDoc}>网页URL</button>
              <button className={`kb-src-btn${docSourceType === 'text' ? ' active' : ''}`} onClick={() => setDocSourceType('text')} disabled={addingDoc}>纯文本</button>
            </div>

            {docSourceType === 'document' && (
              <label className="btn-primary-small" style={{ display: 'inline-block', cursor: 'pointer', width: 'fit-content' }}>
                选择文件上传
                <input type="file" style={{ display: 'none' }} onChange={e => uploadDoc(e.target.files?.[0])} disabled={uploading} accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.ppt,.pptx" />
              </label>
            )}

            {docSourceType === 'url' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <input className="filter-input" value={docUrl} onChange={e => setDocUrl(e.target.value)} placeholder="https://example.com/docs/article" disabled={addingDoc} />
                <div style={{ display: 'flex', gap: 8 }}>
                  <input className="filter-input" style={{ flex: 1 }} value={docTitle} onChange={e => setDocTitle(e.target.value)} placeholder="标题（可选，默认取 URL）" disabled={addingDoc} />
                  <button className="btn-primary-small" onClick={addDocBySource} disabled={addingDoc || !docUrl.trim()}>{addingDoc ? '抓取中...' : '添加'}</button>
                </div>
              </div>
            )}

            {docSourceType === 'text' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <textarea className="filter-input" value={docText} onChange={e => setDocText(e.target.value)} placeholder="粘贴或输入纯文本内容..." rows={5} disabled={addingDoc} style={{ resize: 'vertical', fontFamily: 'inherit' }} />
                <div style={{ display: 'flex', gap: 8 }}>
                  <input className="filter-input" style={{ flex: 1 }} value={docTitle} onChange={e => setDocTitle(e.target.value)} placeholder="标题（可选）" disabled={addingDoc} />
                  <button className="btn-primary-small" onClick={addDocBySource} disabled={addingDoc || !docText.trim()}>{addingDoc ? '入库中...' : '添加'}</button>
                </div>
              </div>
            )}
            {uploading && <span style={{ marginLeft: 0 }}>上传中...</span>}
          </div>

          {docsLoading && <div className="admin-loading">加载文档...</div>}
          {docsError && <div className="admin-error">{docsError}</div>}
          {!docsLoading && !docsError && docs.length === 0 && <div className="sessions-placeholder"><p>该知识库暂无文档，点「上传文档」添加</p></div>}
          {!docsLoading && !docsError && docs.length > 0 && (
            <div className="sessions-table-wrap">
              <table className="sessions-table">
                <thead>
                  <tr><th>标题</th><th>类型</th><th>状态</th><th>切片</th><th>上传时间</th><th>操作</th></tr>
                </thead>
                <tbody>
                  {docs.map(d => (
                    <tr key={d.id}>
                      <td>{d.title}</td>
                      <td><span className={`badge status-${d.source_type}`}>{d.source_type}</span></td>
                      <td><span className={`badge status-${d.status}`}>{d.status}</span></td>
                      <td>{d.chunk_count}</td>
                      <td>{formatDate(d.created_at)}</td>
                      <td>
                        {isAdmin && (
                          <button className="btn-secondary-small kb-danger-btn" onClick={() => deleteDoc(d)}>删除</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div style={{ marginTop: 20 }}>
            <h3 className="detail-title">命中测试（验证检索效果）</h3>
            <div className="filter-bar" style={{ marginBottom: 8 }}>
              <input className="filter-input" style={{ flex: 1 }} value={hitQuery} onChange={e => setHitQuery(e.target.value)} placeholder="输入一个问题，测试知识库能否召回相关内容" />
              <button className="btn-primary-small" onClick={runHitTest} disabled={hitLoading}>{hitLoading ? '测试中...' : '测试'}</button>
            </div>
            {hitResults.length > 0 && (
              (() => {
                const threshold = selectedKb?.similarity_threshold ?? 0
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div className="kb-note">
                      共召回 {hitResults.length} 段 · 当前库阈值 {threshold.toFixed(3)}（低于阈值的片段在真实对话中不会被采用）
                    </div>
                    {hitResults.map((h, i) => {
                      const passed = h.score >= threshold
                      const title = (h.metadata && (h.metadata.title || h.metadata.source)) || h.source || '未知文档'
                      return (
                        <details key={i} className="kb-hit-card" open={i === 0}>
                          <summary className="kb-hit-summary">
                            <span className={`kb-hit-badge ${passed ? 'pass' : 'fail'}`}>{passed ? '采用' : '低于阈值'}</span>
                            <span className="kb-hit-title">{title}</span>
                            <span className="kb-hit-score">匹配度 {h.score.toFixed(3)}</span>
                          </summary>
                          <div className="kb-hit-body">
                            <div className="kb-hit-content">{h.content}</div>
                            {h.source && <div className="kb-hit-source">来源：{h.source}</div>}
                          </div>
                        </details>
                      )
                    })}
                  </div>
                )
              })()
            )}
          </div>
        </div>
      )}
    </div>
  )
}

