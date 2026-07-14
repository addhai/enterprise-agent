-- =============================================================================
-- PostgreSQL Schema — Enterprise Agent 智能客服
-- Phase 1: 租户隔离 + 对话记录 + 用户画像 + 审计日志
-- =============================================================================
-- 设计原则:
--   1. tenant_id 作为每张逻辑表的隔离前缀
--   2. 所有主键使用 UUID 而非自增 ID（分布式友好）
--   3. created_at / updated_at 作为每张表的审计列
--   4. JSONB 存半结构化数据（用户画像、对话元数据）
--   5. 不启用 RLS（应用层做租户过滤，避免 PG 性能开销）
-- =============================================================================

-- 启用必要扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";          -- 模糊搜索索引

-- =========================================================================
-- 1. 租户 (Tenants)
-- =========================================================================
CREATE TABLE IF NOT EXISTS tenants (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(200)  NOT NULL,                    -- 租户名称
    slug            VARCHAR(100)  NOT NULL UNIQUE,             -- URL-friendly 唯一标识
    plan            VARCHAR(50)   NOT NULL DEFAULT 'free',     -- free / pro / enterprise
    status          VARCHAR(20)   NOT NULL DEFAULT 'active',   -- active / suspended / deleted
    settings        JSONB         NOT NULL DEFAULT '{}',       -- 租户级配置 (知识库配额、API 限流等)
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- 默认租户 (开发/单租户模式)
INSERT INTO tenants (id, name, slug, plan) VALUES
    ('00000000-0000-0000-0000-000000000001', 'Default', 'default', 'enterprise')
ON CONFLICT (slug) DO NOTHING;

-- =========================================================================
-- 2. 用户 (Users) — 租户下的用户账号
-- =========================================================================
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_id     VARCHAR(500),                               -- 外部系统用户 ID（微信 OpenID / Chatwoot ID）
    name            VARCHAR(200),
    email           VARCHAR(320),
    plan            VARCHAR(50)   NOT NULL DEFAULT 'free',      -- 用户个人订阅计划
    roles           TEXT[]        NOT NULL DEFAULT '{}',        -- {admin, agent, user}
    access_levels   TEXT[]        NOT NULL DEFAULT '{public}',  -- {public, internal, confidential, restricted}
    profile         JSONB         NOT NULL DEFAULT '{}',        -- 用户画像 (偏好/技术栈/历史摘要)
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    UNIQUE (tenant_id, external_id)
);

CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_users_external ON users(tenant_id, external_id);

-- 默认匿名用户
INSERT INTO users (id, tenant_id, name, external_id) VALUES
    ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'Anonymous', 'anonymous')
ON CONFLICT (tenant_id, external_id) DO NOTHING;

-- =========================================================================
-- 3. 知识库 (Knowledge Bases) — 租户下的知识库
-- =========================================================================
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name            VARCHAR(200)  NOT NULL,
    description     TEXT,
    doc_count       INTEGER       NOT NULL DEFAULT 0,           -- 文档数量 (冗余计数器)
    chunk_count     INTEGER       NOT NULL DEFAULT 0,           -- 切片总数
    status          VARCHAR(20)   NOT NULL DEFAULT 'active',    -- active / indexing / archived
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_kb_tenant ON knowledge_bases(tenant_id);

-- =========================================================================
-- 4. 对话会话 (Conversations) — 一次完整的用户对话
-- =========================================================================
CREATE TABLE IF NOT EXISTS conversations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id      VARCHAR(100)  NOT NULL,                     -- WebSocket/FastAPI 会话标识符
    channel         VARCHAR(50)   NOT NULL DEFAULT 'web',       -- web / wechat / phone / chatwoot
    status          VARCHAR(20)   NOT NULL DEFAULT 'active',    -- active / closed / escalated
    metadata        JSONB         NOT NULL DEFAULT '{}',        -- {ip, user_agent, language, ...}
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    UNIQUE (tenant_id, session_id)
);

CREATE INDEX idx_conv_tenant ON conversations(tenant_id);
CREATE INDEX idx_conv_user ON conversations(tenant_id, user_id);
CREATE INDEX idx_conv_session ON conversations(tenant_id, session_id);
CREATE INDEX idx_conv_status ON conversations(tenant_id, status);
CREATE INDEX idx_conv_created ON conversations(tenant_id, created_at DESC);

