import { useCallback, useEffect, useState } from 'react'
import { fetchJson, postJson, putJson } from './api'
import type { ChannelData } from './types'

export function ChannelsTab({ token }: { token: string }) {
  const [channels, setChannels] = useState<ChannelData[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedChannel, setExpandedChannel] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [saveMsg, setSaveMsg] = useState<{ channel: string; type: 'success' | 'error'; text: string } | null>(null)
  const [testMsg, setTestMsg] = useState<{ channel: string; type: 'success' | 'error'; text: string } | null>(null)

  const [chatwootForm, setChatwootForm] = useState({
    base_url: '',
    api_token: '',
    account_id: '1',
    inbox_id: '1',
    webhook_token: '',
    enabled: false,
  })
  const [feishuForm, setFeishuForm] = useState({
    app_id: '',
    app_secret: '',
    enabled: false,
  })

  const loadChannels = useCallback(() => {
    setLoading(true)
    fetchJson('/admin/channels', token)
      .then(data => {
        const list = (data.channels || data || []) as ChannelData[]
        setChannels(list)
        const cw = list.find(c => c.name === 'chatwoot')
        if (cw?.config) {
          const cfg = cw.config
          setChatwootForm(prev => ({
            ...prev,
            base_url: cfg.base_url || '',
            account_id: cfg.account_id || '1',
            inbox_id: cfg.inbox_id || '1',
            enabled: cw.enabled,
          }))
        }
        const fs = list.find(c => c.name === 'feishu')
        if (fs?.config) {
          const fcfg = fs.config
          setFeishuForm(prev => ({
            ...prev,
            app_id: fcfg.app_id || '',
            enabled: fs.enabled,
          }))
        }
      })
      .catch(() => {
        setChannels([
          { name: 'web', enabled: true, description: 'Web 端聊天窗口' },
          { name: 'feishu', enabled: false, description: '飞书渠道' },
          { name: 'chatwoot', enabled: false, description: 'Chatwoot 客服平台' },
        ])
      })
      .finally(() => setLoading(false))
  }, [token])

  useEffect(() => {
    loadChannels()
  }, [loadChannels])

  const handleSaveChatwoot = async () => {
    setSaving('chatwoot')
    setSaveMsg(null)
    try {
      const body: Record<string, any> = {
        base_url: chatwootForm.base_url,
        account_id: chatwootForm.account_id,
        inbox_id: chatwootForm.inbox_id,
        enabled: chatwootForm.enabled,
      }
      if (chatwootForm.api_token) body.api_token = chatwootForm.api_token
      if (chatwootForm.webhook_token) body.webhook_token = chatwootForm.webhook_token

      const data = await putJson('/admin/channels/chatwoot/config', token, body) as any
      setSaveMsg({ channel: 'chatwoot', type: 'success', text: '配置已保存' })
      setChannels(prev => prev.map(c => c.name === 'chatwoot' ? { ...c, enabled: data.enabled, config: data.config } : c))
    } catch (err) {
      setSaveMsg({ channel: 'chatwoot', type: 'error', text: err instanceof Error ? err.message : '保存失败' })
    } finally {
      setSaving(null)
      setTimeout(() => setSaveMsg(null), 3000)
    }
  }

  const handleTestChatwoot = async () => {
    setTesting('chatwoot')
    setTestMsg(null)
    try {
      const data = await postJson('/admin/channels/chatwoot/test', token, {}) as any
      if (data.success) {
        setTestMsg({ channel: 'chatwoot', type: 'success', text: data.message || '连接成功' })
      } else {
        setTestMsg({ channel: 'chatwoot', type: 'error', text: data.message || '连接失败' })
      }
    } catch (err) {
      setTestMsg({ channel: 'chatwoot', type: 'error', text: err instanceof Error ? err.message : '测试失败' })
    } finally {
      setTesting(null)
      setTimeout(() => setTestMsg(null), 5000)
    }
  }

  const handleSaveFeishu = async () => {
    setSaving('feishu')
    setSaveMsg(null)
    try {
      const body: Record<string, any> = {
        app_id: feishuForm.app_id,
        enabled: feishuForm.enabled,
      }
      if (feishuForm.app_secret) body.app_secret = feishuForm.app_secret

      const data = await putJson('/admin/channels/feishu/config', token, body) as any
      setSaveMsg({ channel: 'feishu', type: 'success', text: '配置已保存' })
      setChannels(prev => prev.map(c => c.name === 'feishu' ? { ...c, enabled: data.enabled, config: data.config } : c))
    } catch (err) {
      setSaveMsg({ channel: 'feishu', type: 'error', text: err instanceof Error ? err.message || '保存失败' : '保存失败' })
    } finally {
      setSaving(null)
      setTimeout(() => setSaveMsg(null), 3000)
    }
  }

  const handleTestFeishu = async () => {
    setTesting('feishu')
    setTestMsg(null)
    try {
      const data = await postJson('/admin/channels/feishu/test', token, {}) as any
      if (data.success) {
        setTestMsg({ channel: 'feishu', type: 'success', text: data.message || '连接成功' })
      } else {
        setTestMsg({ channel: 'feishu', type: 'error', text: data.message || '连接失败' })
      }
    } catch (err) {
      setTestMsg({ channel: 'feishu', type: 'error', text: err instanceof Error ? err.message : '测试失败' })
    } finally {
      setTesting(null)
      setTimeout(() => setTestMsg(null), 5000)
    }
  }

  const getChannelStatus = (name: string): boolean => {
    const ch = channels.find(c => c.name === name || c.name.includes(name) || name.includes(c.name))
    if (ch) return ch.enabled
    if (name === 'web' || name === 'Web 直连') return true
    return false
  }

  const channelConfigs = [
    {
      name: 'Web 直连',
      icon: '🌐',
      desc: '浏览器 WebSocket 直连',
      status: 'active',
      detail: (
        <div className="channel-detail-content">
          <div className="channel-detail-section">
            <div className="channel-detail-icon">✅</div>
            <div>
              <h5>已启用</h5>
              <p>Web 直连是内置功能，无需额外配置。用户访问网站即可直接使用智能客服。</p>
            </div>
          </div>
          <div className="channel-detail-info">
            <div className="info-item"><span className="info-label">连接方式</span><span className="info-value">WebSocket</span></div>
            <div className="info-item"><span className="info-label">状态</span><span className="info-value success">正常运行</span></div>
          </div>
        </div>
      ),
    },
    {
      name: '飞书',
      icon: '📘',
      desc: getChannelStatus('feishu') ? '飞书机器人已配置' : '需要配置飞书开放平台应用',
      status: getChannelStatus('feishu') ? 'active' : 'inactive',
      detail: (
        <div className="channel-detail-content">
          <div className="channel-detail-section">
            <div className="channel-detail-icon">{getChannelStatus('feishu') ? '✅' : '⚠️'}</div>
            <div>
              <h5>{getChannelStatus('feishu') ? '已启用' : '待配置'}</h5>
              <p>通过飞书开放平台创建企业自建应用，将智能客服接入飞书群聊或单聊。</p>
            </div>
          </div>
          <div className="channel-config-form">
            <h5>渠道配置</h5>
            <div className="form-row">
              <label className="form-label">启用飞书渠道</label>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={feishuForm.enabled}
                  onChange={(e) => setFeishuForm(prev => ({ ...prev, enabled: e.target.checked }))}
                  onClick={(e) => e.stopPropagation()}
                />
                <span className="toggle-slider"></span>
              </label>
            </div>
            <div className="form-row">
              <label className="form-label">App ID</label>
              <input
                type="text"
                className="form-input"
                value={feishuForm.app_id}
                onChange={(e) => setFeishuForm(prev => ({ ...prev, app_id: e.target.value }))}
                placeholder="cli_xxxxxxxxxxxxxx"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-row">
              <label className="form-label">App Secret</label>
              <input
                type="password"
                className="form-input"
                value={feishuForm.app_secret}
                onChange={(e) => setFeishuForm(prev => ({ ...prev, app_secret: e.target.value }))}
                placeholder={channels.find(c => c.name === 'feishu')?.config?.app_secret_configured ? '已配置，留空不修改' : '请输入 App Secret'}
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-actions">
              <button
                className="btn btn-secondary"
                onClick={(e) => { e.stopPropagation(); handleTestFeishu(); }}
                disabled={testing === 'feishu'}
              >
                {testing === 'feishu' ? '测试中...' : '测试连接'}
              </button>
              <button
                className="btn btn-primary"
                onClick={(e) => { e.stopPropagation(); handleSaveFeishu(); }}
                disabled={saving === 'feishu'}
              >
                {saving === 'feishu' ? '保存中...' : '保存配置'}
              </button>
            </div>
            {saveMsg?.channel === 'feishu' && (
              <div className={`form-message ${saveMsg.type}`} onClick={(e) => e.stopPropagation()}>
                {saveMsg.text}
              </div>
            )}
            {testMsg?.channel === 'feishu' && (
              <div className={`form-message ${testMsg.type}`} onClick={(e) => e.stopPropagation()}>
                {testMsg.text}
              </div>
            )}
          </div>
          <div className="channel-detail-steps">
            <h5>配置说明</h5>
            <div className="step-list">
              <div className="step-item">
                <div className="step-number">1</div>
                <div className="step-content">
                  <p className="step-title">创建飞书应用</p>
                  <p className="step-desc">前往 <a href="https://open.feishu.cn/" target="_blank" rel="noopener noreferrer">飞书开放平台</a>，创建企业自建应用</p>
                </div>
              </div>
              <div className="step-item">
                <div className="step-number">2</div>
                <div className="step-content">
                  <p className="step-title">获取凭证</p>
                  <p className="step-desc">在应用详情页获取 App ID 和 App Secret 并填入上方</p>
                </div>
              </div>
              <div className="step-item">
                <div className="step-number">3</div>
                <div className="step-content">
                  <p className="step-title">配置事件订阅</p>
                  <p className="step-desc">在飞书开放平台配置消息事件回调地址</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      ),
    },
    {
      name: 'Chatwoot',
      icon: '🪺',
      desc: getChannelStatus('chatwoot') ? 'Chatwoot 客服已接入' : '需要部署 Chatwoot 实例',
      status: getChannelStatus('chatwoot') ? 'active' : 'inactive',
      detail: (
        <div className="channel-detail-content">
          <div className="channel-detail-section">
            <div className="channel-detail-icon">{getChannelStatus('chatwoot') ? '✅' : '🔌'}</div>
            <div>
              <h5>{getChannelStatus('chatwoot') ? '已启用' : '待配置'}</h5>
              <p>Chatwoot 是开源客服系统，可通过 API 与本系统对接，实现多渠道统一管理。</p>
            </div>
          </div>
          <div className="channel-config-form">
            <h5>渠道配置</h5>
            <div className="form-row">
              <label className="form-label">启用 Chatwoot 渠道</label>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={chatwootForm.enabled}
                  onChange={(e) => setChatwootForm(prev => ({ ...prev, enabled: e.target.checked }))}
                  onClick={(e) => e.stopPropagation()}
                />
                <span className="toggle-slider"></span>
              </label>
            </div>
            <div className="form-row">
              <label className="form-label">Chatwoot Base URL</label>
              <input
                type="text"
                className="form-input"
                value={chatwootForm.base_url}
                onChange={(e) => setChatwootForm(prev => ({ ...prev, base_url: e.target.value }))}
                placeholder="https://app.chatwoot.com/api/v1"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-row">
              <label className="form-label">API Token</label>
              <input
                type="password"
                className="form-input"
                value={chatwootForm.api_token}
                onChange={(e) => setChatwootForm(prev => ({ ...prev, api_token: e.target.value }))}
                placeholder={channels.find(c => c.name === 'chatwoot')?.config?.api_token_configured ? '已配置，留空不修改' : '请输入 Agent Bot Token 或 User Token'}
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-row">
              <label className="form-label">Account ID</label>
              <input
                type="text"
                className="form-input"
                value={chatwootForm.account_id}
                onChange={(e) => setChatwootForm(prev => ({ ...prev, account_id: e.target.value }))}
                placeholder="1"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-row">
              <label className="form-label">Inbox ID</label>
              <input
                type="text"
                className="form-input"
                value={chatwootForm.inbox_id}
                onChange={(e) => setChatwootForm(prev => ({ ...prev, inbox_id: e.target.value }))}
                placeholder="1"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            <div className="form-row">
              <label className="form-label">Webhook Token</label>
              <input
                type="password"
                className="form-input"
                value={chatwootForm.webhook_token}
                onChange={(e) => setChatwootForm(prev => ({ ...prev, webhook_token: e.target.value }))}
                placeholder={channels.find(c => c.name === 'chatwoot')?.config?.webhook_token_configured ? '已配置，留空不修改' : '请输入 Webhook 验证 Token'}
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            {channels.find(c => c.name === 'chatwoot')?.config?.webhook_url && (
              <div className="form-row">
                <label className="form-label">Webhook 回调地址</label>
                <div className="form-input readonly" onClick={(e) => e.stopPropagation()}>
                  {window.location.origin}{channels.find(c => c.name === 'chatwoot')?.config?.webhook_url}
                </div>
              </div>
            )}
            <div className="form-actions">
              <button
                className="btn btn-secondary"
                onClick={(e) => { e.stopPropagation(); handleTestChatwoot(); }}
                disabled={testing === 'chatwoot'}
              >
                {testing === 'chatwoot' ? '测试中...' : '测试连接'}
              </button>
              <button
                className="btn btn-primary"
                onClick={(e) => { e.stopPropagation(); handleSaveChatwoot(); }}
                disabled={saving === 'chatwoot'}
              >
                {saving === 'chatwoot' ? '保存中...' : '保存配置'}
              </button>
            </div>
            {saveMsg?.channel === 'chatwoot' && (
              <div className={`form-message ${saveMsg.type}`} onClick={(e) => e.stopPropagation()}>
                {saveMsg.text}
              </div>
            )}
            {testMsg?.channel === 'chatwoot' && (
              <div className={`form-message ${testMsg.type}`} onClick={(e) => e.stopPropagation()}>
                {testMsg.text}
              </div>
            )}
          </div>
          <div className="channel-detail-steps">
            <h5>配置说明</h5>
            <div className="step-list">
              <div className="step-item">
                <div className="step-number">1</div>
                <div className="step-content">
                  <p className="step-title">部署 Chatwoot</p>
                  <p className="step-desc">支持 Docker / 云部署 / 源码部署多种方式</p>
                </div>
              </div>
              <div className="step-item">
                <div className="step-number">2</div>
                <div className="step-content">
                  <p className="step-title">创建 Agent Bot</p>
                  <p className="step-desc">在 Chatwoot 中创建新的 Inbox 和 Agent Bot，获取 Token 填入上方</p>
                </div>
              </div>
              <div className="step-item">
                <div className="step-number">3</div>
                <div className="step-content">
                  <p className="step-title">配置 Webhook</p>
                  <p className="step-desc">将上方 Webhook 回调地址配置到 Chatwoot 的 Webhook 设置中</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      ),
    },
  ]

  return (
    <div className="channel-grid">
      {loading && <div className="admin-loading">加载渠道状态中...</div>}
      {!loading && channelConfigs.map(ch => {
        const isExpanded = expandedChannel === ch.name
        const enabled = getChannelStatus(ch.name)
        return (
          <div
            key={ch.name}
            className={`channel-card expandable ${isExpanded ? 'expanded' : ''}`}
            onClick={() => setExpandedChannel(isExpanded ? null : ch.name)}
          >
            <div className="channel-card-header">
              <span className="channel-icon">{ch.icon}</span>
              <div className="channel-info">
                <h4>{ch.name}</h4>
                <p>{ch.desc}</p>
              </div>
              <span className={`channel-badge ${enabled ? 'active' : 'inactive'}`}>{enabled ? '已启用' : '未配置'}</span>
              <span className="channel-expand-icon">{isExpanded ? '▲' : '▼'}</span>
            </div>
            {isExpanded && <div className="channel-detail">{ch.detail}</div>}
          </div>
        )
      })}
    </div>
  )
}

// ============================================================
// Sessions
// ============================================================

