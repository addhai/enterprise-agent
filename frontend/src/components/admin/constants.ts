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
  { value: 'inactive', label: ' inactive' },
  { value: 'suspended', label: '已停用' },
]

export const USER_STATUSES = ['active', 'inactive', 'suspended']

