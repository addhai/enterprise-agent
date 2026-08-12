import { useCallback, useEffect, useState } from 'react'
import { fetchJson, postJson, putJson } from './api'
import { StatCard } from './StatCard'
import type { ConfigField, ConfigCategory, FeatureFlag } from './types'

export function ConfigTab({ token, hasPermission }: { token: string; hasPermission: (p: string) => boolean }) {
  const [categories, setCategories] = useState<ConfigCategory[]>([])
  const [flags, setFlags] = useState<FeatureFlag[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeCategory, setActiveCategory] = useState<string>('')
  const [editingField, setEditingField] = useState<string | null>(null)
  const [editValue, setEditValue] = useState<string>('')
  const [saving, setSaving] = useState(false)
  const [tabMode, setTabMode] = useState<'categories' | 'flags'>('categories')
  const canManage = hasPermission('config:manage')

  const load = useCallback(() => {
    Promise.all([
      fetchJson('/admin/config', token),
      fetchJson('/admin/config/features', token),
    ])
      .then(([catData, flagData]) => {
        setCategories(catData.categories || [])
        setFlags(flagData.flags || [])
        if (!activeCategory && catData.categories?.length > 0) {
          setActiveCategory(catData.categories[0].key)
        }
        setError('')
      })
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token, activeCategory])

  useEffect(() => { load() }, [load])

  const startEdit = (field: ConfigField) => {
    if (!canManage || field.is_sensitive) return
    setEditingField(field.name)
    setEditValue(String(field.value))
  }

  const saveEdit = async () => {
    if (!editingField) return
    setSaving(true)
    try {
      // 根据字段类型转换值
      const field = categories
        .flatMap(c => c.fields)
        .find(f => f.name === editingField)
      let typedValue: unknown = editValue
      if (field?.type === 'bool') {
        typedValue = ['true', '1', 'yes', 'on'].includes(editValue.toLowerCase())
      } else if (field?.type === 'int') {
        typedValue = parseInt(editValue, 10)
      } else if (field?.type === 'float') {
        typedValue = parseFloat(editValue)
      }
      await putJson('/admin/config', token, { updates: { [editingField]: typedValue } })
      setEditingField(null)
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const toggleFlag = async (flag: FeatureFlag) => {
    if (!canManage) return
    if (!confirm(`确认${flag.enabled ? '关闭' : '开启'} ${flag.name}？`)) return
    try {
      await putJson(`/admin/config/features/${flag.name}`, token, { enabled: !flag.enabled })
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '切换失败')
    }
  }

  const resetCategory = async () => {
    if (!canManage || !activeCategory) return
    if (!confirm(`确认重置 ${activeCategory} 分类的所有配置到默认值？`)) return
    try {
      await postJson(`/admin/config/reset/${activeCategory}`, token, {})
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '重置失败')
    }
  }

  const resetAll = async () => {
    if (!canManage) return
    if (!confirm('确认重置所有配置到默认值？此操作不可撤销。')) return
    try {
      await postJson('/admin/config/reset', token, {})
      await load()
    } catch (err) {
      alert(err instanceof Error ? err.message : '重置失败')
    }
  }

  if (loading) return <div className="admin-loading">加载配置...</div>
  if (error) return <div className="admin-error">{error}</div>

  const currentCategory = categories.find(c => c.key === activeCategory)

  return (
    <div>
      <div className="metrics-grid">
        <StatCard label="配置分类" value={String(categories.length)} />
        <StatCard label="Feature Flag 总数" value={String(flags.length)} />
        <StatCard label="已启用 Flag" value={String(flags.filter(f => f.enabled).length)} color="#10b981" />
        <StatCard label="已修改字段" value={String(categories.flatMap(c => c.fields).filter(f => !f.is_sensitive && !f.is_default).length)} color="#f59e0b" />
      </div>

      <div className="health-controls">
        <div className="tab-switcher">
          <button
            className={`tab-btn ${tabMode === 'categories' ? 'active' : ''}`}
            onClick={() => setTabMode('categories')}
          >分类配置</button>
          <button
            className={`tab-btn ${tabMode === 'flags' ? 'active' : ''}`}
            onClick={() => setTabMode('flags')}
          >Feature Flag</button>
        </div>
        {canManage && tabMode === 'categories' && (
          <>
            <button className="btn-secondary-small" onClick={resetCategory} disabled={!activeCategory}>
              ↺ 重置当前分类
            </button>
            <button className="btn-secondary-small" onClick={resetAll}>
              ↺ 重置全部
            </button>
          </>
        )}
        <button className="btn-secondary-small" onClick={load}>🔄 刷新</button>
      </div>

      {tabMode === 'categories' && (
        <div className="config-layout" style={{ display: 'flex', gap: 16, marginTop: 16 }}>
          {/* 左侧分类列表 */}
          <div className="config-sidebar" style={{ width: 200, flexShrink: 0 }}>
            <h3 className="detail-title">分类</h3>
            <div className="sessions-list" style={{ maxHeight: 500, overflowY: 'auto' }}>
              {categories.map(cat => (
                <button
                  key={cat.key}
                  className={`session-item ${activeCategory === cat.key ? 'active' : ''}`}
                  onClick={() => setActiveCategory(cat.key)}
                  style={{ display: 'block', width: '100%', textAlign: 'left', padding: '8px 12px' }}
                >
                  <div style={{ fontWeight: 600 }}>{cat.label}</div>
                  <div style={{ fontSize: 11, color: '#888' }}>{cat.fields.length} 字段</div>
                </button>
              ))}
            </div>
          </div>

          {/* 右侧字段列表 */}
          <div className="config-content" style={{ flex: 1, minWidth: 0 }}>
            {currentCategory && (
              <>
                <h3 className="detail-title">{currentCategory.label}</h3>
                <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 12 }}>{currentCategory.description}</p>
                <div className="sessions-container">
                  <table className="config-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                      <tr style={{ background: 'var(--bg-deep)', textAlign: 'left' }}>
                        <th style={{ padding: 8, borderBottom: '1px solid var(--border-subtle)' }}>字段名</th>
                        <th style={{ padding: 8, borderBottom: '1px solid var(--border-subtle)' }}>类型</th>
                        <th style={{ padding: 8, borderBottom: '1px solid var(--border-subtle)' }}>当前值</th>
                        <th style={{ padding: 8, borderBottom: '1px solid var(--border-subtle)' }}>默认值</th>
                        <th style={{ padding: 8, borderBottom: '1px solid var(--border-subtle)' }}>状态</th>
                        <th style={{ padding: 8, borderBottom: '1px solid var(--border-subtle)' }}>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {currentCategory.fields.map(field => (
                        <tr key={field.name} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                          <td style={{ padding: 8, fontFamily: 'monospace', fontSize: 13, color: 'var(--text-primary)' }}>{field.name}</td>
                          <td style={{ padding: 8, fontSize: 12, color: 'var(--text-secondary)' }}>{field.type}</td>
                          <td style={{ padding: 8, fontFamily: 'monospace', fontSize: 13, color: 'var(--text-primary)' }}>
                            {field.is_sensitive ? (
                              <span style={{ color: 'var(--text-secondary)' }}>{field.configured ? '已配置 ••••' : '未配置'}</span>
                            ) : editingField === field.name ? (
                              <input
                                type="text"
                                value={editValue}
                                onChange={e => setEditValue(e.target.value)}
                                style={{ width: '100%', padding: '2px 6px', fontFamily: 'monospace' }}
                                autoFocus
                              />
                            ) : (
                              <span style={{ color: field.is_default ? 'var(--text-secondary)' : 'var(--brand-teal)', fontWeight: field.is_default ? 400 : 600 }}>
                                {String(field.value)}
                              </span>
                            )}
                          </td>
                          <td style={{ padding: 8, fontFamily: 'monospace', fontSize: 12, color: 'var(--text-muted)' }}>
                            {field.is_sensitive ? '-' : String(field.default)}
                          </td>
                          <td style={{ padding: 8 }}>
                            {field.is_sensitive ? (
                              <span className="role-badge sensitive">敏感</span>
                            ) : field.is_default ? (
                              <span className="role-badge default">默认</span>
                            ) : (
                              <span className="role-badge modified">已修改</span>
                            )}
                          </td>
                          <td style={{ padding: 8 }}>
                            {canManage && !field.is_sensitive && (
                              editingField === field.name ? (
                                <>
                                  <button className="btn-secondary-small" onClick={saveEdit} disabled={saving} style={{ marginRight: 4 }}>
                                    {saving ? '保存中' : '✓'}
                                  </button>
                                  <button className="btn-secondary-small" onClick={() => setEditingField(null)}>✗</button>
                                </>
                              ) : (
                                <button className="btn-secondary-small" onClick={() => startEdit(field)}>编辑</button>
                              )
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {tabMode === 'flags' && (
        <div className="sessions-container" style={{ marginTop: 16 }}>
          <h3 className="detail-title">Feature Flag 开关</h3>
          <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
            {flags.map(flag => (
              <div key={flag.name} className="metric-card" style={{ padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                  <div>
                    <div style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 600 }}>{flag.name}</div>
                    <div style={{ fontSize: 11, color: '#888' }}>{flag.category_label}</div>
                  </div>
                  <span className={`role-badge ${flag.enabled ? 'enabled' : 'disabled'}`}>
                    {flag.enabled ? '已启用' : '已禁用'}
                  </span>
                </div>
                <button
                  className="btn-secondary-small"
                  onClick={() => toggleFlag(flag)}
                  disabled={!canManage}
                  style={{ width: '100%', marginTop: 8 }}
                >
                  {canManage ? (flag.enabled ? '点击关闭' : '点击开启') : '只读'}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ============================================================
// Evaluation Tab — 评估管理（P5）
// ============================================================

