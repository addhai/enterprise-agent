# ---------------------------------------------------------------------------
# Docker Hub Mirror (中国大陆加速)
# ---------------------------------------------------------------------------
# 注意：mirror.gcr.io 是 dockerhub 的一个镜像站，可以根据需要替换为：
#   - registry.cn-hangzhou.aliyuncs.com（阿里云个人镜像仓库）
#   - docker.m.daocloud.io（DaoCloud 镜像站）
#   - hub.rat.dev
#
# 如果本地拉取正常，注释掉 mirror 行即可
# ---------------------------------------------------------------------------

FROM python:3.11-slim-bookworm

WORKDIR /app

# ---- 依赖层 (利用 Docker 层缓存) ----
# 离线优先：若构建上下文含预下载的 Linux 轮子目录 wheels/（gitignore，仅本地/内网构建放置），
# 则完全离线安装；否则回退在线安装（CI / 有网环境）。两套环境都不破坏。
COPY requirements.txt .
COPY wheels/ /wheels/
RUN if [ -n "$(ls -A /wheels 2>/dev/null | grep -v -x '.gitkeep')" ]; then \
      pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt; \
    else \
      pip install --no-cache-dir -r requirements.txt; \
    fi

# ---- 代码层 ----
COPY src/ src/
COPY scripts/ scripts/

# ---- 运行时 ----
RUN mkdir -p /app/data /app/logs

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')" || exit 1

CMD ["uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
