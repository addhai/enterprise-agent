import { useState, useRef, useEffect, createContext, useContext } from 'react'
import './App.css'
import AdminDashboard from './components/AdminDashboard'

// ============================================================
// Types
// ============================================================

interface User {
  id: string
  username: string
  email?: string
  role?: string
}

// ============================================================
// 主题上下文 — 浅色/深色模式切换
// ============================================================

const ThemeContext = createContext<{
  theme: 'light' | 'dark'
  toggleTheme: () => void
}>({ theme: 'light', toggleTheme: () => {} })



// ============================================================
// Landing Page — Enterprise Agent 官网首页
// ============================================================

/* ---------- Navigation ---------- */

function Navigation({
  onAdminClick,
  user,
  onLoginClick,
  onLogout,
  onProfileClick,
}: {
  onAdminClick: () => void
  user: User | null
  onLoginClick: () => void
  onLogout: () => void
  onProfileClick: () => void
}) {
  const [activeSection, setActiveSection] = useState('hero')
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLLIElement>(null)
  // 从主题上下文获取当前主题和切换函数
  const { theme, toggleTheme } = useContext(ThemeContext)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const getInitials = (name: string) => {
    return name.charAt(0).toUpperCase()
  }

  return (
    <nav className="nav">
      <a href="#hero" className="nav-brand">
        <div className="nav-logo">EA</div>
        <span className="nav-title">Enterprise Agent</span>
      </a>
      <ul className="nav-links">
        <li><a href="#capabilities" className={activeSection === 'capabilities' ? 'active' : ''} onClick={() => setActiveSection('capabilities')}>能力</a></li>
        <li><a href="#architecture" className={activeSection === 'architecture' ? 'active' : ''} onClick={() => setActiveSection('architecture')}>架构</a></li>
        <li><a href="#details" className={activeSection === 'details' ? 'active' : ''} onClick={() => setActiveSection('details')}>技术细节</a></li>
        {/* 主题切换按钮：浅色模式显示月亮，深色模式显示太阳 */}
        <li>
          <button
            className="theme-toggle-btn"
            onClick={toggleTheme}
            title={theme === 'light' ? '切换到深色模式' : '切换到浅色模式'}
            aria-label="切换主题"
          >
            {theme === 'light' ? '🌙' : '☀️'}
          </button>
        </li>
        <li><button className="nav-admin-btn" onClick={(e) => { e.preventDefault(); onAdminClick() }}>管理后台</button></li>
        {user ? (
          <li className="nav-user-menu" ref={userMenuRef}>
            <button
              className="nav-user-btn"
              onClick={() => setUserMenuOpen(!userMenuOpen)}
            >
              <span className="nav-user-avatar">{getInitials(user.username)}</span>
              <span className="nav-user-name">{user.username}</span>
              <span className="nav-user-arrow">▼</span>
            </button>
            {userMenuOpen && (
              <div className="user-dropdown">
                <button className="user-dropdown-item" onClick={() => { setUserMenuOpen(false); onProfileClick() }}>
                  👤 个人中心
                </button>
                <button className="user-dropdown-item" onClick={() => { setUserMenuOpen(false); onAdminClick() }}>
                  💬 我的会话
                </button>
                <div className="user-dropdown-divider" />
                <button className="user-dropdown-item logout" onClick={() => { setUserMenuOpen(false); onLogout() }}>
                  🚪 退出登录
                </button>
              </div>
            )}
          </li>
        ) : (
          <li><button className="nav-login-btn" onClick={(e) => { e.preventDefault(); onLoginClick() }}>登录/注册</button></li>
        )}
        <li><a href="#chat" className="nav-cta">申请试用</a></li>
      </ul>
    </nav>
  )
}

/* ---------- Hero ---------- */

function HeroSection() {
  return (
    <section className="hero" id="hero">
      <div className="hero-particles">
        <span className="hero-particle" /><span className="hero-particle" />
        <span className="hero-particle" /><span className="hero-particle" />
        <span className="hero-particle" /><span className="hero-particle" />
        <span className="hero-particle" /><span className="hero-particle" />
      </div>
      <div className="container">
        <span className="hero-label">Enterprise Agent</span>

        <h1 className="hero-headline reveal">
          客服不该是<br />
          <em>千篇一律</em> 的机器人
        </h1>

        <p className="hero-sub reveal reveal-delay-1">
          基于 LangGraph + ReAct 的企业级智能客服系统。
          五层架构、三层记忆、多维评估——为高端 SaaS 团队打造的真正有分辨力的智能客服。
        </p>

        <div className="hero-tech reveal reveal-delay-2">
          <span>LangGraph</span>
          <span className="hero-tech-divider" />
          <span>ReAct Agent</span>
          <span className="hero-tech-divider" />
          <span>RAG</span>
          <span className="hero-tech-divider" />
          <span>阿里百炼 Qwen</span>
          <span className="hero-tech-divider" />
          <span>Chroma</span>
        </div>

        <div className="hero-actions reveal reveal-delay-3">
          <a href="#chat" className="btn-primary">
            申请试用
            <span className="arrow">→</span>
          </a>
          <button className="btn-link" onClick={() => {
            const el = document.getElementById('architecture')
            el?.scrollIntoView({ behavior: 'smooth' })
          }}>
            了解架构
            <span className="arrow">↓</span>
          </button>
        </div>
      </div>
    </section>
  )
}

