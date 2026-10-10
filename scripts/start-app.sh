#!/bin/sh
# =============================================================================
# 生产单容器启动脚本（runtime-with-ollama 镜像专用）
#
# 2026-10-05 从 docker-compose.prod.yml 的内联 command 外置。
# 背景：Docker Compose v5.5.1 对 $ 的插值转义语义变化（$$ 不再还原为 $），
# 含 shell 变量的内联启动命令无法可靠透传，故整体落入镜像脚本，
# compose 侧只保留无变量的脚本路径调用。
#
# 职责：
#   1) 挂接 WSL2 透传进来的 NVIDIA 驱动库目录，兜底软链 libcuda.so.1
#   2) 后台拉起 ollama serve 并做最长 180s 就绪探针
#   3) 前台 exec uvicorn，使其接管容器 1 号进程信号
# 镜像自身的 CMD（uvicorn）不会启动 ollama，生产部署必须走本脚本。
# =============================================================================
set -e

# ---- 1) WSL2 GPU 驱动挂接 ----
# WSL2 的 NVIDIA 驱动库以 /usr/lib/wsl/drivers/<版本>/ 形式挂入容器。
for d in /usr/lib/wsl/drivers/*/; do
  export LD_LIBRARY_PATH="${d}:/tmp:${LD_LIBRARY_PATH}"
done
# libcuda.so.1 通常只以 libcuda.so.1.1 形式存在，补一个固定名软链到 /tmp
# （/tmp 已在上面的 LD_LIBRARY_PATH 中）。非 WSL 环境下通配符不命中，忽略错误。
ln -sf /usr/lib/wsl/drivers/*/libcuda.so.1.1 /tmp/libcuda.so.1 2>/dev/null || true

# ---- 2) ollama 后台启动 + 就绪探针 ----
/usr/bin/ollama serve > /tmp/ollama.log 2>&1 &
sleep 5
timeout 180 sh -c 'until /usr/bin/ollama list > /dev/null 2>&1; do sleep 2; done'

echo "[start-app] ollama readiness probe finished, starting uvicorn"

# ---- 3) uvicorn 前台托管 ----
# WS 协议心跳 25s/60s（2026-10-09 由 300/300 收紧）。
# 病因：直答路径一次 LLM 调用静默 100-450s，期间无业务帧；300s 心跳等于
# 没有保活，Docker Desktop WSL2 端口转发会把静默连接静默回收，客户端收到
# ConnectionClosedError（no close frame）零帧断连，而服务端 LLM 实际 200
# 正常返回。A/B 两轮各随机命中 2/50，与单题静默时长无关（446s 不断、103s
# 断），符合中间层连接回收特征。协议层 ping/pong 每 25s 给链路续命；
# timeout 留 60s 防 CPU 推理满载时 pong 回复慢被反杀。
# 验证：收紧后跑 GF13/GF16/GP10/GS12 定向题集重复两轮零断连方可镜像固化。
exec uvicorn src.api.server:app \
  --host 0.0.0.0 --port 8000 \
  --ws-ping-interval 25 --ws-ping-timeout 60
