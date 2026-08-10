FROM python:3.11-slim-bookworm

WORKDIR /app

# ---- 依赖层 ----
# 离线优先（同 api Dockerfile）：本地有 wheels/ 则离线装，否则在线装
COPY requirements.txt .
COPY wheels/ /wheels/
RUN if [ -n "$(ls -A /wheels 2>/dev/null | grep -v -x '.gitkeep')" ]; then \
      pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt && \
      pip install --no-cache-dir --no-index --find-links /wheels pika; \
    else \
      pip install --no-cache-dir -r requirements.txt && \
      pip install --no-cache-dir pika; \
    fi

# ---- 代码层 ----
COPY src/ src/
COPY scripts/ scripts/

# ---- 运行时 ----
RUN mkdir -p /app/data /app/logs

# Worker 不暴露 HTTP 端口，只消费 MQ
CMD ["python", "-m", "src.worker.consumer"]
