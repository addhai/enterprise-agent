"""共享类型定义

包含权限等级、业务域、质量状态等枚举型常量。
这些类型被 loader.py (向后兼容 shim) 和其他模块引用。
"""

# ---------------------------------------------------------------------------
# 权限标注
# ---------------------------------------------------------------------------


class AccessLevel:
    """文档访问权限等级"""

    PUBLIC = "public"               # 公开：定价、产品概述
    INTERNAL = "internal"           # 内部：FAQ、配置指南
    CONFIDENTIAL = "confidential"   # 机密：合同、财务
    RESTRICTED = "restricted"       # 受限：API Key、密码、凭证


# ---------------------------------------------------------------------------
# 业务域分类
# ---------------------------------------------------------------------------


class BusinessDomain:
    """业务域标签"""

    PRODUCT = "product"             # 产品：定价、功能、概述
    SALES = "sales"                 # 销售：合同、报价、发票
    SUPPORT = "support"             # 客服：FAQ、配置、故障排查
    ENGINEERING = "engineering"     # 技术：API、SDK、集成、部署
    LEGAL = "legal"                 # 法务：合规、隐私、条款


# ---------------------------------------------------------------------------
# 质量状态
# ---------------------------------------------------------------------------


class QualityStatus:
    """文档质量状态"""

    ACCEPT = "accept"                           # 接受，入库
    REJECT_LOW_QUALITY = "reject_low_quality"   # 拒绝：质量太低
    REJECT_EXPIRED = "reject_expired"           # 拒绝：已过期
    WARN_OUTDATED = "warn_outdated"             # 警告：可能过期
