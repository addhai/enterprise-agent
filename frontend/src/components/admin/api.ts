// API 与格式化共享 helper —— 从 AdminDashboard.tsx 抽离到 admin/api.ts。
// 所有 Tab 组件统一从这里 import，避免重复定义。

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function checkResponse(response: Response) {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new ApiError(response.status, data.detail || data.message || `请求失败 (${response.status})`)
  }
  return response.json()
}

export async function fetchApi(path: string, token: string, options: RequestInit = {}) {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
  if (options.body && typeof options.body === 'string') {
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: { ...headers, ...(options.headers as Record<string, string> || {}) },
  })
  return checkResponse(response)
}

export async function fetchJson(path: string, token: string) {
  return fetchApi(path, token)
}

export async function postJson(path: string, token: string, body: unknown) {
  return fetchApi(path, token, { method: 'POST', body: JSON.stringify(body) })
}

export async function putJson(path: string, token: string, body: unknown) {
  return fetchApi(path, token, { method: 'PUT', body: JSON.stringify(body) })
}

export function formatDate(ts: number | string | undefined) {
  if (ts === undefined || ts === null || ts === '') return '-'
  const d = typeof ts === 'string' ? new Date(ts) : new Date(ts * 1000)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleString('zh-CN')
}

export function formatDuration(seconds?: number) {
  if (seconds === undefined || seconds === null) return '-'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}分${s < 10 ? '0' : ''}${s}秒`
}

export function formatDateShort(ts: number | string | undefined) {
  if (ts === undefined || ts === null || ts === '') return '-'
  const d = typeof ts === 'string' ? new Date(ts) : new Date(ts * 1000)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleDateString('zh-CN')
}
