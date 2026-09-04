// 共享常量 —— 从 AdminDashboard.tsx 抽离，供各 Tab 组件复用。

export const TICKET_STATUSES = [
  { value: '', label: '全部状态' },
  { value: 'open', label: '待处理' },
  { value: 'in_progress', label: '处理中' },
  { value: 'resolved', label: '已解决' },
  { value: 'closed', label: '已关闭' },
  { value: 'cancelled', label: '已取消' },
]

export const TICKET_PRIORITIES = [
  { value: '', label: '全部优先级' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'urgent', label: '紧急' },
]

export const CUSTOMER_STATUSES = [
  { value: '', label: '全部状态' },
  { value: 'active', label: '正常' },
  { value: 'inactive', label: '未活跃' },
  { value: 'suspended', label: '已停用' },
]

export const USER_STATUSES = ['active', 'inactive', 'suspended']

// ============================================================
// 枚举值中文映射 —— 表格/badge 显示时统一使用，避免中英文混用
// ============================================================

export const TICKET_STATUS_LABELS: Record<string, string> = {
  open: '待处理',
  in_progress: '处理中',
  resolved: '已解决',
  closed: '已关闭',
  cancelled: '已取消',
}

export const TICKET_PRIORITY_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
  urgent: '紧急',
}

export const CUSTOMER_STATUS_LABELS: Record<string, string> = {
  active: '正常',
  inactive: '未活跃',
  suspended: '已停用',
}

export const CUSTOMER_PLAN_LABELS: Record<string, string> = {
  free: '免费版',
  pro: '专业版',
  enterprise: '企业版',
  starter: '入门版',
  business: '商业版',
}

export const SESSION_MODE_LABELS: Record<string, string> = {
  ai_chat: 'AI 对话',
  human_chat: '人工客服',
  hybrid: '混合模式',
  bot: '机器人',
}

/** 将枚举值转为中文标签，未知值原样返回 */
export function statusLabel(status: string): string {
  return TICKET_STATUS_LABELS[status] || status
}

export function priorityLabel(priority: string): string {
  return TICKET_PRIORITY_LABELS[priority] || priority
}

export function customerStatusLabel(status: string): string {
  return CUSTOMER_STATUS_LABELS[status] || status
}

export function customerPlanLabel(plan: string): string {
  return CUSTOMER_PLAN_LABELS[plan] || plan
}

export function sessionModeLabel(mode: string): string {
  return SESSION_MODE_LABELS[mode] || mode
}

