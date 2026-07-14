"""
Agent Worker — RabbitMQ 消费者

消费 agent.inference.queue，执行 LangGraph 编排，将结果写入 Redis/DB。

职责:
  1. 消费 RabbitMQ 消息 (agent.inference.*)
  2. 执行 LangGraph 编排 (CustomerServiceAgent)
  3. 结果回写 Redis (供 api-service 轮询/回调) 或 WebSocket 推送
  4. DLQ 处理 (失败消息进入死信队列)

启动方式:
  python -m src.worker.consumer
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from typing import Any, Dict, Optional

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPConnectionError

logger = logging.getLogger(__name__)

# ---- 队列常量 ----
EXCHANGE = "agent.tasks"
QUEUE_INFERENCE = "agent.inference.queue"
QUEUE_DLQ = "agent.inference.dlq"
ROUTING_KEY = "agent.inference.*"


class AgentWorker:
    """LangGraph Agent 异步消费者"""

    def __init__(self, rabbitmq_url: str):
        self.rabbitmq_url = rabbitmq_url
        self._connection: Optional[pika.BlockingConnection] = None
        self._channel: Optional[BlockingChannel] = None
        self._running = False

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """建立 RabbitMQ 连接 + 声明拓扑"""
        params = pika.URLParameters(self.rabbitmq_url)
        params.heartbeat = 60
        params.blocked_connection_timeout = 30

        self._connection = pika.BlockingConnection(params)
        self._channel = self._connection.channel()

        # 声明交换机（与 definitions.json 保持一致）
        self._channel.exchange_declare(
            exchange=EXCHANGE, exchange_type="topic", durable=True
        )

        # 声明队列
        self._channel.queue_declare(queue=QUEUE_INFERENCE, durable=True)
        self._channel.queue_bind(
            queue=QUEUE_INFERENCE, exchange=EXCHANGE, routing_key=ROUTING_KEY
        )

        # 公平分发：每个消费者一次只取一条消息
        self._channel.basic_qos(prefetch_count=1)

        logger.info("Worker connected to RabbitMQ, listening on %s", QUEUE_INFERENCE)

    def disconnect(self) -> None:
        """断开连接"""
        self._running = False
        if self._channel and self._channel.is_open:
            self._channel.close()
        if self._connection and self._connection.is_open:
            self._connection.close()
        logger.info("Worker disconnected from RabbitMQ")

    # ------------------------------------------------------------------
    # 消息处理
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动消费者循环"""
        self.connect()
        self._running = True

        # 注册消费回调
        self._channel.basic_consume(
            queue=QUEUE_INFERENCE, on_message_callback=self._handle_message,
            auto_ack=False  # 手动 ACK：处理成功才确认
        )

        logger.info("Worker started, waiting for messages...")
        try:
            self._channel.start_consuming()
        except KeyboardInterrupt:
            logger.info("Worker stopped by user")
        except Exception as e:
            logger.error("Worker crashed: %s", e)
            raise
        finally:
            self.disconnect()

    def _handle_message(
        self,
        ch: BlockingChannel,
        method: pika.spec.Basic.Deliver,
        properties: pika.BasicProperties,
        body: bytes,
    ) -> None:
        """处理单条推理任务消息

        消息格式:
        {
            "task_id": "uuid",
            "user_id": "...",
            "tenant_id": "...",
            "session_id": "...",
            "message": "用户问题",
            "priority": 0,
            "max_turns": 5
        }
        """
        task_id = "unknown"
        try:
            task: Dict[str, Any] = json.loads(body)
            task_id = task.get("task_id", "unknown")

            logger.info(
                "Processing task %s (user=%s, priority=%d)",
                task_id, task.get("user_id"), task.get("priority", 0),
            )

            # ---- 执行 LangGraph 编排 ----
            result = self._process_task(task)

            # ---- ACK 消息 ----
            ch.basic_ack(delivery_tag=method.delivery_tag)
            logger.info("Task %s completed, intent=%s", task_id, result.get("intent"))

        except json.JSONDecodeError:
            logger.error("Invalid message body: %s", body[:200])
            # 格式错误直接拒绝（不重试）
            ch.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
        except Exception as e:
            logger.exception("Task %s failed: %s", task_id, e)
            # 重试或进入 DLQ（由消息 TTL + DLX 自动处理）
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def _process_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个推理任务 — 调用 LangGraph Workflow"""
        session_id = task.get("session_id", "")
        user_id = task.get("user_id", "anonymous")
        message = task.get("message", "")
        tenant_id = task.get("tenant_id", "")
        max_turns = task.get("max_turns", 5)

        # ---- 延迟导入避免启动时加载 LLM ----
        from langchain_core.messages import HumanMessage

        from src.api.dependencies import get_workflow
        from src.graph.state import AgentState

        app = get_workflow()

        state = AgentState(
            messages=[HumanMessage(content=message)],
            intent=None,
            retrieved_docs=[],
            needs_human=False,
            turn_count=0,
            final_response="",
            user_id=user_id,
            session_id=session_id,
            tenant_id=tenant_id,
            user_access_levels=task.get("user_access_levels", ["public", "internal", "confidential", "restricted"]),
            user_roles=task.get("user_roles", []),
            user_plan=task.get("user_plan", "free"),
            faq_match=None,
            effective_max_turns=max_turns,
            has_reflected=False,
            memory_context="",
            quality_score=None,
            access_filtered=0,
            needs_expert_delegation=False,
            expert_response=None,
        )

        result = app.invoke(state, config={"configurable": {"thread_id": session_id}})

        return {
            "session_id": session_id,
            "intent": result.get("intent"),
            "final_response": result.get("final_response", ""),
            "needs_human": result.get("needs_human", False),
            "quality_score": result.get("quality_score"),
        }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    # 从环境变量读取 RabbitMQ URL
    rabbitmq_url = __import__("os").environ.get(
        "RABBITMQ_URL", "amqp://agent:agent@localhost:5672"
    )

    worker = AgentWorker(rabbitmq_url=rabbitmq_url)

    # 注册信号处理，优雅退出
    signal.signal(signal.SIGINT, lambda s, f: worker.disconnect())
    signal.signal(signal.SIGTERM, lambda s, f: worker.disconnect())

    worker.start()


if __name__ == "__main__":
    main()
