# =============================================================================
# Enterprise Agent - 生产单容器镜像（FastAPI + Ollama 同镜像，全内网离线运行）
#
# 2026-10-05 依据运行中镜像 enterprise-agent-app-ollama:latest（构建于 2026-09-21）
# 的 docker history 逐层重建。此前工作区根 Dockerfile 被替换成了 legacy 单阶段文件，
# 与 docker-compose.prod.yml 声明的 target: runtime-with-ollama 不匹配，
# compose build 会直接失败。legacy 单阶段文件仍可从 git 历史取出：
#   git show a07d7d2:Dockerfile
#
# Stage 说明（对应生产运维手册记载的四阶段结构，做了一处工程简化）：
#   ollama-src          直接以本机现行生产镜像为来源提取 ollama 二进制，
#                       替代从源码编译 ollama（Go + cmake，耗时长且强依赖外网），
#                       二进制与现网逐字节一致，零运行时行为漂移。
#   runtime-with-ollama python:3.10-slim（3.10.21 / Debian trixie，与原镜像同基）
#                       + torch CPU + 运行时依赖 + 应用代码/向量库/reranker 权重
#                       + ollama 二进制。compose 的 build.target 指向本阶段。
#
# 构建: docker compose -f deploy/prod/docker-compose.prod.yml \
#          --env-file deploy/prod/.env.production build app
# =============================================================================

# ---- Stage 1: ollama 二进制来源（复用现网镜像，避免源码编译） ----
FROM enterprise-agent-app-ollama:latest AS ollama-src

# ---- Stage 2: 运行时（应用 + ollama 单容器） ----
FROM python:3.10-slim AS runtime-with-ollama

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1

WORKDIR /app

# 非 root 用户（uid 与原镜像保持 10001，避免挂载卷属主错位）
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/logs \
    && chown appuser:appuser /app /app/logs

# ---- Python 依赖：torch CPU 走 pytorch 官方 CPU 源，其余走清华镜像 ----
COPY requirements-runtime.txt requirements.txt
RUN pip install --no-cache-dir "torch==2.14.0+cpu" \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -i "${PIP_INDEX_URL}" --trusted-host "${PIP_TRUSTED_HOST}" \
    && pip install --no-cache-dir -r requirements.txt \
        -i "${PIP_INDEX_URL}" --trusted-host "${PIP_TRUSTED_HOST}" \
        --prefer-binary \
    && find /usr/local/lib/python3.10/site-packages -name __pycache__ -type d -exec rm -rf {} + \
    && find /usr/local/lib/python3.10/site-packages -name "*.pyc" -delete \
    && rm -rf /tmp/*

# ---- 应用代码与知识库资产（统一 chown 到 appuser） ----
COPY --chown=appuser:appuser main.py .
COPY --chown=appuser:appuser src/ src/
COPY --chown=appuser:appuser scripts/ scripts/
COPY --chown=appuser:appuser data/docs/ data/docs/
# 预构建向量库：全新命名卷首次挂载时以此目录内容为种子；已存在的卷不受影响
COPY --chown=appuser:appuser chroma_data/ chroma_data/
# 本地 reranker 权重（bge-reranker-base，约 1.1GB，全内网离线口径）
COPY --chown=appuser:appuser models/bge-reranker-base /app/models/bge-reranker-base
COPY --chown=appuser:appuser static/ static/

# transformers / huggingface 强制离线，避免运行期尝试联网
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

USER appuser

EXPOSE 8000

# 镜像内健康检查沿用历史路径 /api/health；compose 已用 /api/v1/health 覆盖
HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

# 默认 CMD 只启动 uvicorn，不会拉起 ollama；生产部署由 scripts/start-app.sh 托管
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- 注入 ollama 二进制（自 ollama-src stage 拷贝，外部依赖仅 glibc/libgcc） ----
USER root
ENV OLLAMA_HOST=127.0.0.1:11434 \
    HOME=/home/appuser

COPY --from=ollama-src /usr/bin/ollama /usr/bin/ollama
COPY --from=ollama-src /usr/lib/ollama/llama-server /usr/lib/ollama/llama-server
COPY --from=ollama-src /usr/lib/ollama/llama-quantize /usr/lib/ollama/llama-quantize
COPY --from=ollama-src /usr/lib/ollama/*.so* /usr/lib/ollama/

RUN chmod +x /app/scripts/start-app.sh \
    && mkdir -p /home/appuser/.ollama \
    && chmod 755 /usr/bin/ollama /usr/lib/ollama/llama-server /usr/lib/ollama/llama-quantize \
    && chown -R appuser:appuser /home/appuser/.ollama

USER appuser
