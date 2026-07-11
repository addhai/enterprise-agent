# ============================================================================
# Enterprise Agent — 前端部署指南
# ============================================================================

## 方案：React SPA → Vercel 免费托管 / 或 Nginx 静态托管

### 方式一：Vercel 免费托管（推荐，自带 CDN + HTTPS）

```bash
# 1. 安装 Vercel CLI
npm i -g vercel

# 2. 进入前端目录
cd enterprise-agent-web

# 3. 部署（首次会引导登录）
vercel --prod

# 4. 返回域名，例如: https://enterprise-agent.vercel.app
```

**环境变量**（Vercel Dashboard → Settings → Environment Variables）：
```
VITE_API_URL=https://你的域名/api/v1
VITE_WS_URL=wss://你的域名/ws
```

### 方式二：Nginx 静态托管（和后端同一台机器）

```bash
# 1. 构建前端
cd enterprise-agent-web
npm run build

# 2. 产物复制到 Nginx 静态目录
cp -r dist/* /opt/enterprise-agent/static/

# 3. 重启 Nginx
sudo systemctl reload nginx
```

---

## 前端核心代码结构

```
enterprise-agent-web/
├── public/
│   └── favicon.ico
├── src/
│   ├── App.tsx                    # 主组件（聊天窗口）
│   ├── main.tsx                   # 入口
│   ├── components/
│   │   ├── ChatWindow.tsx         # 聊天主面板
│   │   ├── MessageBubble.tsx      # 消息气泡（文字/图片/语音）
│   │   ├── InputBar.tsx           # 输入栏
│   │   └── TypingIndicator.tsx    # 正在输入提示
│   ├── hooks/
│   │   └── useWebSocket.ts        # WebSocket 连接管理
│   ├── stores/
│   │   └── chatStore.ts           # Zustand 状态管理
│   └── vite-env.d.ts
├── index.html
├── vite.config.ts
├── package.json
└── tsconfig.json
```

---

## 关键文件模板

### package.json
```json
{
  "name": "enterprise-agent-web",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^5.0.0",
    "axios": "^1.7.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.4.0",
    "vite": "^5.4.0"
  }
}
```

### vite.config.ts
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
```

### src/hooks/useWebSocket.ts（核心）
```typescript
import { useEffect, useRef, useCallback } from 'react'

interface WSMessage {
  type: string
  session_id?: string
  delta?: string
  done?: boolean
  text?: string
  error_message?: string
  is_typing?: boolean
  status?: string
}

export function useWebSocket(onMessage: (msg: WSMessage) => void) {
  const ws = useRef<WebSocket | null>(null)
  const sessionId = useRef<string>('')

  const connect = useCallback((domain: string) => {
    const protocol = domain.startsWith('https') ? 'wss' : 'ws'
    const url = `${protocol}://${domain}/ws/chat`

    ws.current = new WebSocket(url)

    ws.current.onopen = () => {
      console.log('WebSocket connected')
    }

    ws.current.onmessage = (e) => {
      const msg = JSON.parse(e.data) as WSMessage
      if (msg.type === 'session_ready') {
        sessionId.current = msg.session_id!
      }
      onMessage(msg)
    }

    ws.current.onclose = () => {
      console.log('WebSocket disconnected, reconnecting in 3s...')
      setTimeout(() => connect(domain), 3000)
    }

    ws.current.onerror = (err) => {
      console.error('WebSocket error:', err)
    }
  }, [onMessage])

  const sendMessage = useCallback((text: string, imageBase64?: string, audioBase64?: string) => {
    if (!ws.current || ws.current.readyState !== WebSocket.OPEN) return

    ws.current.send(JSON.stringify({
      type: 'chat_message',
      message: text,
      session_id: sessionId.current,
      image_base64: imageBase64,
      audio_base64: audioBase64,
    }))
  }, [])

  const disconnect = useCallback(() => {
    ws.current?.close()
  }, [])

  useEffect(() => {
    return disconnect
  }, [disconnect])

  return { connect, sendMessage, sessionId: sessionId.current }
}
```

### src/stores/chatStore.ts
```typescript
import { create } from 'zustand'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  image?: string  // base64
  audio?: string  // base64
}

interface ChatState {
  messages: Message[]
  isTyping: boolean
  addMessage: (msg: Omit<Message, 'id' | 'timestamp'>) => void
  appendToLastAI: (text: string) => void
  setTyping: (v: boolean) => void
  clear: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isTyping: false,

  addMessage: (msg) => set((state) => ({
    messages: [...state.messages, { ...msg, id: crypto.randomUUID(), timestamp: Date.now() }],
  })),

