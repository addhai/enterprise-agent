# =============================================================================
# Legacy Dockerfile — 保留用于快速启动单进程 (不推荐生产使用)
#
# 生产环境请使用:
#   docker/api/Dockerfile      — API Service
#   docker/worker/Dockerfile   — Agent Worker
#   docker/rag/Dockerfile      — RAG Service
#
# 开发热重载:
#   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
# =============================================================================

FROM python:3.11-slim-bookworm

WORKDIR /app

# ---- Dependencies ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Application ----
COPY src/ src/
COPY scripts/ scripts/

RUN mkdir -p /app/data /app/chroma_data /app/logs

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')" || exit 1

CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
