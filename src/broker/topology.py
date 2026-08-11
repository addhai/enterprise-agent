"""RabbitMQ 拓扑幂等声明。

对应原 deploy/rabbitmq/definitions.json 的设计意图，但改为代码侧声明，
避免 RabbitMQ 4.x load_definitions 的 vhost 导入顺序坑。

所有声明均为幂等（durable + 已存在则忽略），可安全地被 api-service / worker
在启动时重复调用。队列均带死信交换机(agent.dlx)与 TTL，符合生产级异步任务队列设计。
"""

from __future__ import annotations

from typing import Any, Dict

# ---- 名称常量（与 src/config.py / worker/consumer.py 保持一致）----
EXCHANGE_TASKS = "agent.tasks"
EXCHANGE_DLX = "agent.dlx"

QUEUE_INFERENCE = "agent.inference.queue"
QUEUE_INFERENCE_DLQ = "agent.inference.dlq"
QUEUE_MEMORY_PERSIST = "memory.persist.queue"
QUEUE_MEMORY_PERSIST_DLQ = "memory.persist.dlq"
QUEUE_RAG_INDEX = "rag.index.queue"
QUEUE_RAG_INDEX_DLQ = "rag.index.dlq"
QUEUE_NOTIFY_PUSH = "notify.push.queue"

VHOST = "/"  # RabbitMQ 内建默认 vhost

# 队列参数（死信 + TTL + 类型），与 definitions.json 对齐
_INFERENCE_ARGS: Dict[str, Any] = {
    "x-queue-type": "classic",
    "x-max-priority": 10,
    "x-message-ttl": 300000,
    "x-dead-letter-exchange": EXCHANGE_DLX,
    "x-dead-letter-routing-key": QUEUE_INFERENCE_DLQ,
}
_INFERENCE_DLQ_ARGS: Dict[str, Any] = {"x-message-ttl": 86400000}
_MEMORY_PERSIST_ARGS: Dict[str, Any] = {
    "x-queue-type": "classic",
    "x-message-ttl": 60000,
    "x-dead-letter-exchange": EXCHANGE_DLX,
    "x-dead-letter-routing-key": QUEUE_MEMORY_PERSIST_DLQ,
}
_MEMORY_PERSIST_DLQ_ARGS: Dict[str, Any] = {"x-message-ttl": 86400000}
_RAG_INDEX_ARGS: Dict[str, Any] = {
    "x-queue-type": "classic",
    "x-max-priority": 5,
    "x-message-ttl": 600000,
    "x-dead-letter-exchange": EXCHANGE_DLX,
    "x-dead-letter-routing-key": QUEUE_RAG_INDEX_DLQ,
}
_RAG_INDEX_DLQ_ARGS: Dict[str, Any] = {}
_NOTIFY_PUSH_ARGS: Dict[str, Any] = {
    "x-queue-type": "classic",
    "x-message-ttl": 300000,
}


def declare_topology(channel) -> None:
    """在给定 channel 上幂等声明完整拓扑（交换机 / 队列 / 绑定）。

    Args:
        channel: 已建立的 pika channel（需已 select 到目标 vhost）。
    """
    # 1) 交换机
    channel.exchange_declare(
        exchange=EXCHANGE_TASKS, exchange_type="topic", durable=True
    )
    channel.exchange_declare(
        exchange=EXCHANGE_DLX, exchange_type="topic", durable=True
    )

    # 2) 队列（含死信参数）
    channel.queue_declare(queue=QUEUE_INFERENCE, durable=True, arguments=_INFERENCE_ARGS)
    channel.queue_declare(
        queue=QUEUE_INFERENCE_DLQ, durable=True, arguments=_INFERENCE_DLQ_ARGS
    )
    channel.queue_declare(
        queue=QUEUE_MEMORY_PERSIST, durable=True, arguments=_MEMORY_PERSIST_ARGS
    )
    channel.queue_declare(
        queue=QUEUE_MEMORY_PERSIST_DLQ,
        durable=True,
        arguments=_MEMORY_PERSIST_DLQ_ARGS,
    )
    channel.queue_declare(
        queue=QUEUE_RAG_INDEX, durable=True, arguments=_RAG_INDEX_ARGS
    )
    channel.queue_declare(
        queue=QUEUE_RAG_INDEX_DLQ, durable=True, arguments=_RAG_INDEX_DLQ_ARGS
    )
    channel.queue_declare(
        queue=QUEUE_NOTIFY_PUSH, durable=True, arguments=_NOTIFY_PUSH_ARGS
    )

    # 3) 业务绑定：agent.tasks -> 各队列
    channel.queue_bind(
        queue=QUEUE_INFERENCE, exchange=EXCHANGE_TASKS, routing_key="agent.inference.*"
    )
    channel.queue_bind(
        queue=QUEUE_MEMORY_PERSIST, exchange=EXCHANGE_TASKS, routing_key="memory.persist"
    )
    channel.queue_bind(
        queue=QUEUE_RAG_INDEX, exchange=EXCHANGE_TASKS, routing_key="rag.index.*"
    )
    channel.queue_bind(
        queue=QUEUE_NOTIFY_PUSH, exchange=EXCHANGE_TASKS, routing_key="notify.*"
    )

    # 4) 死信绑定：agent.dlx -> 各 DLQ
    channel.queue_bind(
        queue=QUEUE_INFERENCE_DLQ,
        exchange=EXCHANGE_DLX,
        routing_key=QUEUE_INFERENCE_DLQ,
    )
    channel.queue_bind(
        queue=QUEUE_MEMORY_PERSIST_DLQ,
        exchange=EXCHANGE_DLX,
        routing_key=QUEUE_MEMORY_PERSIST_DLQ,
    )
    channel.queue_bind(
        queue=QUEUE_RAG_INDEX_DLQ,
        exchange=EXCHANGE_DLX,
        routing_key=QUEUE_RAG_INDEX_DLQ,
    )
