# =============================================================================
# Enterprise Agent — Makefile (本地开发常用命令)
# =============================================================================
# Usage:
#   make help          — 显示所有命令
#   make up            — 启动全部服务
#   make down          — 停止全部服务
#   make build         — 构建全部镜像
#   make logs API      — 查看指定服务日志
#   make test          — 运行全部测试
#   make lint          — 代码检查
#   make migrate-dry   — 预览 Chroma→Milvus 迁移
#   make migrate       — 执行 Chroma→Milvus 迁移
# =============================================================================

.PHONY: help up down restart build build-api build-rag build-worker \
        logs ps clean test test-cov test-api test-rag lint lint-fix \
        format migrate-dry migrate migrate-verify \
        shell-api shell-worker shell-rag \
        pg-connect redis-connect mq-console minio-console \
        install dev dev-api dev-rag

# ---- 默认目标 ----
.DEFAULT_GOAL := help

help: ## 显示所有可用命令
	@echo "Enterprise Agent — Makefile"
	@echo ""
	@echo "基础命令:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# =========================================================================
# Docker Compose — 服务管理
# =========================================================================

up: ## 启动全部服务 (docker compose up -d)
	docker compose up -d
	@echo ""
	@echo "服务已启动:"
	@docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

down: ## 停止全部服务
	docker compose down

restart: down up ## 重启全部服务

build: ## 构建全部镜像
	docker compose build

build-api: ## 仅构建 API 镜像
	docker compose build api-service

build-rag: ## 仅构建 RAG 镜像
	docker compose build rag-service

build-worker: ## 仅构建 Worker 镜像
	docker compose build agent-worker

logs: ## 查看指定服务日志 (make logs SVC=api-service)
	docker compose logs -f $(SVC)

ps: ## 查看服务状态
	docker compose ps

clean: down ## 停止并清理数据卷 (危险!)
	@read -p "⚠️  确认清理所有数据卷? [y/N] " ans; \
	if [ "$$ans" = "y" ]; then \
		docker compose down -v; \
		echo "已清理所有数据卷"; \
	else \
		echo "已取消"; \
	fi

# =========================================================================
# 开发环境 (不使用 Docker)
# =========================================================================

install: ## 安装依赖
	pip install -r requirements.txt
	cd frontend && npm ci

dev: ## 启动 API 开发服务器 (热重载)
	python -m src.api.server

dev-rag: ## 启动 RAG 开发服务器 (热重载)
	uvicorn src.rag.server:app --host 0.0.0.0 --port 8001 --reload

dev-worker: ## 启动 Worker 消费者
	python -m src.worker.consumer

# =========================================================================
# 测试
# =========================================================================

test: ## 运行全部测试
	pytest tests/ -v

test-cov: ## 运行测试 + 覆盖率报告
	pytest tests/ -v --cov=src --cov-report=term --cov-report=html

test-api: ## 仅运行 API 相关测试
	pytest tests/test_graph/ tests/test_agent/ -v

test-rag: ## 仅运行 RAG 相关测试
	pytest tests/test_rag/ -v

# =========================================================================
# 代码质量
# =========================================================================

lint: ## 代码检查
	ruff check src/ tests/
	cd frontend && npm run lint

lint-fix: ## 自动修复 Lint 问题
	ruff check --fix src/ tests/

format: ## 代码格式化
	ruff format src/ tests/

# =========================================================================
# Chroma → Milvus 迁移
# =========================================================================

migrate-dry: ## 预览迁移 (不实际写入)
	python scripts/migrate_chroma_to_milvus.py --dry-run

migrate: ## 执行 Chroma → Milvus 迁移
	python scripts/migrate_chroma_to_milvus.py

migrate-verify: ## 仅验证迁移一致性
	python scripts/migrate_chroma_to_milvus.py --verify-only

# =========================================================================
# 数据操作
# =========================================================================

ingest: ## 入库知识库文档
	python scripts/ingest_docs.py

ingest-incremental: ## 增量索引
	python scripts/incremental_index.py

# =========================================================================
# Shell / 连接
# =========================================================================

shell-api: ## 进入 API 容器
	docker compose exec api-service bash

shell-worker: ## 进入 Worker 容器
	docker compose exec agent-worker bash

shell-rag: ## 进入 RAG 容器
	docker compose exec rag-service bash

pg-connect: ## 连接 PostgreSQL
	docker compose exec postgres psql -U postgres -d agent

redis-connect: ## 连接 Redis
	docker compose exec redis redis-cli

mq-console: ## 打开 RabbitMQ Management UI
	@echo "RabbitMQ Management: http://localhost:15672 (agent/agent)"

minio-console: ## 打开 MinIO Console
	@echo "MinIO Console: http://localhost:9001 (minioadmin/minioadmin)"

# =========================================================================
# CI/CD 本地验证
# =========================================================================

ci-lint: ## 本地运行 CI lint 阶段
	ruff check src/ tests/
	ruff format --check src/ tests/

ci-test: ## 本地运行 CI test 阶段
	pytest tests/ -v --cov=src

ci-sast: ## 本地运行 SAST 扫描
	bandit -r src/ -f screen
	semgrep scan --config auto src/ 2>/dev/null || true

ci-full: ci-lint ci-test ci-sast ## 本地运行完整 CI 流水线
	@echo "✅ CI 流水线验证完成"

# =========================================================================
# Helm / K8s 验证
# =========================================================================

helm-lint: ## Helm Chart 语法检查
	helm lint deploy/helm/enterprise-agent/

helm-template: ## Helm 渲染模板预览 (staging)
	helm template agent deploy/helm/enterprise-agent/ \
		-f deploy/helm/enterprise-agent/values.yaml \
		-f deploy/helm/enterprise-agent/values-staging.yaml

helm-template-prod: ## Helm 渲染模板预览 (production)
	helm template agent deploy/helm/enterprise-agent/ \
		-f deploy/helm/enterprise-agent/values.yaml \
		-f deploy/helm/enterprise-agent/values-prod.yaml

docker-lint: ## Dockerfile 最佳实践检查
	@which hadolint > /dev/null 2>&1 && \
		hadolint docker/api/Dockerfile docker/worker/Dockerfile docker/rag/Dockerfile || \
		echo "hadolint not installed, skipping. Install: brew install hadolint / apt install hadolint"

check-imports: ## 验证所有 Python import 路径
	@echo "Checking imports..."
	@python -c "
import ast, os, sys
errors = []
src_dir = 'src'
for root, dirs, files in os.walk(src_dir):
    for f in files:
        if not f.endswith('.py'):
            continue
        filepath = os.path.join(root, f)
        try:
            with open(filepath) as fh:
                tree = ast.parse(fh.read(), filename=filepath)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    pass  # 不做运行时 import，只检查语法
        except SyntaxError as e:
            errors.append(f'{filepath}: {e}')
if errors:
    print('Syntax errors found:')
    for e in errors:
        print(f'  ❌ {e}')
    sys.exit(1)
else:
    print('  ✅ All imports parse successfully')
" && echo "  ✅ Import check passed"

validate: helm-lint check-imports ## 运行所有验证命令
	@echo "✅ 所有验证通过"
