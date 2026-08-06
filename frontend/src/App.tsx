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
// Theme Context — dark by default for v2
// ============================================================

const ThemeContext = createContext<{
  theme: 'light' | 'dark'
  toggleTheme: () => void
}>({ theme: 'dark', toggleTheme: () => {} })

// ============================================================
// Navigation — Glass floating bar
// ============================================================

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

  const getInitials = (name: string) => name.charAt(0).toUpperCase()

  return (
    <nav className="nav">
      <a href="#hero" className="nav-brand">
        <div className="nav-logo">E</div>
        <span className="nav-title">Enterprise<span className="brand-highlight">AI</span></span>
      </a>

      <ul className="nav-links">
        <li><a href="#capabilities" className={activeSection === 'capabilities' ? 'active' : ''} onClick={() => setActiveSection('capabilities')}>产品</a></li>
        <li><a href="#architecture" className={activeSection === 'architecture' ? 'active' : ''} onClick={() => setActiveSection('architecture')}>架构</a></li>
        <li><a href="#details" className={activeSection === 'details' ? 'active' : ''} onClick={() => setActiveSection('details')}>技术细节</a></li>
        <li>
          <button className="theme-toggle-btn" onClick={toggleTheme}
            title={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
            aria-label="Toggle theme">
            {theme === 'light' ? '\u263E' : '\u2600'}
          </button>
        </li>
        <li><button className="btn btn-ghost nav-admin-btn" onClick={(e) => { e.preventDefault(); onAdminClick() }}>管理后台</button></li>

        {user ? (
          <li className="nav-user-menu" ref={userMenuRef}>
            <button className="nav-user" onClick={() => setUserMenuOpen(!userMenuOpen)}>
              <div className="nav-user-avatar">{getInitials(user.username)}</div>
              <span className="nav-user-name">{user.username}</span>
            </button>
            {userMenuOpen && (
              <div className="user-dropdown" style={{
                position: 'absolute', top: '100%', right: 0, marginTop: 8,
                background: 'var(--bg-primary)', border: '1px solid var(--glass-border)',
                borderRadius: 'var(--radius-md)', padding: 4, minWidth: 160, boxShadow: 'var(--shadow-lg)', zIndex: 50,
              }}>
                <button style={{ display: 'flex', width: '100%', gap: 8, padding: '8px 12px', border: 'none', background: 'none', fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer', borderRadius: 'var(--radius-sm)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-glass)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}
                  onClick={() => { setUserMenuOpen(false); onProfileClick() }}>
                  个人中心
                </button>
                <button style={{ display: 'flex', width: '100%', gap: 8, padding: '8px 12px', border: 'none', background: 'none', fontSize: 13, color: 'var(--text-secondary)', cursor: 'pointer', borderRadius: 'var(--radius-sm)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-glass)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}
                  onClick={() => { setUserMenuOpen(false); onAdminClick() }}>
                  我的会话
                </button>
                <div style={{ height: 1, background: 'var(--border-subtle)', margin: '4px 8px' }} />
                <button style={{ display: 'flex', width: '100%', gap: 8, padding: '8px 12px', border: 'none', background: 'none', fontSize: 13, color: '#ef4444', cursor: 'pointer', borderRadius: 'var(--radius-sm)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(239,68,68,0.06)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'none')}
                  onClick={() => { setUserMenuOpen(false); onLogout() }}>
                  退出登录
                </button>
              </div>
            )}
          </li>
        ) : (
          <li><button className="btn btn-ghost" onClick={(e) => { e.preventDefault(); onLoginClick() }}>登录</button></li>
        )}
        <li><a href="#chat" className="btn btn-primary nav-cta">开始使用</a></li>
      </ul>

      <button className="nav-mobile-toggle" onClick={() => {}}>
        &#9776;
      </button>
    </nav>
  )
}

// ============================================================
// Hero Section — Split layout with chat preview (Qumica style)
// ============================================================

// 纯静态几何色块背景（SVG 矢量，零依赖、零动画、零 glow）。
// 静态矢量不需要懒加载/降级门控，直接渲染即最稳方案。
import GeometricBackground from './components/GeometricBackground'

function HeroBackground() {
  return (
    <div className="hero-bg" aria-hidden="true">
      <GeometricBackground />
    </div>
  )
}

function HeroSection() {
  return (
    <section className="hero" id="hero">
      <HeroBackground />
      <div className="container">
        <div className="hero-content">
          {/* Left: Copy */}
          <div className="hero-left">
            <div className="hero-tag">
              <span className="hero-tag-dot"></span>
              智能客服工作台 v2.0
            </div>

            <h1 className="hero-title">
              AI 驱动的企业级<br />
              <span className="gradient-text">智能客服平台</span>
            </h1>

            <p className="hero-description">
              融合 LangGraph Agent、RAG 知识库、MCP 工具调用与多租户 RBAC，
              为客服团队打造全链路 AI 辅助决策系统。真实对接阿里云 API，开箱即用。
            </p>

            <div className="hero-actions">
              <button className="btn btn-primary" onClick={() => {
                const el = document.querySelector('.chat-toggle') as HTMLElement
                el?.click()
              }}>
                打开控制台
              </button>
              <button className="btn btn-secondary" onClick={() => {
                const el = document.getElementById('architecture')
                el?.scrollIntoView({ behavior: 'smooth' })
              }}>
                查看文档
              </button>
            </div>

            <div className="hero-metrics">
              <div className="hero-metric">
                <div className="hero-metric-value">99.2%</div>
                <div className="hero-metric-label">意图识别准确率</div>
              </div>
              <div className="hero-metric">
                <div className="hero-metric-value">&lt;800ms</div>
                <div className="hero-metric-label">平均响应延迟</div>
              </div>
              <div className="hero-metric">
                <div className="hero-metric-value">14+</div>
                <div className="hero-metric-label">功能模块</div>
              </div>
            </div>
          </div>

          {/* Right: Chat Preview */}
          <div className="hero-right">
            <div className="hero-chat-preview">
              <div className="hero-chat-header">
                <span className="hero-chat-status-dot"></span>
                <span className="hero-chat-status-text">AI 助手在线</span>
                <span className="hero-chat-status-detail">WebSocket 已连接</span>
              </div>

              <div className="hero-chat-bubbles">
                <div className="chat-bubble chat-bubble-ai">
                  您好！我是企业智能客服助手。我可以帮您查询云资源状态、创建工单或诊断问题。有什么需要帮助的吗？
                </div>
                <div className="chat-bubble chat-bubble-self">
                  帮我查一下生产环境的 ECS 实例状态
                </div>
                <div className="chat-bubble chat-bubble-ai">
                  正在通过阿里云 API 查询...
                  <div className="chat-result-card">
                    <div className="chat-result-card-title">ecs-web-server-prod</div>
                    <div className="chat-result-card-body">
                      状态: <span className="highlight">Running</span> | CPU: 34% | 内存: 56%
                    </div>
                    <div className="chat-result-card-meta">47.98.12.34 | cn-shenzhen</div>
                  </div>
                </div>
              </div>

              <div className="hero-chat-input">
                <span className="hero-chat-input-placeholder">输入消息...</span>
                <div className="hero-chat-input-actions">
                  <div className="hero-chat-input-icon">+</div>
                  <div className="hero-chat-input-send">&#9654;</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

// ============================================================
// Architecture Section — Glass cards
// ============================================================

interface ArchLayer {
  number: string
  name: string
  desc: string
}

const ARCH_LAYERS: ArchLayer[] = [
  { number: '01', name: '接入层 (Gateway)', desc: 'FastAPI 高性能异步服务 + WebSocket 实时双向通信 + APISIX 网关路由' },
  { number: '02', name: '安全层 (Security)', desc: 'RBAC 四角色权限模型 + JWT 鉴权 + 输入检测/输出校验纵深防御' },
  { number: '03', name: '编排层 (Orchestration)', desc: 'LangGraph DAG 工作流引擎 + 5 种对话路径自动路由 + 状态机管理' },
  { number: '04', name: '能力层 (Capability)', desc: 'RAG 混合检索 + ReAct Agent 工具调用 + 三层记忆管理 + 多维评估' },
  { number: '05', name: '数据层 (Data)', desc: 'Milvus 向量库 + PostgreSQL 持久化 + Redis 缓存 + MinIO 对象存储' },
]

function ArchitectureSection() {
  return (
    <section id="architecture" className="architecture">
      <div className="container" style={{ textAlign: 'center' }}>
        <p className="section-label reveal">System Architecture</p>
        <h2 className="section-title reveal">五层架构设计</h2>
        <p className="section-subtitle reveal">
          从接入到数据，每一层都经过精心设计，确保系统的可扩展性、安全性和可维护性。
        </p>
      </div>

      <div className="arch-layers">
        {ARCH_LAYERS.map((layer, i) => (
          <div key={layer.number} className="arch-layer reveal" style={{ transitionDelay: `${i * 80}ms` }}>
            <div className="arch-layer-num">{layer.number}</div>
            <div className="arch-layer-content">
              <div className="arch-layer-name">{layer.name}</div>
              <div className="arch-layer-desc">{layer.desc}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

// ============================================================
// Capabilities Section — Feature grid with colored icons
// ============================================================

interface CapItem {
  icon: string
  title: string
  desc: string
  color: 'teal' | 'purple' | 'blue' | 'amber'
}

const CAPABILITIES: CapItem[] = [
  { icon: '\u26A1', title: 'Agent 引擎', desc: 'LangGraph 编排多步骤推理，ReAct 思考-行动-观察循环，工具调用链路可追踪可调试', color: 'teal' },
  { icon: '\uD83D\uDCDA', title: 'RAG 知识库', desc: 'Milvus 向量检索 + BM25 关键词 + RRF 融合排序，支持文档分片、命中测试与索引重建', color: 'purple' },
  { icon: '\u2601', title: 'MCP 工具链', desc: '真实对接阿里云 ECS/RDS/SLB CloudMonitor API，查询生产资源状态与监控指标', color: 'blue' },
  { icon: '\uD83D\uDEE1', title: '多租户 RBAC', desc: '四角色权限模型（超级管理员/管理员/操作员/访客），数据隔离到租户级别', color: 'amber' },
  { icon: '\uD83D\uDCCA', title: '多维评估', desc: 'RAG 离线检索指标 + LLM-as-Judge 对话质量五维评分 + 幻觉检测机制', color: 'teal' },
  { icon: '\uD83D\uDD17', title: '五种对话路径', desc: 'FAQ 直达 / 技术排查 / 人工转接 / FAQ 升级 RAG / RAG 转人工，自动路由编排', color: 'purple' },
]

function CapabilitiesSection() {
  return (
    <section id="capabilities" className="capabilities">
      <div className="container" style={{ textAlign: 'center' }}>
        <p className="section-label reveal">Core Capabilities</p>
        <h2 className="section-title reveal">全方位 AI 能力矩阵</h2>
        <p className="section-subtitle reveal">
          六大核心能力覆盖企业客服全场景，从简单 FAQ 到复杂工单处理。
        </p>
      </div>

      <div className="capabilities-grid">
        {CAPABILITIES.map((cap, i) => (
          <div className="capability-card reveal" key={cap.title} style={{ transitionDelay: `${i * 60}ms` }}>
            <div className={`capability-icon ${cap.color}`}>{cap.icon}</div>
            <div className="capability-name">{cap.title}</div>
            <div className="capability-desc">{cap.desc}</div>
          </div>
        ))}
      </div>
    </section>
  )
}

// ============================================================
// Metrics Section — Gradient numbers
// ============================================================

interface Metric {
  value: string
  label: string
}

const METRICS: Metric[] = [
  { value: '94.2%', label: 'RAG 检索 Recall@10' },
  { value: '<800ms', label: 'P95 端到端延迟' },
  { value: '<2.1%', label: '幻觉率 (Hallucination)' },
  { value: '5 层', label: '安全纵深防御' },
]

function MetricsSection() {
  return (
    <section className="metrics">
      <div className="container" style={{ textAlign: 'center' }}>
        <p className="section-label reveal">Performance</p>
        <h2 className="section-title reveal">经过验证的核心指标</h2>
      </div>
      <div className="metrics-grid">
        {METRICS.map((m, i) => (
          <div className="metric-card reveal" key={m.label} style={{ transitionDelay: `${i * 80}ms` }}>
            <div className="metric-value">{m.value}</div>
            <div className="metric-label">{m.label}</div>
          </div>
        ))}
      </div>
    </section>
  )
}

// ============================================================
// Tech Details Accordion
// ============================================================

interface DetailItem {
  question: string
  answer: React.ReactNode
}

const DETAILS: DetailItem[] = [
  {
    question: '检索精度如何保障？',
    answer: <>采用 <code>向量语义检索 + BM25 关键词 + RRF 融合排序</code> 三路召回策略。Embedding 使用阿里百炼 text-embedding-v4（1024 维），文档经过语义分块确保上下文完整性。</>,
  },
  {
    question: '记忆管理怎么做？',
    answer: <>三层架构：<code>滑窗短期记忆</code>（Redis 优先，内存 fallback）、<code>LLM 摘要压缩</code>（自动提炼关键信息）、<code>向量长期记忆</code>（PG + Milvus 持久化）。三节点接入：entry → rag → reply。</>,
  },
  {
    question: '安全护栏有几层？',
    answer: <>五层纵深防御：<code>输入检测</code> → <code>编排护栏</code> → <code>Agent 约束</code> → <code>输出校验</code> → <code>审计告警</code>。</>,
  },
  {
    question: '支持哪些 LLM？',
    answer: <>核心使用阿里百炼 Qwen-Plus / Qwen-Max，兼容 OpenAI API 格式。Embedding 使用 text-embedding-v4。</>,
  },
  {
    question: '如何降级？',
    answer: <>所有关键组件均设计了 <code>自动降级</code> 机制：Redis 不可用时降级为进程内存，PostgreSQL 不可用时降级为 SQLite 本地文件存储。</>,
  },
]

function TechDetailsSection() {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(0)

  return (
    <section id="details" className="tech-details">
      <div className="container" style={{ textAlign: 'center' }}>
        <p className="section-label reveal">Deep Dive</p>
        <h2 className="section-title reveal">技术细节</h2>
      </div>

      <div className="details-list">
        {DETAILS.map((item, i) => (
          <div className={`detail-item ${expandedIndex === i ? 'open' : ''}`} key={i}>
            <button
              className="detail-summary"
              onClick={() => setExpandedIndex(expandedIndex === i ? null : i)}
            >
              <span>{item.question}</span>
              <span className="detail-chevron">&#9660;</span>
            </button>
            {expandedIndex === i && (
              <div className="detail-body">{item.answer}</div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}

// ============================================================
// CTA Section
// ============================================================

function CTASection() {
  return (
    <section id="chat" className="cta-section">
      <div className="container">
        <div className="cta-card reveal">
          <h2 className="cta-title">准备好升级你的客服体验了吗？</h2>
          <p className="cta-desc">
            从传统 FAQ 机器人到真正的企业级 AI 智能客服，只差一次对话的距离。
          </p>
          <div className="cta-buttons">
            <button className="btn btn-primary" onClick={() => {
              const el = document.querySelector('.chat-toggle') as HTMLElement
              el?.click()
            }}>
              开始对话
            </button>
            <button className="btn btn-secondary" onClick={() => {
              window.open('https://github.com/addhai/enterprise-agent', '_blank')
            }}>
              GitHub
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}

// ============================================================
// Footer — Tech stack wall
// ============================================================

function Footer() {
  const techStack = ['Python / FastAPI', 'React 19 + TypeScript', 'LangGraph', 'Milvus + PostgreSQL', 'Docker Compose', '阿里云 API']

  return (
    <footer className="footer">
      <div className="container">
        <div className="footer-inner">
          <div className="footer-brand">
            <div className="footer-brand-logo">E</div>
            EnterpriseAI
          </div>
          <div className="footer-tech-stack">
            {techStack.map(t => (
              <span key={t} className="footer-tech-item">{t}</span>
            ))}
          </div>
          <div className="footer-copy">Enterprise Agent &copy; {new Date().getFullYear()}</div>
        </div>
      </div>
    </footer>
  )
}

// ============================================================
// Auth Modal — Glassmorphism
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
      const body = activeTab === 'login' ? { username, password } : { username, email, password }

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
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ position: 'relative' }}>
        <button className="modal-close" onClick={onClose}>&times;</button>

        <h2 className="modal-title">{activeTab === 'login' ? '欢迎回来' : '创建账号'}</h2>
        <p className="modal-subtitle">{activeTab === 'login' ? '登录你的 Enterprise AI 账号' : '注册一个新账号开始使用'}</p>

        <div className="modal-tabs">
          <button className={`modal-tab ${activeTab === 'login' ? 'active' : ''}`} onClick={() => { setActiveTab('login'); setError('') }}>登录</button>
          <button className={`modal-tab ${activeTab === 'register' ? 'active' : ''}`} onClick={() => { setActiveTab('register'); setError('') }}>注册</button>
        </div>

        {error && <div style={{ padding: '10px 14px', borderRadius: 'var(--radius-sm)', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', color: '#ef4444', fontSize: 13, marginBottom: 16 }}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">用户名</label>
            <input className="form-input" type="text" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="请输入用户名" required />
          </div>

          {activeTab === 'register' && (
            <div className="form-group">
              <label className="form-label">邮箱</label>
              <input className="form-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="请输入邮箱" required />
            </div>
          )}

          <div className="form-group">
            <label className="form-label">密码</label>
            <input className="form-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="请输入密码" required />
          </div>

          {activeTab === 'register' && (
            <div className="form-group">
              <label className="form-label">确认密码</label>
              <input className="form-input" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} placeholder="请再次输入密码" required />
            </div>
          )}

          <button type="submit" className="form-submit" disabled={loading}>
            {loading ? '处理中...' : (activeTab === 'login' ? '登录' : '注册')}
          </button>
        </form>

        <div className="admin-quick-login">
          <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 8px' }}>快速入口：</p>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
            <button className="admin-quick-login-btn" onClick={handleAdminLogin} disabled={loading}>管理员登录</button>
            <button className="btn btn-ghost" style={{ fontSize: 12, padding: '6px 16px' }} onClick={handleDemoLogin}>演示模式</button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ============================================================
// Profile Modal
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

  const [stats, setStats] = useState<{ totalSessions: number | null; monthlyConversations: number | null; avgTurns: number | null }>({ totalSessions: null, monthlyConversations: null, avgTurns: null })
  const [statsLoading, setStatsLoading] = useState(false)

  useEffect(() => {
    if (!isOpen || !user) return
    const token = localStorage.getItem('token')
    if (!token) return

    setStatsLoading(true)
    fetch('/api/v1/dashboard/kpi', { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        const sessions = data?.sessions
        if (sessions) {
          setStats({
            totalSessions: typeof sessions.total === 'number' ? sessions.total : 0,
            monthlyConversations: typeof sessions.active_today === 'number' ? sessions.active_today : 0,
            avgTurns: typeof sessions.avg_turns === 'number' ? sessions.avg_turns : 0,
          })
        } else {
          setStats({ totalSessions: 0, monthlyConversations: 0, avgTurns: 0 })
        }
      })
      .catch(() => setStats({ totalSessions: 0, monthlyConversations: 0, avgTurns: 0 }))
      .finally(() => setStatsLoading(false))
  }, [isOpen, user])

  const formatStat = (v: number | null): string => {
    if (v === null) return '--'
    if (!Number.isInteger(v)) return v.toFixed(2)
    return String(v)
  }

  if (!isOpen || !user) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal profile-modal" onClick={(e) => e.stopPropagation()} style={{ position: 'relative', maxHeight: '80vh', overflowY: 'auto' }}>
        <button className="modal-close" onClick={onClose}>&times;</button>

        <p className="section-label" style={{ textAlign: 'left' }}>Profile</p>
        <h2 className="modal-title" style={{ textAlign: 'left' }}>个人中心</h2>

        <div className="profile-header">
          <div className="profile-avatar">{getInitials(user.username)}</div>
          <div className="profile-info">
            <div className="profile-name">{user.username}</div>
            <div className="profile-role">{user.email || '未设置邮箱'}</div>
          </div>
        </div>

        <div className="profile-stats">
          <div className="profile-stat">
            <div className="profile-stat-value">{statsLoading ? '...' : formatStat(stats.totalSessions)}</div>
            <div className="profile-stat-label">会话总数</div>
          </div>
          <div className="profile-stat">
            <div className="profile-stat-value">{statsLoading ? '...' : formatStat(stats.monthlyConversations)}</div>
            <div className="profile-stat-label">今日对话</div>
          </div>
          <div className="profile-stat">
            <div className="profile-stat-value">{statsLoading ? '...' : formatStat(stats.avgTurns)}</div>
            <div className="profile-stat-label">平均轮次</div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[
            { label: '用户 ID', value: user.id },
            { label: '用户名', value: user.username },
            { label: '邮箱', value: user.email || '未设置' },
            { label: '角色', value: user.role || '默认角色' },
          ].map(row => (
            <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>{row.label}</span>
              <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--mono)', fontSize: 12 }}>{row.value}</span>
            </div>
          ))}
        </div>

        <button className="btn btn-ghost" style={{ marginTop: 24, width: '100%', justifyContent: 'center', color: '#ef4444', borderColor: 'rgba(239,68,68,0.2)' }}
          onClick={() => { onClose(); onLogout() }}>
          退出登录
        </button>
      </div>
    </div>
  )
}

// ============================================================
// Chat Widget — Floating (preserving ALL logic, updating class names)
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
  { icon: '', text: '如何重置密码？' },
  { icon: '', text: '定价方案是什么？' },
  { icon: '', text: '如何联系人工客服？' },
  { icon: '', text: '查看系统架构' },
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
    if (user) { setUserId(user.id) } else {
      let uid = localStorage.getItem('user_id')
      if (!uid) { uid = 'user_' + Math.random().toString(36).substring(2, 15); localStorage.setItem('user_id', uid) }
      setUserId(uid)
    }
    const sid = localStorage.getItem('session_id') || ''
    if (sid) setSessionId(sid)
  }, [user])

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, isTyping])

  useEffect(() => {
    if (!userId) return
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true); setConnecting(false); inputRef.current?.focus()
      const savedSessionId = localStorage.getItem('session_id')
      if (savedSessionId) {
        ws.send(JSON.stringify({ type: 'resume_session', session_id: savedSessionId, user_id: userId, token: token || undefined }))
      }
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'session_ready') { setSessionId(data.session_id); localStorage.setItem('session_id', data.session_id) }
        else if (data.type === 'typing_indicator') { setIsTyping(data.is_typing || false) }
        else if (data.type === 'streaming_chunk') {
          if (data.delta && !data.done) {
            setMessages(prev => {
              const last = prev[prev.length - 1]
              if (last && last.role === 'assistant') {
                const newContent = last.content + data.delta
                const shouldShowButton = data.suggest_human || newContent.includes('点击下方按钮转接人工客服') || newContent.includes('转接人工客服')
                const updated = [...prev]
                updated[updated.length - 1] = { ...last, content: newContent, suggestHuman: shouldShowButton ? true : last.suggestHuman }
                return updated
              }
              return [...prev, { id: crypto.randomUUID(), role: 'assistant', content: data.delta, timestamp: Date.now() }]
            })
          } else if (data.done) {
            if (data.suggest_human) {
              setMessages(prev => { const updated = [...prev]; const lastIdx = updated.length - 1; if (lastIdx >= 0 && updated[lastIdx].role === 'assistant') updated[lastIdx] = { ...updated[lastIdx], suggestHuman: true }; return updated })
            }
          }
        } else if (data.type === 'transfer_notice') { if (!humanEscalated) setHumanEscalated(true); setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: '正在为您转接人工客服...', timestamp: Date.now() }]); setIsTyping(false) }
        else if (data.type === 'handoff_context') { setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: '转接上下文已记录', timestamp: Date.now() }]); setIsTyping(false) }
        else if (data.type === 'message_received') { setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: '消息已发送给人工客服', timestamp: Date.now() }]) }
        else if (data.type === 'info') { setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: data.text || '', timestamp: Date.now() }]); setIsTyping(false) }
        else if (data.type === 'error') { setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: data.error_message || '发生错误', timestamp: Date.now() }]); setIsTyping(false) }
      } catch { /* ignore */ }
    }

    ws.onclose = () => { setConnected(false); setConnecting(false) }
    ws.onerror = () => { setConnecting(false); setConnected(false); setMessages([]) }
    return () => ws.close()
  }, [userId, token])

  const fetchSessions = async () => {
    if (!user || !token) return
    setSessionsLoading(true)
    try {
      const response = await fetch('/api/v1/sessions', { headers: { Authorization: `Bearer ${token}` } })
      if (response.ok) { const data = await response.json(); setSessions(data.sessions || data || []) }
    } catch { setSessions([]) } finally { setSessionsLoading(false) }
  }

  const loadSession = async (sid: string) => {
    if (!token) return
    try {
      const response = await fetch(`/api/v1/sessions/${sid}`, { headers: { Authorization: `Bearer ${token}` } })
      if (response.ok) {
        const data = await response.json()
        const msgs: ChatMessage[] = (data.messages || []).map((m: any, idx: number) => ({
          id: String(idx), role: m.role as 'user' | 'assistant' | 'system',
          content: m.content, timestamp: new Date(m.timestamp).getTime(),
        }))
        setMessages(msgs); setSessionId(sid); localStorage.setItem('session_id', sid)
      }
    } catch { /* ignore */ }
    setShowSessionList(false)
  }

  const createNewSession = () => {
    setMessages([]); setSessionId(''); localStorage.removeItem('session_id'); setHumanEscalated(false); setShowSessionList(false)
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'new_session', user_id: userId, token: token || undefined }))
    }
  }

  const sendMessage = () => {
    const text = input.trim()
    if ((!text && !imagePreview && !audioPreview) || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'user', content: text || (imagePreview ? '[图片]' : '[语音]'), timestamp: Date.now(), image: imagePreview || undefined, audio: audioPreview || undefined }])
    wsRef.current.send(JSON.stringify({ type: 'chat_message', message: text || '[图片消息]', session_id: sessionId, user_id: userId, token: token || undefined, image_base64: imagePreview, audio_base64: audioPreview }))
    setInput(''); setImagePreview(null); setAudioPreview(null); setIsTyping(true); inputRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }

  const handleHumanEscalate = (_msgId: string) => {
    if (humanEscalated || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    setHumanEscalated(true)
    wsRef.current.send(JSON.stringify({ type: 'human_escalation', session_id: sessionId, user_id: userId, reason: 'user_requested' }))
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: '正在为您转接人工客服...', timestamp: Date.now() }])
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
    if (isRecording) { mediaRecorderRef.current?.stop(); setIsRecording(false); return }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      mediaRecorderRef.current = mr; audioChunksRef.current = []
      mr.ondataavailable = (e) => audioChunksRef.current.push(e.data)
      mr.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: 'audio/webm' })
        const reader = new FileReader()
        reader.onloadend = () => setAudioPreview(reader.result as string)
        reader.readAsDataURL(blob); stream.getTracks().forEach(t => t.stop())
      }
      mr.start(); setIsRecording(true)
    } catch { alert('无法访问麦克风') }
  }

  const formatTime = (ts: number) => new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

  const BotIcon = ({ color = 'var(--brand-teal)' }: { color?: string }) => (
    <svg viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="20" height="20">
      <rect x="3" y="7" width="18" height="13" rx="3" /><circle cx="9" cy="13" r="1.5" fill={color} stroke="none" /><circle cx="15" cy="13" r="1.5" fill={color} stroke="none" />
      <path d="M12 2v3" stroke={color} strokeWidth="1.5" /><path d="M8 5h8" stroke={color} strokeWidth="1.5" /><path d="M7 18h10" stroke={color} strokeWidth="1.5" opacity="0.5" />
    </svg>
  )

  const handleToggleSessionList = () => { if (!showSessionList && user) fetchSessions(); setShowSessionList(!showSessionList) }

  return (
    <>
      <button className="chat-toggle" onClick={() => setIsOpen(!isOpen)} title="打开聊天">
        {isOpen ? (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
        ) : (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
        )}
      </button>

      {isOpen && (
        <div className="chat-widget">
          <div className="chat-panel">
            <div className="chat-panel-header">
              <div className="chat-panel-title">
                {user && (
                  <button className="chat-panel-action-btn" onClick={handleToggleSessionList} title="会话列表" style={{ marginRight: 4 }}>&#9776;</button>
                )}
                <BotIcon />
                <span style={{ marginLeft: 8 }}>智能客服</span>
              </div>
              <div className="chat-panel-actions">
                <span className={`hero-chat-status-dot ${connected ? '' : 'chat-panel-status-disconnected'} ${connecting ? 'chat-panel-status-connecting' : ''}`}></span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{connecting ? '连接中' : connected ? '已连接' : '离线'}</span>
                <button className="chat-panel-action-btn" onClick={() => setIsOpen(false)}>&times;</button>
              </div>
            </div>

            {showSessionList && user && (
              <div className="chat-session-sidebar">
                <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>我的会话</span>
                  <button className="dash-btn dash-btn-sm" onClick={createNewSession}>+ 新会话</button>
                </div>
                <div className="chat-session-list">
                  {sessionsLoading && <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>加载中...</div>}
                  {!sessionsLoading && sessions.length === 0 && <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>暂无会话</div>}
                  {!sessionsLoading && sessions.map(s => (
                    <div key={s.session_id} className={`chat-session-item ${s.session_id === sessionId ? 'active' : ''}`} onClick={() => loadSession(s.session_id)}>
                      {s.last_message || '新会话'}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="chat-messages">
              {messages.length === 0 && !connecting && (
                <div style={{ padding: 24, textAlign: 'center' }}>
                  <p style={{ color: 'var(--text-secondary)', fontSize: 13, marginBottom: 12 }}>你好！我是 Enterprise AI 智能客服助手。</p>
                  <div className="chat-quick-questions">
                    {QUICK_QUESTIONS.map((q, i) => (
                      <button key={i} className="chat-quick-q" onClick={() => handleQuickQuestion(q.text)}>{q.text}</button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map(msg => (
                <div key={msg.id} className={`chat-msg ${msg.role}`}>
                  {msg.role === 'assistant' && <BotIcon style={{ marginRight: 8, flexShrink: 0, opacity: 0.6 }} />}
                  <div className={msg.role === 'system' ? 'chat-msg system' : msg.role === 'user' ? 'chat-msg user' : 'chat-msg ai'}>
                    {msg.image && <img src={msg.image} alt="" style={{ maxWidth: 200, borderRadius: 8, marginTop: 6 }} />}
                    {msg.audio && <audio controls src={msg.audio} style={{ width: 200, height: 28, marginTop: 6 }} />}
                    {msg.content && <span>{msg.content}</span>}
                    {msg.role === 'assistant' && msg.suggestHuman && (
                      <button className="badge badge-purple" style={{ marginTop: 8, cursor: 'pointer', border: 'none', padding: '6px 14px' }}
                        onClick={() => handleHumanEscalate(msg.id)} disabled={humanEscalated}>
                        {humanEscalated ? '已申请转接' : '转接人工客服'}
                      </button>
                    )}
                    <span style={{ display: 'block', fontSize: 10, color: 'var(--text-dim)', marginTop: 4 }}>{formatTime(msg.timestamp)}</span>
                  </div>
                </div>
              ))}

              {isTyping && (
                <div className="chat-msg ai">
                  <BotIcon style={{ marginRight: 8, flexShrink: 0, opacity: 0.6 }} />
                  <div className="chat-msg-thinking">
                    <span className="chat-thinking-dot"></span>
                    <span className="chat-thinking-dot"></span>
                    <span className="chat-thinking-dot"></span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {imagePreview && (
              <div style={{ padding: '8px 12px', borderTop: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 8 }}>
                <img src={imagePreview} alt="" style={{ height: 40, borderRadius: 6 }} />
                <button className="chat-panel-action-btn" onClick={removeImage}>&times;</button>
              </div>
            )}

            <div className="chat-input-area">
              <div className="chat-input-row">
                <input ref={inputRef} className="chat-input" type="text" value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown} placeholder="输入消息..." disabled={!connected} />
                <button className="chat-send-btn" onClick={sendMessage} disabled={!input.trim() && !imagePreview && !audioPreview || !connected}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" /></svg>
                </button>
              </div>
              <div className="chat-input-tools">
                <button className="chat-tool-btn" onClick={() => fileInputRef.current?.click()} title="发送图片">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
                </button>
                <input ref={fileInputRef} type="file" accept="image/*" onChange={handleImageChange} style={{ display: 'none' }} />
                <button className={`chat-tool-btn ${isRecording ? 'badge-danger' : ''}`} onClick={toggleRecording} title={isRecording ? '停止录音' : '语音输入'}>
                  {isRecording ? '\u25A0\u25A0' : '\uD83C\uDFA4'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ============================================================
// Main App
// ============================================================

function App() {
  const [adminModalOpen, setAdminModalOpen] = useState(false)
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [profileModalOpen, setProfileModalOpen] = useState(false)
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)

  // Dark mode by default in v2
  const [theme, setTheme] = useState<'light' | 'dark'>(
    () => (localStorage.getItem('theme') as 'light' | 'dark') || 'dark'
  )

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    localStorage.setItem('theme', theme)
  }, [theme])

  const toggleTheme = () => setTheme(prev => (prev === 'light' ? 'dark' : 'light'))

  useEffect(() => {
    const savedToken = localStorage.getItem('token')
    const savedUser = localStorage.getItem('user')
    if (savedToken && savedUser) {
      try { setUser(JSON.parse(savedUser)); setToken(savedToken) } catch { localStorage.removeItem('token'); localStorage.removeItem('user') }
    }
  }, [])

  const handleLoginSuccess = (u: User, t: string) => { setUser(u); setToken(t) }
  const handleLogout = () => { setUser(null); setToken(null); localStorage.removeItem('token'); localStorage.removeItem('user') }

  // Scroll reveal observer
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => entries.forEach(entry => { if (entry.isIntersecting) { entry.target.classList.add('visible'); observer.unobserve(entry.target) } }),
      { threshold: 0.1, rootMargin: '0px 0px -40px 0px' }
    )
    document.querySelectorAll('.reveal').forEach(el => observer.observe(el))
    return () => observer.disconnect()
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      <div className="landing-page">
        <Navigation onAdminClick={() => setAdminModalOpen(true)} user={user} onLoginClick={() => setAuthModalOpen(true)} onLogout={handleLogout} onProfileClick={() => setProfileModalOpen(true)} />
        <HeroSection />
        <ArchitectureSection />
        <CapabilitiesSection />
        <MetricsSection />
        <TechDetailsSection />
        <CTASection />
        <Footer />
        <FloatingChatWidget user={user} token={token} />
        <AdminDashboard isOpen={adminModalOpen} onClose={() => setAdminModalOpen(false)} user={user} token={token} onLoginClick={() => setAuthModalOpen(true)} />
        <AuthModal isOpen={authModalOpen} onClose={() => setAuthModalOpen(false)} onLoginSuccess={handleLoginSuccess} />
        <ProfileModal isOpen={profileModalOpen} onClose={() => setProfileModalOpen(false)} user={user} onLogout={() => { setProfileModalOpen(false); handleLogout() }} />
      </div>
    </ThemeContext.Provider>
  )
}

export default App