-- =========================================================================
-- 5. 消息 (Messages) — 对话中的每条消息
-- =========================================================================
CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id UUID          NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20)   NOT NULL,                     -- user / assistant / system / tool
    content         TEXT          NOT NULL,
    intent          VARCHAR(50),                                -- faq / technical / human / clarification
    metadata        JSONB         NOT NULL DEFAULT '{}',        -- {tool_calls, token_count, latency_ms, ...}
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_msg_conv ON messages(tenant_id, conversation_id);
CREATE INDEX idx_msg_created ON messages(conversation_id, created_at);

-- =========================================================================
-- 6. 长期记忆 (Long-Term Memories) — 用户级别的持久化记忆条目
-- =========================================================================
CREATE TABLE IF NOT EXISTS long_term_memories (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic           VARCHAR(200)  NOT NULL,                     -- api_version / sdk_config / error_pattern / ...
    content         TEXT          NOT NULL,
    importance      REAL          NOT NULL DEFAULT 0.0,         -- 0.0 ~ 1.0 重要度评分
    metadata        JSONB         NOT NULL DEFAULT '{}',
    expired_at      TIMESTAMPTZ,                                -- 过期时间 (NULL = 永不过期)
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ltm_user ON long_term_memories(tenant_id, user_id);
CREATE INDEX idx_ltm_topic ON long_term_memories(tenant_id, user_id, topic);
CREATE INDEX idx_ltm_importance ON long_term_memories(tenant_id, user_id, importance DESC);

-- =========================================================================
-- 7. 评估记录 (Quality Evaluations) — LLM-as-Judge 评分记录
-- =========================================================================
CREATE TABLE IF NOT EXISTS quality_evaluations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    conversation_id UUID          REFERENCES conversations(id) ON DELETE SET NULL,
    score_overall   REAL          NOT NULL,                     -- 0.0 ~ 5.0
    score_accuracy  REAL,
    score_completeness REAL,
    score_safety    REAL,
    score_helpfulness REAL,
    flags           TEXT[]        NOT NULL DEFAULT '{}',        -- {hallucination, unsafe, incomplete}
    needs_review    BOOLEAN       NOT NULL DEFAULT FALSE,
    evaluator       VARCHAR(50)   NOT NULL DEFAULT 'llm-judge', -- llm-judge / human / automated
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_eval_tenant ON quality_evaluations(tenant_id);
CREATE INDEX idx_eval_conv ON quality_evaluations(tenant_id, conversation_id);

-- =========================================================================
-- 8. 审计日志 (Audit Logs) — 安全审计 + 合规追踪
-- =========================================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         UUID          REFERENCES users(id) ON DELETE SET NULL,
    action          VARCHAR(100)  NOT NULL,                     -- chat / retrieve / escalate / admin_login / ...
    resource_type   VARCHAR(50),                                -- conversation / knowledge_base / user / tenant
    resource_id     UUID,
    ip_address      INET,
    user_agent      TEXT,
    details         JSONB         NOT NULL DEFAULT '{}',        -- 操作详情
    severity        VARCHAR(20)   NOT NULL DEFAULT 'info',      -- info / warning / critical
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_tenant ON audit_logs(tenant_id);
CREATE INDEX idx_audit_action ON audit_logs(tenant_id, action);
CREATE INDEX idx_audit_created ON audit_logs(tenant_id, created_at DESC);
CREATE INDEX idx_audit_severity ON audit_logs(tenant_id, severity, created_at DESC);

-- =========================================================================
-- 9. 限流记录 (Rate Limiting) — 可选的 PG 限流方案 (Redis 优先)
-- =========================================================================
CREATE TABLE IF NOT EXISTS rate_limits (
    tenant_id       UUID          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint        VARCHAR(200)  NOT NULL,                     -- /api/v1/chat
    window_start    TIMESTAMPTZ   NOT NULL,
    request_count   INTEGER       NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, user_id, endpoint, window_start)
);

-- =========================================================================
-- 触发 updated_at 自动更新
-- =========================================================================
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 为所有含 updated_at 的表创建触发器
CREATE TRIGGER trg_tenants_updated
    BEFORE UPDATE ON tenants FOR EACH ROW EXECUTE FUNCTION update_modified_column();

CREATE TRIGGER trg_users_updated
    BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_modified_column();

CREATE TRIGGER trg_knowledge_bases_updated
    BEFORE UPDATE ON knowledge_bases FOR EACH ROW EXECUTE FUNCTION update_modified_column();

CREATE TRIGGER trg_conversations_updated
    BEFORE UPDATE ON conversations FOR EACH ROW EXECUTE FUNCTION update_modified_column();
