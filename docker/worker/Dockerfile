FROM python:3.11-slim-bookworm

WORKDIR /app

# ---- 依赖层 ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir pika    # RabbitMQ 客户端 (新增依赖)

# ---- 代码层 ----
COPY src/ src/
COPY scripts/ scripts/

# ---- 运行时 ----
RUN mkdir -p /app/data /app/logs

# Worker 不暴露 HTTP 端口，只消费 MQ
CMD ["python", "-m", "src.worker.consumer"]
