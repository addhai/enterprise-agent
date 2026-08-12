import { useEffect, useState } from 'react'
import { fetchJson, formatDate } from './api'
import { StatCard } from './StatCard'
import type { SatisfactionRecord } from './types'

export function SatisfactionTab({ token }: { token: string }) {
  const [records, setRecords] = useState<SatisfactionRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    fetchJson('/satisfaction?limit=100', token)
      .then((r: any) => setRecords((r.records || []) as SatisfactionRecord[]))
      .catch(err => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [token])

  if (loading) return <div className="admin-loading">加载满意度...</div>
  if (error) return <div className="admin-error">{error}</div>

  const total = records.length
  const avg = total ? records.reduce((s, r) => s + r.score, 0) / total : 0
  const csat = total ? Math.round((records.filter(r => r.score >= 4).length / total) * 1000) / 10 : 0
  const detractors = records.filter(r => r.score <= 2).length
  const promoters = records.filter(r => r.score >= 4).length
  const nps = total ? Math.round(((promoters - detractors) / total) * 100) : 0
  const negativePending = records.filter(r => r.score <= 3).length
  const distribution: { star: number; label: string; count: number; positive: boolean }[] = [5, 4, 3, 2, 1].map(star => {
    const count = records.filter(r => r.score === star).length
    return { star, label: `${star} 星`, count, positive: star >= 4 }
  })
  const maxCount = Math.max(1, ...distribution.map(d => d.count))

  return (
    <div>
      <div className="metrics-grid">
        <StatCard label="CSAT（满意率）" value={`${csat}%`} color="#2dd4a0" />
        <StatCard label="NPS（净推荐值）" value={String(nps)} color="#60a5fa" />
        <StatCard label="平均评分" value={avg.toFixed(2)} color="#fbbf24" />
        <StatCard label="评价总数" value={String(total)} color="#aa3bff" />
        <StatCard label="差评待跟进" value={String(negativePending)} color={negativePending > 0 ? '#f87171' : undefined} />
      </div>

      <div className="sessions-container" style={{ marginTop: 16 }}>
        <h3 className="detail-title">评分分布</h3>
        <div className="sat-dist">
          {distribution.map(d => (
            <div key={d.star} className="sat-dist-row">
              <span className="sat-dist-label">{d.label}</span>
              <div className="sat-dist-track">
                <div
                  className={`sat-dist-bar ${d.positive ? 'pos' : 'neg'}`}
                  style={{ width: `${(d.count / maxCount) * 100}%` }}
                />
              </div>
              <span className="sat-dist-count">{d.count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="sessions-container" style={{ marginTop: 16 }}>
        <h3 className="detail-title">评价记录</h3>
        {records.length === 0 ? <p className="hint">暂无评价</p> : (
          <div className="comment-list">
            {records.map(r => (
              <div key={r.id} className="comment-item">
                <div className="comment-header">
                  <span className="comment-author">{r.score} 星 · {r.user_id}</span>
                  <span className="comment-time">{formatDate(r.created_at)}</span>
                </div>
                <p className="comment-content">{r.comment || r.tags.join(', ') || '无文字评价'}</p>
                {r.agent_id && <span className="hint">客服：{r.agent_id}</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ============================================================
// Notifications
// ============================================================

