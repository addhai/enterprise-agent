# =============================================================================
# Enterprise Agent - P2-4 部署 Dockerfile
#
# 单镜像包含完整应用：FastAPI + LangGraph + RAG(Chroma) + 知识库
# 支持挂载本地知识库目录、环境变量分离配置(.env)
#
# 构建：
#   docker build -t enterprise-agent:latest -f deploy/p2/Dockerfile .
#
# 运行：
#   docker run -d -p 8000:8000 \
#     --env-file deploy/p2/.env.p2 \
#     -v $(pwd)/data/docs:/app/data/docs:ro \
#     -v $(pwd)/chroma_data:/app/chroma_data \
#     enterprise-agent:latest
#
# 多阶段构建：
#   stage 1 (builder)  安装依赖到独立 venv
#   stage 2 (runtime)   仅拷贝 venv + 应用代码，镜像更小
# =============================================================================

# ---- Stage 1: Builder ----
FROM python:3.10-slim AS builder

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# 安装编译依赖（psycopg2-binary 免编译，但部分 transitive 仍需 gcc）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 装到独立 prefix，方便 stage 2 整体拷贝
RUN pip install --no-cache-dir --prefix=/install \
    -r requirements.txt \
    -i "${PIP_INDEX_URL}" --trusted-host "${PIP_TRUSTED_HOST}" \
    --prefer-binary

# ---- Stage 2: Runtime ----
FROM python:3.10-slim AS runtime

LABEL maintainer="addhai"
LABEL description="Enterprise AI Customer Service Agent - FastAPI + LangGraph + RAG"
LABEL version="2.0.0"

# 运行时环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    PATH="/app/venv/bin:$PATH"

WORKDIR /app

# 从 builder 拷贝依赖（venv 独立 prefix，无系统污染）
COPY --from=builder /install /app/venv

# 应用代码
COPY src/ src/
COPY main.py .
COPY scripts/ scripts/

# 知识库文档（默认内置；运行时可被 volume 覆盖）
COPY data/docs/ data/docs/

# 预构建向量库（可被 volume 覆盖以使用不同库）
# 如果没有 chroma_data 目录，容器启动时会自动创建空库
# 离线部署时建议 COPY chroma_data/ chroma_data/
# 在线部署时建议 -v ./chroma_data:/app/chroma_data 挂载持久化

# 日志目录 + 非 root 用户
RUN mkdir -p /app/logs /app/chroma_data && \
    useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# 健康检查（容器内自检，不依赖 curl/wget）
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=5)" \
    || exit 1

# 启动命令（可被 docker-compose command 覆盖）
# 入口 src/api/server.py 是完整应用（REST + WS + 管理后台）
CMD ["python", "-m", "uvicorn", "src.api.server:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