  appendToLastAI: (text) => set((state) => {
    const msgs = [...state.messages]
    const last = msgs[msgs.length - 1]
    if (last && last.role === 'assistant') {
      last.content += text
    } else {
      msgs.push({ id: crypto.randomUUID(), role: 'assistant', content: text, timestamp: Date.now() })
    }
    return { messages: msgs }
  }),

  setTyping: (v) => set({ isTyping: v }),

  clear: () => set({ messages: [], isTyping: false }),
}))
```

### src/App.tsx（主组件）
```typescript
import { useEffect, useRef, useState } from 'react'
import { useChatStore } from './stores/chatStore'
import { useWebSocket } from './hooks/useWebSocket'
import './App.css'

const API_BASE = import.meta.env.VITE_API_URL || ''
const WS_DOMAIN = window.location.host

function App() {
  const { messages, addMessage, appendToLastAI, setTyping, clear } = useChatStore()
  const { connect, sendMessage } = useWebSocket((msg) => {
    switch (msg.type) {
      case 'typing_indicator':
        setTyping(msg.is_typing ?? false)
        break
      case 'streaming_chunk':
        if (msg.delta && !msg.done) {
          appendToLastAI(msg.delta)
        }
        break
      case 'transfer_notice':
        addMessage({ role: 'system', content: '🔄 ' + (msg.text || '正在转接人工客服...') })
        break
      case 'error':
        addMessage({ role: 'system', content: '❌ ' + (msg.error_message || '发生错误') })
        setTyping(false)
        break
    }
  })

  const [input, setInput] = useState('')
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    connect(WS_DOMAIN)
  }, [connect])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = () => {
    if (!input.trim()) return
    addMessage({ role: 'user', content: input })
    sendMessage(input)
    setInput('')
  }

  return (
    <div className="chat-container">
      <header className="chat-header">
        <span>🤖 智能客服</span>
      </header>

      <div className="chat-messages">
        {messages.map((msg) => (
          <div key={msg.id} className={`message ${msg.role}`}>
            {msg.content}
          </div>
        ))}
        {messages.length === 0 && (
          <div className="message system">你好，我是智能客服助手 👋</div>
        )}
        <div ref={chatEndRef} />
      </div>

      <div className="chat-input">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
          placeholder="输入消息..."
        />
        <button onClick={handleSend} disabled={!input.trim()}>发送</button>
      </div>
    </div>
  )
}

export default App
```

### src/App.css
```css
* { margin: 0; padding: 0; box-sizing: border-box; }

.chat-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 800px;
  margin: 0 auto;
  background: #f5f5f5;
}

.chat-header {
  background: #07c160;
  color: white;
  padding: 16px;
  text-align: center;
  font-size: 18px;
  font-weight: 500;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.message {
  max-width: 80%;
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.5;
  word-break: break-word;
}

.message.user {
  align-self: flex-end;
  background: #07c160;
  color: white;
}

.message.assistant {
  align-self: flex-start;
  background: white;
  color: #333;
  box-shadow: 0 1px 2px rgba(0,0,0,0.1);
}

.message.system {
  align-self: center;
  background: #eee;
  color: #666;
  font-size: 12px;
  padding: 8px 12px;
}

.chat-input {
  display: flex;
  gap: 8px;
  padding: 12px;
  background: white;
  border-top: 1px solid #ddd;
}

.chat-input input {
  flex: 1;
  border: 1px solid #ddd;
  border-radius: 20px;
  padding: 10px 16px;
  font-size: 15px;
  outline: none;
}

.chat-input input:focus {
  border-color: #07c160;
}

.chat-input button {
  padding: 10px 20px;
  background: #07c160;
  color: white;
  border: none;
  border-radius: 20px;
  font-size: 15px;
  cursor: pointer;
}

.chat-input button:disabled {
  background: #ccc;
  cursor: not-allowed;
}
```

---

## 完整部署流程

```bash
# 1. 部署后端
sudo bash deploy.sh

# 2. 创建前端项目
npm create vite@latest enterprise-agent-web -- --template react-ts
cd enterprise-agent-web
npm install

# 3. 把上面的模板文件复制进去（替换 src/ 下的文件）

# 4. 构建前端
npm run build

# 5. 部署到 Vercel（方式一）
vercel --prod
# 或部署到本机（方式二）
cp -r dist/* /opt/enterprise-agent/static/
sudo systemctl reload nginx

# 6. 入库文档
sudo systemctl start enterprise-agent-ingest

# 7. 配置健康检查
echo '*/5 * * * * /opt/enterprise-agent/healthcheck.sh' | crontab -
```
