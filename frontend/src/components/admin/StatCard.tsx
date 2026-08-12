// 共享统计卡片组件 —— 从 AdminDashboard.tsx 抽离，供所有 Tab 复用。
export function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ color: color || 'var(--brand-teal-dark)' }}>{value}</div>
    </div>
  )
}