/* ---------- Architecture Flow ---------- */

interface ArchLayer {
  number: string
  name: string
  desc: string
}

const ARCH_LAYERS: ArchLayer[] = [
  { number: 'LAYER 01', name: '接入层', desc: 'FastAPI 高性能服务，WebSocket 实时通信' },
  { number: 'LAYER 02', name: '安全层', desc: '4/5 层纵深防御，输入检测 + 输出校验' },
  { number: 'LAYER 03', name: '编排层', desc: 'LangGraph + DAG 工作流，5 种对话路径自动路由' },
  { number: 'LAYER 04', name: '能力层', desc: 'RAG 检索 · ReAct Agent · 三层记忆 · 多维评估' },
  { number: 'LAYER 05', name: '数据层', desc: 'Chroma 向量库 · Redis 缓存 · PostgreSQL 持久化' },
]

function ArchitectureSection() {
  return (
    <section id="architecture" className="architecture">
      <div className="container">
        <p className="section-label reveal">Architecture</p>

        <div className="arch-flow reveal">
          {ARCH_LAYERS.map((layer, i) => (
            <div key={layer.number}>
              <div className="arch-layer reveal" style={{ transitionDelay: `${i * 80}ms` }}>
                <span className="arch-layer-number">{layer.number}</span>
                <h3 className="arch-layer-name">{layer.name}</h3>
                <p className="arch-layer-desc">{layer.desc}</p>
              </div>
              {i < ARCH_LAYERS.length - 1 && (
                <span className="arch-arrow" aria-hidden="true">→</span>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ---------- Capabilities Grid ---------- */

interface CapItem {
  icon: string
  title: string
  desc: string
  tag: string
  planned?: boolean
}

const CAPABILITIES: CapItem[] = [
  { icon: '🔍', title: 'RAG 混合检索', desc: '文档加载 → 语义分块 → Embedding → 向量+BM25+RRF 融合检索，阿里百炼 text-embedding-v4 1024 维', tag: 'Active' },
  { icon: '🔄', title: 'ReAct Agent', desc: '思考-行动-观察循环，并行工具调用。search_kb / search_faq / escalate 三大工具链', tag: 'Active' },
  { icon: '🧠', title: '三层记忆管理', desc: '短期滑窗 + LLM 摘要 + 向量长期记忆 + 用户画像。三节点接入：entry → rag → reply', tag: 'Active' },
  { icon: '🛡️', title: '五层安全护栏', desc: '输入检测 → 编排护栏 → Agent 约束 → 输出校验 → 审计告警，纵深防御体系', tag: 'Active' },
  { icon: '📊', title: '多维评估监控', desc: 'RAG 离线指标 + LLM-as-Judge 对话质量 5 维评分 + 幻觉检测', tag: 'Active' },
  { icon: '🗺️', title: '5 种对话路径', desc: 'FAQ 直达 / 技术排查 / 人工转接 / FAQ 升级 RAG / RAG 转人工，自动路由编排', tag: 'Active' },
]

function CapabilitiesSection() {
  return (
    <section id="capabilities" className="capabilities">
      <div className="container">
        <p className="section-label reveal">Capabilities</p>
        <div className="cap-grid reveal">
          {CAPABILITIES.map((cap, i) => (
            <div className="cap-card" key={cap.title} style={{ transitionDelay: `${i * 0.06}s` }}>
              <span className="cap-icon" aria-hidden="true">{cap.icon}</span>
              <h3 className="cap-title">{cap.title}</h3>
              <p className="cap-desc">{cap.desc}</p>
              <span className={`cap-tag${cap.planned ? ' planned' : ''}`}>{cap.tag}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ---------- Metrics ---------- */

interface Metric {
  value: string
  label: string
}

const METRICS: Metric[] = [
  { value: '94.2%', label: 'RAG 检索 Recall' },
  { value: '230ms', label: 'P95 响应延迟' },
  { value: '<2.1%', label: '幻觉率' },
  { value: '5 层', label: '安全纵深防御' },
]

function MetricsSection() {
  return (
    <section className="metrics">
      <div className="container">
        <div className="metrics-row reveal">
          {METRICS.map((m, i) => (
            <div className="metric" key={m.label} style={{ transitionDelay: `${i * 0.1}s` }}>
              <div className="metric-value">{m.value}</div>
              <div className="metric-label">{m.label}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ---------- Tech Details Accordion ---------- */

interface DetailItem {
  question: string
  answer: React.ReactNode
}

const DETAILS: DetailItem[] = [
  {
    question: '检索精度如何保障？',
    answer: (
      <>
        采用 <code>向量检索 + BM25 + RRF 融合排序</code> 三路召回策略。Embedding 使用阿里百炼 text-embedding-v4（1024 维），文档经过语义分块确保上下文完整性。
      </>
    ),
  },
  {
    question: '记忆管理怎么做？',
    answer: (
      <>
        三层架构：<code>滑窗短期记忆</code>（Redis 优先，内存 fallback）、<code>LLM 摘要压缩</code>（自动提炼关键信息）、<code>向量长期记忆</code>（PG + Chroma 持久化 + 语义检索）。三节点接入：entry → rag → reply。
      </>
    ),
  },
  {
    question: '安全护栏有几层？',
    answer: (
      <>
        五层纵深防御：<code>输入检测</code> → <code>编排护栏</code> → <code>Agent 约束</code> → <code>输出校验</code> → <code>审计告警</code>。
      </>
    ),
  },
  {
    question: '支持哪些 LLM？',
    answer: (
      <>
        核心使用阿里百炼 Qwen-Plus / Qwen-Max，兼容 OpenAI API 格式。Embedding 使用阿里百炼 text-embedding-v4。
      </>
    ),
  },
  {
    question: '如何降级？',
    answer: (
      <>
        所有关键组件均设计了<code>自动降级</code>机制：Redis 不可用时降级为进程内存，PostgreSQL 不可用时降级为本地文件存储。
      </>
    ),
  },
]

function TechDetailsSection() {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(0)

  return (
    <section id="details" className="tech-details">
      <div className="container">
        <p className="section-label reveal">Technical Details</p>

        <div className="accordion reveal">
          {DETAILS.map((item, i) => (
            <div className="accordion-item" key={i}>
              <button
                className="accordion-trigger"
                aria-expanded={expandedIndex === i}
                onClick={() => setExpandedIndex(expandedIndex === i ? null : i)}
              >
                <span>{item.question}</span>
                <span className="icon" aria-hidden="true">+</span>
              </button>
              <div
                className="accordion-panel"
                style={{ maxHeight: expandedIndex === i ? '400px' : '0' }}
              >
                <div className="accordion-panel-inner">{item.answer}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ---------- CTA ---------- */

function CTASection() {
  return (
    <section id="chat" className="cta-section">
      <div className="container">
        <h2 className="cta-headline reveal">准备好升级你的客服了吗？</h2>
        <p className="cta-sub reveal reveal-delay-1">
          从 FAQ 机器人到真正的企业级智能客服，只差一次对话的距离。
        </p>
        <a href="#" className="btn-primary reveal reveal-delay-2" onClick={(e) => {
          e.preventDefault()
          const btn = document.querySelector('.floating-chat-btn') as HTMLElement
          btn?.click()
        }}>
          开始对话
          <span className="arrow">→</span>
        </a>
      </div>
    </section>
  )
}

/* ---------- Footer ---------- */

function Footer() {
  return (
    <footer className="footer container">
      <span>
        <a href="https://github.com/hai-zju/enterprise-agent" target="_blank" rel="noopener noreferrer">GitHub</a>
      </span>
    </footer>
  )
}

// ============================================================
// Login / Register Modal
// ============================================================

function AuthModal({
  isOpen,
  onClose,
  onLoginSuccess,
}: {
  isOpen: boolean
  onClose: () => void
  onLoginSuccess: (user: User, token: string) => void
}) {
  const [activeTab, setActiveTab] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const endpoint = activeTab === 'login' ? '/api/v1/auth/login' : '/api/v1/auth/register'
      const body = activeTab === 'login'
        ? { username, password }
        : { username, email, password }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || data.message || (activeTab === 'login' ? '登录失败' : '注册失败'))
      }

      const data = await response.json()
      const token = data.token || data.access_token || ''
      const returnedUser = data.user || {}
      const userData: User = {
        id: returnedUser.id || returnedUser.user_id || data.user_id || data.id || '',
        username: returnedUser.username || data.username || username,
        email: returnedUser.email || data.email || email,
        role: returnedUser.role || data.role || '',
      }

      localStorage.setItem('token', token)
      localStorage.setItem('user', JSON.stringify(userData))
      onLoginSuccess(userData, token)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  const handleAdminLogin = async () => {
    setError('')
    setLoading(true)
    try {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: 'admin', password: 'admin123' }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || data.message || '管理员登录失败')
      }
      const data = await response.json()
      const token = data.token || data.access_token || ''
      const returnedUser = data.user || {}
      const userData: User = {
        id: returnedUser.id || returnedUser.user_id || data.user_id || data.id || '',
        username: returnedUser.username || data.username || 'admin',
        email: returnedUser.email || data.email || '',
        role: returnedUser.role || data.role || '',
      }
      localStorage.setItem('token', token)
      localStorage.setItem('user', JSON.stringify(userData))
      onLoginSuccess(userData, token)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : '管理员登录失败')
    } finally {
      setLoading(false)
    }
  }

  const handleDemoLogin = () => {
    const demoUser: User = { id: 'demo-user', username: 'demo' }
    const demoToken = 'demo-token'
    localStorage.setItem('token', demoToken)
    localStorage.setItem('user', JSON.stringify(demoUser))
    onLoginSuccess(demoUser, demoToken)
    onClose()
  }

  return (
    <div className="auth-modal-overlay" onClick={onClose}>
      <div className="auth-modal" onClick={(e) => e.stopPropagation()}>
        <button className="auth-modal-close" onClick={onClose}>×</button>
        <div className="auth-modal-content">
          <h2 className="auth-title">{activeTab === 'login' ? '登录' : '注册'}</h2>

          <div className="auth-tabs">
            <button
              className={`auth-tab-btn ${activeTab === 'login' ? 'active' : ''}`}
              onClick={() => { setActiveTab('login'); setError('') }}
            >
              登录
            </button>
            <button
              className={`auth-tab-btn ${activeTab === 'register' ? 'active' : ''}`}
              onClick={() => { setActiveTab('register'); setError('') }}
            >
              注册
            </button>
          </div>

          {error && <div className="auth-error">{error}</div>}

          <form className="auth-form" onSubmit={handleSubmit}>
            <div className="form-group">
              <label>用户名</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入用户名"
                required
              />
            </div>

            {activeTab === 'register' && (
              <div className="form-group">
                <label>邮箱</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="请输入邮箱"
                  required
                />
              </div>
            )}

            <div className="form-group">
              <label>密码</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入密码"
                required
              />
            </div>

            {activeTab === 'register' && (
              <div className="form-group">
                <label>确认密码</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="请再次输入密码"
                  required
                />
              </div>
            )}

            <button type="submit" className="auth-submit-btn" disabled={loading}>
              {loading ? '处理中...' : (activeTab === 'login' ? '登录' : '注册')}
            </button>
          </form>

          <div className="auth-demo">
            <p>或使用演示账号 / 管理员账号体验：</p>
            <button className="admin-quick-login-btn" onClick={handleAdminLogin} disabled={loading}>
              管理员快速登录 (admin / admin123)
            </button>
            <button className="demo-login-btn" onClick={handleDemoLogin}>
              快速体验（演示账号）
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ============================================================
// Profile Modal — 个人中心
// ============================================================

function ProfileModal({
  isOpen,
  onClose,
  user,
  onLogout,
}: {
  isOpen: boolean
  onClose: () => void
  user: User | null
  onLogout: () => void
}) {
  const getInitials = (name: string) => name.charAt(0).toUpperCase()

  // 个人中心统计：从 /api/v1/dashboard/kpi 拉取真实数据
  const [stats, setStats] = useState<{
    totalSessions: number | null
    monthlyConversations: number | null
    avgTurns: number | null
  }>({ totalSessions: null, monthlyConversations: null, avgTurns: null })
  const [statsLoading, setStatsLoading] = useState(false)

  useEffect(() => {
    if (!isOpen || !user) return
    const token = localStorage.getItem('token')
    if (!token) return

    setStatsLoading(true)
    fetch('/api/v1/dashboard/kpi', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        const sessions = data?.sessions
        if (sessions) {
          setStats({
            totalSessions: typeof sessions.total === 'number' ? sessions.total : 0,
            // 仪表盘目前仅提供 active_today，作为近期对话量展示
            monthlyConversations:
              typeof sessions.active_today === 'number' ? sessions.active_today : 0,
            avgTurns: typeof sessions.avg_turns === 'number' ? sessions.avg_turns : 0,
          })
        } else {
          setStats({ totalSessions: 0, monthlyConversations: 0, avgTurns: 0 })
        }
      })
      .catch(() => {
        // 权限不足或网络异常时回退到 0，避免一直显示 "--"
        setStats({ totalSessions: 0, monthlyConversations: 0, avgTurns: 0 })
      })
      .finally(() => setStatsLoading(false))
  }, [isOpen, user])

  const formatStat = (v: number | null): string => {
    if (v === null) return '--'
    if (!Number.isInteger(v)) return v.toFixed(2)
    return String(v)
  }

  if (!isOpen || !user) return null

  return (
    <div className="profile-modal-overlay" onClick={onClose}>
      <div className="profile-modal" onClick={(e) => e.stopPropagation()}>
        <button className="profile-modal-close" onClick={onClose}>×</button>
        <div className="profile-modal-content">
          <p className="section-label">User Profile</p>
          <h2 className="profile-title">个人中心</h2>

          <div className="profile-header">
            <div className="profile-avatar-large">{getInitials(user.username)}</div>
            <div className="profile-info">
              <h3 className="profile-username">{user.username}</h3>
              <p className="profile-email">{user.email || '未设置邮箱'}</p>
              <span className="profile-plan">免费版</span>
            </div>
          </div>

          <div className="profile-stats">
            <div className="profile-stat-item">
              <div className="profile-stat-value">
                {statsLoading ? '...' : formatStat(stats.totalSessions)}
              </div>
              <div className="profile-stat-label">会话总数</div>
            </div>
            <div className="profile-stat-item">
              <div className="profile-stat-value">
                {statsLoading ? '...' : formatStat(stats.monthlyConversations)}
              </div>
              <div className="profile-stat-label">本月对话</div>
            </div>
            <div className="profile-stat-item">
              <div className="profile-stat-value">
                {statsLoading ? '...' : formatStat(stats.avgTurns)}
              </div>
              <div className="profile-stat-label">平均轮次</div>
            </div>
          </div>

          <div className="profile-section">
            <h4>账号信息</h4>
            <div className="profile-info-row">
              <span className="info-label">用户ID</span>
              <span className="info-value">{user.id}</span>
            </div>
            <div className="profile-info-row">
              <span className="info-label">用户名</span>
              <span className="info-value">{user.username}</span>
            </div>
            <div className="profile-info-row">
              <span className="info-label">邮箱</span>
              <span className="info-value">{user.email || '未设置'}</span>
            </div>
          </div>

          <div className="profile-actions">
            <button className="profile-action-btn" onClick={onLogout}>
              🚪 退出登录
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ============================================================
// Chat Widget — Floating
// ============================================================

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  image?: string
  audio?: string
  suggestHuman?: boolean
}

interface ChatSession {
  session_id: string
  last_message: string
  updated_at: string
  message_count: number
}

const WS_URL = '/ws/chat'

const QUICK_QUESTIONS = [
  { icon: '🔐', text: '如何重置密码？' },
  { icon: '💰', text: '你们的定价方案是什么？' },
  { icon: '🔄', text: '如何取消订阅？' },
  { icon: '📞', text: '联系客服方式' },
]

function FloatingChatWidget({ user, token }: { user: User | null; token: string | null }) {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [connecting, setConnecting] = useState(true)
  const [isTyping, setIsTyping] = useState(false)
  const [sessionId, setSessionId] = useState('')
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [audioPreview, setAudioPreview] = useState<string | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [humanEscalated, setHumanEscalated] = useState(false)
  const [userId, setUserId] = useState('')
  const [showSessionList, setShowSessionList] = useState(false)
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])

  useEffect(() => {
    if (user) {
      setUserId(user.id)
    } else {
      let uid = localStorage.getItem('user_id')
      if (!uid) {
        uid = 'user_' + Math.random().toString(36).substring(2, 15)
        localStorage.setItem('user_id', uid)
      }
      setUserId(uid)
    }

    const sid = localStorage.getItem('session_id') || ''
    if (sid) setSessionId(sid)
  }, [user])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  useEffect(() => {
    if (!userId) return

    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setConnecting(false)
      inputRef.current?.focus()

      const savedSessionId = localStorage.getItem('session_id')
      if (savedSessionId) {
        ws.send(JSON.stringify({
          type: 'resume_session',
          session_id: savedSessionId,
          user_id: userId,
          token: token || undefined,
        }))
      }
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === 'session_ready') {
          setSessionId(data.session_id)
          localStorage.setItem('session_id', data.session_id)
        } else if (data.type === 'typing_indicator') {
          setIsTyping(data.is_typing || false)
        } else if (data.type === 'streaming_chunk') {
          if (data.delta && !data.done) {
            setMessages(prev => {
              const last = prev[prev.length - 1]
              if (last && last.role === 'assistant') {
                const newContent = last.content + data.delta
                const shouldShowButton = data.suggest_human || 
                  newContent.includes('点击下方按钮转接人工客服') ||
                  newContent.includes('转接人工客服')
                const updated = [...prev]
                updated[updated.length - 1] = { 
                  ...last, 
                  content: newContent,
                  suggestHuman: shouldShowButton ? true : last.suggestHuman,
                }
                return updated
              }
              return [...prev, { id: crypto.randomUUID(), role: 'assistant', content: data.delta, timestamp: Date.now() }]
            })
          } else if (data.done) {
            if (data.suggest_human) {
              setMessages(prev => {
                const updated = [...prev]
                const lastIdx = updated.length - 1
                if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') {
                  updated[lastIdx] = { ...updated[lastIdx], suggestHuman: true }
                }
                return updated
              })
            }
          }
        } else if (data.type === 'transfer_notice') {
          if (!humanEscalated) setHumanEscalated(true)
          setMessages(prev => {
            const alreadyHas = prev.some(m => m.role === 'system' && m.content.includes('正在转接人工客服'))
            if (alreadyHas) return prev
            return [...prev, { id: crypto.randomUUID(), role: 'system', content: '🔄 ' + (data.message || '正在转接人工客服...'), timestamp: Date.now() }]
          })
          setIsTyping(false)
        } else if (data.type === 'handoff_context') {
          setMessages(prev => {
            const alreadyHas = prev.some(m => m.role === 'system' && m.content.includes('转接上下文已记录'))
            if (alreadyHas) return prev
            return [...prev, { id: crypto.randomUUID(), role: 'system', content: '📋 转接上下文已记录', timestamp: Date.now() }]
          })
          setIsTyping(false)
        } else if (data.type === 'message_received') {
          setMessages(prev => {
            const alreadyHas = prev.some(m => m.role === 'system' && m.content.includes('消息已发送给人工客服'))
            if (alreadyHas) return prev
            return [...prev, { id: crypto.randomUUID(), role: 'system', content: '✅ 消息已发送给人工客服', timestamp: Date.now() }]
          })
        } else if (data.type === 'info') {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: 'ℹ️ ' + (data.text || ''), timestamp: Date.now() }])
          setIsTyping(false)
        } else if (data.type === 'error') {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: '❌ ' + (data.error_message || '发生错误'), timestamp: Date.now() }])
          setIsTyping(false)
        }
      } catch { console.error('Parse error:', event.data) }
    }

    ws.onclose = () => { setConnected(false); setConnecting(false) }
    ws.onerror = () => { setConnecting(false); setConnected(false); setMessages([]) }
    return () => ws.close()
  }, [userId, token])

  const fetchSessions = async () => {
    if (!user || !token) return
    setSessionsLoading(true)
    try {
      const response = await fetch('/api/v1/sessions', {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      if (response.ok) {
        const data = await response.json()
        setSessions(data.sessions || data || [])
      }
    } catch {
      setSessions([])
    } finally {
      setSessionsLoading(false)
    }
  }

  const loadSession = async (sid: string) => {
    if (!token) return
    try {
      const response = await fetch(`/api/v1/sessions/${sid}`, {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      if (response.ok) {
        const data = await response.json()
        const msgs: ChatMessage[] = (data.messages || []).map((m: any, idx: number) => ({
          id: String(idx),
          role: m.role as 'user' | 'assistant' | 'system',
          content: m.content,
          timestamp: new Date(m.timestamp).getTime(),
        }))
        setMessages(msgs)
        setSessionId(sid)
        localStorage.setItem('session_id', sid)
      }
    } catch {
      console.error('Failed to load session')
    }
    setShowSessionList(false)
  }

  const createNewSession = () => {
    setMessages([])
    setSessionId('')
    localStorage.removeItem('session_id')
    setHumanEscalated(false)
    setShowSessionList(false)
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'new_session',
        user_id: userId,
        token: token || undefined,
      }))
    }
  }

  const sendMessage = () => {
    const text = input.trim()
    if ((!text && !imagePreview && !audioPreview) || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

    setMessages(prev => [...prev, {
      id: crypto.randomUUID(), role: 'user',
      content: text || (imagePreview ? '[图片]' : '[语音]'),
      timestamp: Date.now(),
      image: imagePreview || undefined,
      audio: audioPreview || undefined,
    }])

    wsRef.current.send(JSON.stringify({
      type: 'chat_message', message: text || '[图片消息]',
      session_id: sessionId,
      user_id: userId,
      token: token || undefined,
      image_base64: imagePreview,
      audio_base64: audioPreview,
    }))

    setInput(''); setImagePreview(null); setAudioPreview(null); setIsTyping(true)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const handleHumanEscalate = (_msgId: string) => {
    if (humanEscalated) return
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    setHumanEscalated(true)
    wsRef.current.send(JSON.stringify({
      type: 'human_escalation',
      session_id: sessionId,
      user_id: userId,
      reason: 'user_requested',
    }))
    setMessages(prev => [...prev, {
      id: crypto.randomUUID(),
      role: 'system',
      content: '🔄 正在为您转接人工客服...',
      timestamp: Date.now(),
    }])
  }

  const handleQuickQuestion = (text: string) => { setInput(text); setTimeout(() => sendMessage(), 100) }

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => setImagePreview(ev.target?.result as string)
    reader.readAsDataURL(file)
  }

  const removeImage = () => { setImagePreview(null); if (fileInputRef.current) fileInputRef.current.value = '' }

  const toggleRecording = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop(); setIsRecording(false); return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      mediaRecorderRef.current = mr
      audioChunksRef.current = []
      mr.ondataavailable = (e) => audioChunksRef.current.push(e.data)
      mr.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
        const reader = new FileReader()
        reader.onloadend = () => setAudioPreview(reader.result as string)
        reader.readAsDataURL(blob)
        stream.getTracks().forEach(t => t.stop())
      }
      mr.start(); setIsRecording(true)
    } catch { alert('无法访问麦克风') }
  }

  const formatTime = (ts: number) => new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

  const getInitials = (name: string) => name.charAt(0).toUpperCase()

  const BotIcon = ({ color = '#0B0F19' }: { color?: string }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="7" width="18" height="13" rx="3" />
      <circle cx="9" cy="13" r="1.5" fill={color} stroke="none" />
      <circle cx="15" cy="13" r="1.5" fill={color} stroke="none" />
      <path d="M12 2v3" stroke={color} strokeWidth="1.5" />
      <path d="M8 5h8" stroke={color} strokeWidth="1.5" />
      <path d="M7 18h10" stroke={color} strokeWidth="1.5" opacity="0.5" />
    </svg>
  )

  const handleToggleSessionList = () => {
    if (!showSessionList && user) {
      fetchSessions()
    }
    setShowSessionList(!showSessionList)
  }

  return (
    <>
      <button className="floating-chat-btn" onClick={() => setIsOpen(!isOpen)} title="打开聊天">
        {isOpen ? (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <path d="M18 6L6 18M6 6l12 12" />
          </svg>
        ) : (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        )}
      </button>

      {isOpen && (
        <section id="chat-widget" className="chat-widget floating">
          <div className="chat-panel">
            <div className="chat-header">
              <div className="chat-header-left">
                {user && (
                  <button className="chat-sessions-btn" onClick={handleToggleSessionList} title="会话列表">
                    ☰
                  </button>
                )}
                <span className="chat-bot-icon">
                  <BotIcon color="#0B0F19" />
                </span>
                <div>
                  <h3 className="chat-header-title">智能客服</h3>
                  <span className={`chat-status ${connected ? 'online' : connecting ? 'connecting' : 'offline'}`}>
                    {connecting ? <span className="spinner" /> : connected ? '● 在线' : '○ 离线'}
                  </span>
                </div>
              </div>
              <button className="chat-close-btn" onClick={() => setIsOpen(false)}>×</button>
            </div>

            {showSessionList && user && (
              <div className="chat-session-list">
                <div className="session-list-header">
                  <span>我的会话</span>
                  <button className="new-session-btn" onClick={createNewSession}>+ 新会话</button>
                </div>
                {sessionsLoading && <div className="session-list-loading">加载中...</div>}
                {!sessionsLoading && sessions.length === 0 && (
                  <div className="session-list-empty">暂无会话</div>
                )}
                {!sessionsLoading && sessions.map((s) => (
                  <div
                    key={s.session_id}
                    className={`session-list-item ${s.session_id === sessionId ? 'active' : ''}`}
                    onClick={() => loadSession(s.session_id)}
                  >
                    <div className="session-item-preview">{s.last_message || '新会话'}</div>
                    <div className="session-item-meta">
                      <span>{new Date(s.updated_at).toLocaleDateString('zh-CN')}</span>
                      <span>{s.message_count} 条消息</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="chat-messages">
              {messages.length === 0 && !connecting && (
                <div className="chat-welcome">
                  <p className="chat-welcome-text">你好！我是 Enterprise Agent 智能客服。</p>
                  <div className="chat-quick-questions">
                    {QUICK_QUESTIONS.map((q, i) => (
                      <button key={i} className="chat-quick-btn" onClick={() => handleQuickQuestion(q.text)}>
                        <span className="chat-quick-icon">{q.icon}</span><span>{q.text}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map(msg => (
                <div key={msg.id} className={`chat-message ${msg.role}`}>
                  {msg.role === 'assistant' && (
                    <span className="chat-msg-avatar" title="AI">
                      <BotIcon color="#0B0F19" />
                    </span>
                  )}
                  <div className="chat-msg-bubble">
                    {msg.image && <div className="chat-msg-image"><img src={msg.image} alt="" /></div>}
                    {msg.audio && <div className="chat-msg-audio"><audio controls src={msg.audio} /></div>}
                    {msg.content && <p className="chat-msg-text">{msg.content}</p>}
                    {msg.role === 'assistant' && msg.suggestHuman && (
                      <button 
                        className="human-escalate-btn" 
                        onClick={() => handleHumanEscalate(msg.id)}
                        disabled={humanEscalated}
                      >
                        {humanEscalated ? '✅ 已申请转接' : '🔧 转接人工客服'}
                      </button>
                    )}
                    <span className="chat-msg-time">{formatTime(msg.timestamp)}</span>
                  </div>
                  {msg.role === 'user' && (
                    <span className="chat-msg-avatar" title="你">
                      <span className="initials">{user ? getInitials(user.username) : '你'}</span>
                    </span>
                  )}
                </div>
              ))}

              {isTyping && (
                <div className="chat-message assistant typing">
                  <span className="chat-msg-avatar">
                    <BotIcon color="#0B0F19" />
                  </span>
                  <div className="chat-msg-bubble">
                    <div className="typing-dots"><span /><span /><span /></div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {imagePreview && (
              <div className="image-preview-bar">
                <img src={imagePreview} alt="预览" />
                <button className="remove-btn" onClick={removeImage}>×</button>
              </div>
            )}

            <div className="chat-input-area">
              <button className="tool-btn" onClick={() => fileInputRef.current?.click()} title="发送图片">📷</button>
              <input ref={fileInputRef} type="file" accept="image/*" onChange={handleImageChange} style={{ display: 'none' }} />

              <button className={`tool-btn ${isRecording ? 'recording' : ''}`} onClick={toggleRecording} title={isRecording ? '停止录音' : '语音输入'}>
                {isRecording ? '⏹' : '🎤'}
              </button>

              <input ref={inputRef} type="text" value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown} placeholder="输入你的问题..." disabled={!connected} className="chat-input" />
              <button onClick={sendMessage} disabled={!input.trim() && !imagePreview && !audioPreview || !connected} className="chat-send-btn">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" />
                </svg>
              </button>
            </div>
          </div>
        </section>
      )}
    </>
  )
}

/* ============================================================
   Main App
   ============================================================ */

function App() {
  const [adminModalOpen, setAdminModalOpen] = useState(false)
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [profileModalOpen, setProfileModalOpen] = useState(false)
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)

  // 主题状态：从 localStorage 读取，默认浅色模式
  const [theme, setTheme] = useState<'light' | 'dark'>(
    () => (localStorage.getItem('theme') as 'light' | 'dark') || 'light'
  )

  // 主题副作用：切换 document 的 dark 类并持久化到 localStorage
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('theme', theme)
  }, [theme])

  // 主题切换函数
  const toggleTheme = () => setTheme(prev => (prev === 'light' ? 'dark' : 'light'))

  useEffect(() => {
    const savedToken = localStorage.getItem('token')
    const savedUser = localStorage.getItem('user')
    if (savedToken && savedUser) {
      try {
        setUser(JSON.parse(savedUser))
        setToken(savedToken)
      } catch {
        localStorage.removeItem('token')
        localStorage.removeItem('user')
      }
    }
  }, [])

  const handleLoginSuccess = (u: User, t: string) => {
    setUser(u)
    setToken(t)
  }

  const handleLogout = () => {
    setUser(null)
    setToken(null)
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            entry.target.classList.add('visible')
            observer.unobserve(entry.target)
          }
        })
      },
      { threshold: 0.1, rootMargin: '0px 0px -40px 0px' }
    )

    document.querySelectorAll('.reveal').forEach(el => observer.observe(el))
    return () => observer.disconnect()
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
    <div className="landing-page">
      <Navigation
        onAdminClick={() => setAdminModalOpen(true)}
        user={user}
        onLoginClick={() => setAuthModalOpen(true)}
        onLogout={handleLogout}
        onProfileClick={() => setProfileModalOpen(true)}
      />
      <HeroSection />
      <ArchitectureSection />
      <CapabilitiesSection />
      <MetricsSection />
      <TechDetailsSection />
      <CTASection />
      <Footer />
      <FloatingChatWidget user={user} token={token} />
      <AdminDashboard
        isOpen={adminModalOpen}
        onClose={() => setAdminModalOpen(false)}
        user={user}
        token={token}
        onLoginClick={() => setAuthModalOpen(true)}
      />
      <AuthModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        onLoginSuccess={handleLoginSuccess}
      />
      <ProfileModal
        isOpen={profileModalOpen}
        onClose={() => setProfileModalOpen(false)}
        user={user}
        onLogout={() => { setProfileModalOpen(false); handleLogout() }}
      />
    </div>
    </ThemeContext.Provider>
  )
}

export default App
