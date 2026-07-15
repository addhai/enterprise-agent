"""
性能诊断专家 Agent — 独立 A2A Agent

从客服 Agent 中拆分出的性能诊断专家，专注处理：
  1. 同步卡住/超时问题诊断
  2. API 延迟分析 (429/503/超时)
  3. 大文件传输性能瓶颈
  4. 数据库锁冲突排查

启动方式:
  python -m src.protocols.perf_agent           # 端口 9002
  python -m src.protocols.perf_agent --port 9102

A2A 协作流:
  客服 Agent ──delegate_to_expert()──→ 性能专家 Agent (本服务)
  客服 Agent 翻译专家结论为用户友好回复
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 性能诊断知识库（无外部依赖，可独立测试）
# ---------------------------------------------------------------------------

_PERF_KNOWLEDGE = {
    "sync_stuck": (
        "【同步卡住诊断】\n"
        "常见原因:\n"
        "1. 文件锁定 — 源文件被其他进程占用，CloudSync 无法读取\n"
        "2. 网络中断 — 传输过程中网络波动导致重试循环\n"
        "3. 数据库锁冲突 — 大批量同步时 DB 行锁阻塞\n"
        "4. 磁盘空间不足 — 临时目录或目标存储空间不够\n"
        "建议:\n"
        "→ 检查文件是否被其他程序锁定（lsof / handle.exe）\n"
        "→ 查看同步日志中的重试次数和错误码\n"
        "→ 对于 >100GB 文件建议分块上传（每块 ≤50GB）\n"
        "→ 检查数据库连接池状态和锁等待队列"
    ),
    "api_latency": (
        "【API 延迟分析】\n"
        "常见原因:\n"
        "1. 限流 (429) — 超出 API 调用频率限制，建议实施指数退避重试\n"
        "2. 服务不可用 (503) — 后端服务过载，检查服务健康状态\n"
        "3. 超时 — 请求处理时间超过 30s 超时阈值\n"
        "4. CORS 预检慢 — OPTIONS 请求未缓存导致额外往返\n"
        "建议:\n"
        "→ 实施 429 自动重试（指数退避: 1s → 2s → 4s → 8s）\n"
        "→ 启用 API 响应缓存减少重复请求\n"
        "→ 检查 CDN 配置减少 CORS 预检频率\n"
        "→ 监控 P95/P99 延迟指标定位慢请求"
    ),
    "large_file": (
        "【大文件传输优化】\n"
        "瓶颈分析:\n"
        "1. 单文件过大 — >100GB 文件传输失败率高，建议分块\n"
        "2. 内存不足 — 全文件加载导致 OOM\n"
        "3. 网络带宽 — 长连接超时或带宽打满\n"
        "建议:\n"
        "→ 将大文件拆分为 ≤50GB 的分块分别上传\n"
        "→ 启用服务端分片上传（multipart upload）\n"
        "→ 使用断点续传避免网络中断后从头开始\n"
        "→ 压缩传输（gzip）减少网络带宽占用"
    ),
    "db_lock": (
        "【数据库锁冲突排查】\n"
        "常见场景:\n"
        "1. 行锁等待 — 大批量同步时多线程争抢同一行\n"
        "2. 死锁 — 两个事务互相等待对方释放锁\n"
        "3. 连接池耗尽 — 并发同步任务占满连接池\n"
        "建议:\n"
        "→ 检查 pg_locks / innodb_lock_waits 视图定位阻塞源\n"
        "→ 降低同步并发度（建议 ≤4 并发）\n"
        "→ 使用乐观锁替代悲观锁减少锁持有时间\n"
        "→ 配置连接池上限和等待超时（建议 max_connections=50）"
    ),
}


def _diagnose(query: str) -> str:
    """基于关键词匹配的性能诊断（无外部依赖）"""
    q = query.lower()

    if any(kw in q for kw in ["stuck", "stuck at", "卡住", "不完成", "processing for"]):
        return _PERF_KNOWLEDGE["sync_stuck"]
    if any(kw in q for kw in ["429", "503", "latency", "slow api", "rate limit", "延迟", "限流"]):
        return _PERF_KNOWLEDGE["api_latency"]
    if any(kw in q for kw in ["large file", "big file", "500gb", "大文件", "超大"]):
        return _PERF_KNOWLEDGE["large_file"]
    if any(kw in q for kw in ["lock", "deadlock", "db timeout", "锁", "死锁", "数据库"]):
        return _PERF_KNOWLEDGE["db_lock"]

    return (
        "【性能诊断】未匹配到特定场景，通用建议:\n"
        "1. 检查系统资源（CPU/内存/磁盘/网络）\n"
        "2. 查看日志中的 ERROR/WARN 级别条目\n"
        "3. 确认是否为偶发或持续性问题\n"
        "4. 提供具体的错误码和复现步骤以便进一步分析"
    )


# ---------------------------------------------------------------------------
# Agent Card 定义（延迟加载 a2a-sdk）
# ---------------------------------------------------------------------------

PERF_AGENT_CARD = None
PERF_AGENT_SKILLS = [
    {
        "id": "sync_stuck_diagnosis",
        "name": "Sync Stuck Diagnosis",
        "description": "诊断文件同步卡住、长时间处理不完成的问题",
        "tags": ["performance", "sync", "stuck", "timeout"],
        "examples": [
            "Sync is stuck at processing for 30 minutes",
            "My sync has been running for 7 hours on a 500GB file",
        ],
    },
    {
        "id": "api_latency_analysis",
        "name": "API Latency Analysis",
        "description": "分析 API 响应慢、429 限流、503 服务不可用等性能问题",
        "tags": ["performance", "api", "latency", "429", "503"],
        "examples": [
            "API responses are very slow today",
            "Getting 429 rate limit errors frequently",
        ],
    },
    {
        "id": "large_file_transfer",
        "name": "Large File Transfer Analysis",
        "description": "大文件传输性能瓶颈分析，包括分块、压缩、网络优化建议",
        "tags": ["performance", "large-file", "transfer", "optimization"],
        "examples": [
            "Uploading a 500GB file takes too long",
            "Large file sync keeps failing with timeout",
        ],
    },
    {
        "id": "db_lock_diagnosis",
        "name": "Database Lock Diagnosis",
        "description": "数据库锁冲突、死锁、连接池耗尽等底层性能问题排查",
        "tags": ["performance", "database", "lock", "deadlock"],
        "examples": [
            "Database operations are timing out",
            "Getting deadlock errors during bulk sync",
        ],
    },
]


def _build_perf_agent_card():
    """延迟构建 a2a AgentCard 对象"""
    global PERF_AGENT_CARD
    if PERF_AGENT_CARD is not None:
        return PERF_AGENT_CARD

    from a2a.types import AgentCard, AgentCapabilities, AgentSkill

    PERF_AGENT_CARD = AgentCard(
        name="Performance Diagnosis Expert Agent",
        description=(
            "CloudSync 性能诊断专家 Agent。"
            "专精文件同步性能问题、API 延迟分析、数据库锁冲突排查、大文件传输瓶颈。"
            "接收来自客服 Agent 的 A2A 委托请求。"
        ),
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text", "text/plain"],
        default_output_modes=["text", "text/plain"],
        skills=[
            AgentSkill(
                id=s["id"],
                name=s["name"],
                description=s["description"],
                tags=s["tags"],
                examples=s["examples"],
            )
            for s in PERF_AGENT_SKILLS
        ],
    )
    return PERF_AGENT_CARD


# ---------------------------------------------------------------------------
# A2A Server（延迟加载 a2a-sdk）
# ---------------------------------------------------------------------------


def _make_text_message(text: str, context_id: str, task_id: str):
    """Create a Message with a text Part (a2a-sdk 1.1.0 compatible)"""
    from uuid import uuid4
    from a2a.types import Message, Part, Role
    return Message(
        message_id=str(uuid4()),
        role=Role.ROLE_AGENT,
        context_id=context_id,
        task_id=task_id,
        parts=[Part(text=text)],
    )


class PerfExpertExecutor:
    """性能诊断专家 Agent 的 A2A 执行器"""

    async def execute(
        self, context, event_queue
    ) -> None:
        """接收 A2A 委托请求，执行性能诊断"""
        query = context.get_user_input()

        if not query:
            await event_queue.enqueue_event(
                _make_text_message(
                    "请提供需要诊断的性能问题描述。",
                    context.context_id,
                    context.task_id,
                )
            )
            return

        logger.info("Perf expert received query: %s", query[:200])
        diagnosis = _diagnose(query)

        await event_queue.enqueue_event(
            _make_text_message(diagnosis, context.context_id, context.task_id)
        )

    async def cancel(
        self, context, event_queue
    ) -> None:
        pass


def build_perf_agent_server():
    """构建性能诊断专家 Agent 的 A2A Server"""
    from fastapi import FastAPI
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.server.routes import add_a2a_routes_to_fastapi
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.routes.rest_routes import create_rest_routes

    card = _build_perf_agent_card()

    app = FastAPI(
        title="CloudSync Performance Expert A2A Agent",
        description="A2A-compatible performance diagnosis expert agent",
        version="1.0.0",
    )

    handler = DefaultRequestHandler(
        agent_executor=PerfExpertExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(
            agent_card=card,
            card_url="/.well-known/agent.json",
        ),
        jsonrpc_routes=create_jsonrpc_routes(
            request_handler=handler,
            rpc_url="/",
        ),
        rest_routes=create_rest_routes(
            request_handler=handler,
            path_prefix="/v1",
        ),
    )

    return app


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------


async def main():
    """启动性能诊断专家 Agent: python -m src.protocols.perf_agent"""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Performance Expert A2A Agent")
    parser.add_argument("--port", type=int, default=9002)
    args = parser.parse_args()

    app = build_perf_agent_server()

    logger.info("Performance Expert Agent starting on http://localhost:%s", args.port)
    logger.info("Agent Card: http://localhost:%s/.well-known/agent.json", args.port)

    config = uvicorn.Config(app, host="0.0.0.0", port=args.port, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


if __name__ == "__main__":
    asyncio.run(main())
