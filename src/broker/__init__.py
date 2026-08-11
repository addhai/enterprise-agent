"""Broker 包：RabbitMQ 拓扑自初始化。

此前拓扑靠 rabbitmq.conf 的 load_definitions 静态导入 definitions.json，
但在 RabbitMQ 4.x 会稳定触发
  BOOT FAILED: Please create virtual host "/" prior to importing definitions
（内建默认 vhost "/" 的创建时机晚于 definitions 导入校验）。

改为由应用自身幂等声明拓扑：broker 启动后，任意连接方调用 declare_topology
即可把交换机/队列/绑定补齐，不依赖 management 插件，也不受 vhost 顺序坑影响。
"""

from .topology import declare_topology

__all__ = ["declare_topology"]
