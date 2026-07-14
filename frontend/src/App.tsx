import { useState, useRef, useEffect } from 'react'
import './App.css'

// ============================================================
// Landing Page — Enterprise Agent 官网首页
// Dark editorial · Grain texture · Circuit architecture
// ============================================================

/* ---------- Navigation ---------- */

function Navigation() {
  const [activeSection, setActiveSection] = useState('hero')

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
        <li><a href="#admin" className="nav-link-admin" onClick={(e) => { e.preventDefault(); document.getElementById('admin')?.scrollIntoView({ behavior: 'smooth' }) }}>管理后台</a></li>
        <li><a href="#chat" className="nav-cta">申请试用</a></li>
      </ul>
    </nav>
  )
}

/* ---------- Hero ---------- */

function HeroSection() {
  return (
    <section className="hero" id="hero">
      {/* Floating particles */}
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
            <>
              <div className="arch-layer reveal" key={layer.number} style={{ transitionDelay: `${i * 80}ms` }}>
                <span className="arch-layer-number">{layer.number}</span>
                <h3 className="arch-layer-name">{layer.name}</h3>
                <p className="arch-layer-desc">{layer.desc}</p>
              </div>
              {i < ARCH_LAYERS.length - 1 && (
                <span className="arch-arrow" aria-hidden="true">→</span>
              )}
            </>
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
// Chat Widget — Floating
// ============================================================

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  image?: string
  audio?: string
}

const WS_URL = 'ws://127.0.0.1:8000/ws/chat'

const QUICK_QUESTIONS = [
  { icon: '🔐', text: '如何重置密码？' },
  { icon: '💰', text: '你们的定价方案是什么？' },
  { icon: '🔄', text: '如何取消订阅？' },
  { icon: '📞', text: '联系客服方式' },
]

function FloatingChatWidget() {
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

  const wsRef = useRef<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const audioChunksRef = useRef<Blob[]>([])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  useEffect(() => {
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setConnecting(false)
      inputRef.current?.focus()
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === 'session_ready') {
          setSessionId(data.session_id)
        } else if (data.type === 'typing_indicator') {
          setIsTyping(data.is_typing || false)
        } else if (data.type === 'streaming_chunk') {
          if (data.delta && !data.done) {
            setMessages(prev => {
              const last = prev[prev.length - 1]
              if (last && last.role === 'assistant') {
                const updated = [...prev]
                updated[updated.length - 1] = { ...last, content: last.content + data.delta }
                return updated
              }
              return [...prev, { id: crypto.randomUUID(), role: 'assistant', content: data.delta, timestamp: Date.now() }]
            })
          }
        } else if (data.type === 'transfer_notice') {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: '🔄 ' + (data.message || '正在转接人工客服...'), timestamp: Date.now() }])
          setIsTyping(false)
        } else if (data.type === 'handoff_context') {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: '📋 转接上下文已记录', timestamp: Date.now() }])
          setIsTyping(false)
        } else if (data.type === 'message_received') {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: '✅ 消息已发送给人工客服', timestamp: Date.now() }])
        } else if (data.type === 'info') {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: 'ℹ️ ' + (data.text || ''), timestamp: Date.now() }])
        } else if (data.type === 'error') {
          setMessages(prev => [...prev, { id: crypto.randomUUID(), role: 'system', content: '❌ ' + (data.error_message || '发生错误'), timestamp: Date.now() }])
          setIsTyping(false)
        }
      } catch { console.error('Parse error:', event.data) }
    }

    ws.onclose = () => { setConnected(false); setConnecting(false) }
    ws.onerror = () => { setConnecting(false); setConnected(false); setMessages([]) }
    return () => ws.close()
  }, [])

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
      image_base64: imagePreview,
      audio_base64: audioPreview,
    }))

    setInput(''); setImagePreview(null); setAudioPreview(null); setIsTyping(true)
    inputRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
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

  // Bot SVG icon component
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

  return (
    <>
      {/* 悬浮按钮 */}
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

      {/* 聊天面板 */}
      {isOpen && (
        <section id="chat-widget" className="chat-widget floating">
          <div className="chat-panel">
            <div className="chat-header">
              <div className="chat-header-left">
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
                    <span className="chat-msg-time">{formatTime(msg.timestamp)}</span>
                  </div>
                  {msg.role === 'user' && (
                    <span className="chat-msg-avatar" title="你">
                      <span className="initials">你</span>
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

// ============================================================
// Admin Dashboard
// ============================================================

interface MetricData {
  total_requests: number
  resolved: number
  unresolved: number
  resolution_rate: number
  escalation_rate: number
  avg_turns: number
}

function AdminDashboard() {
  const [activeTab, setActiveTab] = useState<'metrics' | 'channels' | 'sessions'>('metrics')
  const [businessMetrics, setBusinessMetrics] = useState<MetricData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/v1/metrics/business')
      .then(r => {
        if (!r.ok) throw new Error('API not available')
        return r.json()
      })
      .then(setBusinessMetrics)
      .catch(() => setError('后端指标服务未运行，请先启动后端'))
      .finally(() => setLoading(false))
  }, [])

  const StatCard = ({ label, value, color }: { label: string; value: string; color: string }) => (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ color }}>{value}</div>
    </div>
  )

  if (loading) return <div className="admin-loading">加载中...</div>
  if (error) return <div className="admin-error">{error}</div>

  return (
    <section id="admin" className="admin-section">
      <div className="container">
        <p className="section-label">Admin Dashboard</p>
        <h2 className="admin-title">管理后台</h2>

        <div className="admin-tabs">
          <button className={`tab-btn ${activeTab === 'metrics' ? 'active' : ''}`} onClick={() => setActiveTab('metrics')}>📊 监控指标</button>
          <button className={`tab-btn ${activeTab === 'channels' ? 'active' : ''}`} onClick={() => setActiveTab('channels')}>🔌 渠道管理</button>
          <button className={`tab-btn ${activeTab === 'sessions' ? 'active' : ''}`} onClick={() => setActiveTab('sessions')}>💬 会话管理</button>
        </div>

        {activeTab === 'metrics' && businessMetrics && (
          <div className="metrics-grid">
            <StatCard label="总请求数" value={String(businessMetrics.total_requests || 0)} color="#667eea" />
            <StatCard label="已解决" value={String(businessMetrics.resolved || 0)} color="#4ade80" />
            <StatCard label="未解决" value={String(businessMetrics.unresolved || 0)} color="#f87171" />
            <StatCard label="解决率" value={`${((businessMetrics.resolution_rate || 0) * 100).toFixed(1)}%`} color="#667eea" />
            <StatCard label="转人工率" value={`${((businessMetrics.escalation_rate || 0) * 100).toFixed(1)}%`} color="#fbbf24" />
            <StatCard label="平均轮数" value={((businessMetrics.avg_turns || 0).toFixed(1))} color="#a78bfa" />
          </div>
        )}

        {activeTab === 'channels' && (
          <div className="channel-grid">
            {[
              { name: 'Web 直连', status: 'active' as const, icon: '🌐', desc: '浏览器 WebSocket 直连' },
              { name: '微信公众号', status: 'inactive' as const, icon: '💬', desc: '需要配置微信服务器地址' },
              { name: '电话热线', status: 'inactive' as const, icon: '📞', desc: 'Twilio 集成，需配置 API Key' },
              { name: 'Chatwoot', status: 'inactive' as const, icon: '🪺', desc: '需要部署 Chatwoot 实例' },
            ].map(ch => (
              <div className="channel-card" key={ch.name}>
                <span className="channel-icon">{ch.icon}</span>
                <div className="channel-info">
                  <h4>{ch.name}</h4>
                  <p>{ch.desc}</p>
                </div>
                <span className={`channel-badge ${ch.status}`}>{ch.status === 'active' ? '已启用' : '未配置'}</span>
              </div>
            ))}
          </div>
        )}

        {activeTab === 'sessions' && (
          <div className="sessions-placeholder">
            <p>会话管理功能开发中...</p>
            <p className="hint">可通过 <code>/api/v1/metrics/all</code> 查看实时数据</p>
          </div>
        )}
      </div>
    </section>
  )
}

/* ============================================================
   Main App
   ============================================================ */

function App() {
  // Scroll reveal observer
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
    <div className="landing-page">
      <Navigation />
      <HeroSection />
      <ArchitectureSection />
      <CapabilitiesSection />
      <MetricsSection />
      <TechDetailsSection />
      <CTASection />
      <AdminDashboard />
      <Footer />
      <FloatingChatWidget />
    </div>
  )
}

export default App
