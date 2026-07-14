FROM python:3.11-slim-bookworm

WORKDIR /app

# ---- 依赖层 ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir pymilvus minio pika    # 新增: Milvus, MinIO, RabbitMQ 客户端

# ---- 代码层 (只复制 RAG 需要的) ----
COPY src/rag/ src/rag/
COPY src/config.py src/config.py

# ---- 运行时 ----
RUN mkdir -p /app/data /app/logs /app/chroma_data

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')" || exit 1

CMD ["uvicorn", "src.rag.server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
