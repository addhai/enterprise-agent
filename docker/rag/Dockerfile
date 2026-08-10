FROM python:3.11-slim-bookworm

WORKDIR /app

# ---- 依赖层 ----
# 离线优先（同 api Dockerfile）：本地有 wheels/ 则离线装，否则在线装
COPY requirements.txt .
COPY wheels/ /wheels/
RUN if [ -n "$(ls -A /wheels 2>/dev/null | grep -v -x '.gitkeep')" ]; then \
      pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt && \
      pip install --no-cache-dir --no-index --find-links /wheels pymilvus minio pika; \
    else \
      pip install --no-cache-dir -r requirements.txt && \
      pip install --no-cache-dir pymilvus minio pika; \
    fi

# ---- 代码层 (只复制 RAG 需要的) ----
COPY src/rag/ src/rag/
COPY src/config.py src/config.py

# ---- 运行时 ----
RUN mkdir -p /app/data /app/logs /app/chroma_data

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')" || exit 1

CMD ["uvicorn", "src.rag.server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
