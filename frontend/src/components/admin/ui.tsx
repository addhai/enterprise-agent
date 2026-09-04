// 共享 UI 组件 — 空状态、禁用按钮 tooltip、SVG 图标
// 替代裸文本空状态和 emoji 按钮，统一视觉风格

import type { ReactNode } from 'react'

// ============================================================
// SVG 图标 — 替代 emoji，跨平台渲染一致
// ============================================================

const iconProps = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

export const IconRefresh = ({ size = 14 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <path d="M21 2v6h-6" />
    <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
    <path d="M3 22v-6h6" />
    <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
  </svg>
)

export const IconHeart = ({ size = 14 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
  </svg>
)

export const IconWrench = ({ size = 14 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
  </svg>
)

export const IconCheck = ({ size = 14 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
    <polyline points="22 4 12 14.01 9 11.01" />
  </svg>
)

export const IconInbox = ({ size = 24 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
    <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
  </svg>
)

export const IconUsers = ({ size = 24 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
    <circle cx="9" cy="7" r="4" />
    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
  </svg>
)

export const IconMessage = ({ size = 24 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
)

export const IconActivity = ({ size = 24 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
  </svg>
)

export const IconClock = ({ size = 24 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
)

export const IconBook = ({ size = 24 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
  </svg>
)

export const IconServer = ({ size = 24 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
    <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
    <line x1="6" y1="6" x2="6.01" y2="6" />
    <line x1="6" y1="18" x2="6.01" y2="18" />
  </svg>
)

export const IconBell = ({ size = 24 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
  </svg>
)

export const IconTicket = ({ size = 24 }: { size?: number }) => (
  <svg {...iconProps} width={size} height={size}>
    <path d="M3 7v2a3 3 0 0 1 0 6v2c0 1.1.9 2 2 2h14a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2z" />
    <line x1="13" y1="5" x2="13" y2="19" strokeDasharray="2 3" />
  </svg>
)

// ============================================================
// EmptyState — 统一空状态组件，带图标、标题、描述、可选操作
// ============================================================

export function EmptyState({
  icon,
  title,
  desc,
  action,
}: {
  icon?: ReactNode
  title: string
  desc?: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-state-icon">{icon}</div>}
      <p className="empty-state-title">{title}</p>
      {desc && <p className="empty-state-desc">{desc}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  )
}

// ============================================================
// DisabledButton — 包装 disabled 按钮并显示禁用原因 tooltip
// ============================================================

export function DisabledButton({
  children,
  disabledReason,
  disabled,
  ...btnProps
}: {
  children: ReactNode
  disabledReason?: string
  disabled?: boolean
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  if (disabled && disabledReason) {
    return (
      <span className="btn-disabled-wrapper">
        <button {...btnProps} disabled={disabled}>
          {children}
        </button>
        <span className="btn-disabled-tooltip">{disabledReason}</span>
      </span>
    )
  }
  return (
    <button {...btnProps} disabled={disabled}>
      {children}
    </button>
  )
}
