"""配置中心 API — 运行时配置查看与热更新

提供 HTTP 接口管理运行时配置（feature flag、阈值、模型参数）：
    - 按分类查看配置（脱敏敏感字段）
    - 热更新配置（无需重启服务）
    - Feature flag 一键切换
    - 重置到默认值

权限：admin / agent 可读，仅 admin 可写。

设计原则：
    1. 白名单制：只允许更新 CONFIG_CATEGORIES 中列出的字段
    2. 敏感字段脱敏：包含 key/secret/password/token 的字段只返回 *_configured: bool
    3. 类型校验：基于 Pydantic 字段类型校验更新值
    4. 审计日志：记录配置变更
"""
import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from src.api.rbac import Permission, require_permissions
from src.config import Settings, settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["config"])


# ====================================================================
# 配置分类定义
# ====================================================================

CONFIG_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "llm": {
        "label": "LLM 模型",
        "description": "大语言模型推理参数",
        "fields": [
            "llm_model", "llm_complex_model",
            "llm_temperature", "llm_max_tokens", "llm_enable_thinking",
        ],
    },
    "retrieval": {
        "label": "检索配置",
        "description": "知识库检索参数（相似度阈值、top_k 等）",
        "fields": [
            "retrieval_top_k", "retrieval_rerank_top_n", "retrieval_min_tokens",
            "kb_similarity_threshold", "kb_call_mode", "kb_weights",
        ],
    },
    "rerank": {
        "label": "重排序",
        "description": "检索结果重排序（P1 功能）",
        "fields": ["rerank_enabled", "rerank_provider", "rerank_model", "rerank_top_n"],
    },
    "rag": {
        "label": "RAG/文档",
        "description": "文档分块与 DeepDoc 解析",
        "fields": [
            "chunk_size", "chunk_overlap",
            "deepdoc_enabled", "deepdoc_scan_threshold", "deepdoc_render_dpi",
        ],
    },
    "dedup": {
        "label": "去重",
        "description": "文档去重策略",
        "fields": [
            "dedup_exact_enabled", "dedup_simhash_enabled",
            "dedup_simhash_threshold", "dedup_simhash_window",
        ],
    },
    "guardrail": {
        "label": "安全护栏",
        "description": "输入安全检测（P2 功能）",
        "fields": ["guardrail_enabled", "guardrail_llm_jailbreak", "guardrail_llm_relevance"],
    },
    "hitl": {
        "label": "人工审批",
        "description": "敏感操作人工审批（P2 功能）",
        "fields": ["humanloop_enabled", "humanloop_timeout", "humanloop_notify_channel"],
    },
    "memory": {
        "label": "记忆",
        "description": "短期/长期记忆参数",
        "fields": ["memory_context_max_docs", "context_rounds", "short_term_ttl", "short_term_max_window"],
    },
    "evaluation": {
        "label": "评估",
        "description": "质量评估配置（P5 功能）",
        "fields": [
            "eval_llm_judge_enabled", "eval_online_sampling_rate",
            "eval_hallucination_check_enabled",
        ],
    },
    "vision": {
        "label": "视觉/OCR",
        "description": "图像理解与 OCR 引擎",
        "fields": [
            "vision_engine_name", "vision_model", "vision_timeout",
            "ocr_engine_name", "fallback_ocr_name",
        ],
    },
    "agent": {
        "label": "Agent",
        "description": "Agent 推理轮次",
        "fields": ["max_reasoning_turns", "max_turns_faq", "max_turns_technical", "max_turns_complex"],
    },
    "outline": {
        "label": "大纲/章节",
        "description": "文档大纲元数据",
        "fields": ["outline_store_full_json"],
    },
}

# 敏感字段关键词（字段名包含这些词的视为敏感）
SENSITIVE_KEYWORDS = ("key", "secret", "password", "token", "credential")

# 所有可更新字段的白名单
_UPDATABLE_FIELDS: set = set()
for cat in CONFIG_CATEGORIES.values():
    _UPDATABLE_FIELDS.update(cat["fields"])


# ====================================================================
# 辅助函数
# ====================================================================

def _is_sensitive(field_name: str) -> bool:
    """判断字段是否敏感（需要脱敏）"""
    return any(kw in field_name.lower() for kw in SENSITIVE_KEYWORDS)


def _get_field_type(field_name: str) -> type:
    """获取字段类型"""
    field_info = Settings.model_fields.get(field_name)
    if field_info is None:
        return str
    ann = field_info.annotation
    # 处理 Optional[...] / Union[...]
    if hasattr(ann, "__origin__") and ann.__origin__ is Union:
        # 取非 None 的类型
        args = [a for a in ann.__args__ if a is not type(None)]
        if args:
            return args[0]
    return ann or str


def _get_field_default(field_name: str) -> Any:
    """获取字段默认值"""
    field_info = Settings.model_fields.get(field_name)
    if field_info is None:
        return None
    if field_info.default is not None:
        return field_info.default
    return field_info.default_factory() if field_info.default_factory else None


def _get_field_value(field_name: str) -> Any:
    """获取当前字段值"""
    return getattr(settings, field_name, None)


def _set_field_value(field_name: str, value: Any) -> None:
    """设置字段值（热更新）"""
    setattr(settings, field_name, value)


def _coerce_value(field_name: str, value: Any) -> Any:
    """将输入值强制转换为字段类型"""
    target_type = _get_field_type(field_name)
    try:
        if target_type is bool:
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "on")
            return bool(value)
        if target_type is int:
            return int(value)
        if target_type is float:
            return float(value)
        return str(value)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"字段 {field_name} 期望类型 {target_type.__name__}，但收到 {value!r}: {e}",
        )


def _field_to_dict(field_name: str) -> Dict[str, Any]:
    """将单个字段转为字典表示（敏感字段脱敏）"""
    value = _get_field_value(field_name)
    target_type = _get_field_type(field_name)
    default = _get_field_default(field_name)

    result: Dict[str, Any] = {
        "name": field_name,
        "type": target_type.__name__,
        "default": default,
        "is_sensitive": _is_sensitive(field_name),
    }

    if _is_sensitive(field_name):
        result["value"] = ""
        result["configured"] = bool(value)
    else:
        result["value"] = value
        result["is_default"] = (value == default)

    return result


# ====================================================================
# 请求模型
# ====================================================================

class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""
    updates: Dict[str, Any] = Field(
        ...,
        description="字段名 → 新值 的映射，如 {'rerank_enabled': true, 'kb_similarity_threshold': 0.3}",
    )


class FeatureFlagUpdateRequest(BaseModel):
    """Feature flag 切换请求"""
    enabled: bool = Field(..., description="true=启用, false=禁用")


# ====================================================================
# API 路由
# 注意：固定路径必须在动态路径 /admin/config/{category} 之前注册，
# 否则 FastAPI 会把 "features"、"meta"、"reset" 等当作 category 参数。
# ====================================================================

@router.get("/admin/config")
async def list_all_config(
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CONFIG_VIEW)),
):
    """获取所有配置（按分类，脱敏敏感字段）

    需要 config:view 权限
    """
    categories: List[Dict[str, Any]] = []
    for cat_key, cat_meta in CONFIG_CATEGORIES.items():
        fields = [_field_to_dict(f) for f in cat_meta["fields"]]
        categories.append({
            "key": cat_key,
            "label": cat_meta["label"],
            "description": cat_meta["description"],
            "fields": fields,
        })

    return {
        "total_categories": len(categories),
        "categories": categories,
    }


@router.put("/admin/config")
async def update_config(
    req: ConfigUpdateRequest,
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CONFIG_MANAGE)),
):
    """批量更新配置（需 config:manage 权限）

    支持部分更新，只更新提供的字段。
    敏感字段（key/secret/password/token）不可通过此接口修改。
    更新后立即生效（内存热更新），重启后回退到 .env 配置。

    示例：
        {"updates": {"rerank_enabled": true, "kb_similarity_threshold": 0.3}}
    """
    if not req.updates:
        raise HTTPException(status_code=400, detail="更新内容不能为空")

    updated: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []

    for field_name, raw_value in req.updates.items():
        # 白名单检查
        if field_name not in _UPDATABLE_FIELDS:
            skipped.append({"field": field_name, "reason": "不在可更新白名单中"})
            continue

        # 敏感字段检查
        if _is_sensitive(field_name):
            skipped.append({"field": field_name, "reason": "敏感字段不可通过此接口修改"})
            continue

        # 类型转换
        old_value = _get_field_value(field_name)
        try:
            new_value = _coerce_value(field_name, raw_value)
        except HTTPException as e:
            skipped.append({"field": field_name, "reason": e.detail})
            continue

        # 设置新值
        _set_field_value(field_name, new_value)
        updated.append({
            "field": field_name,
            "old_value": old_value,
            "new_value": new_value,
        })

        logger.info(
            "Config updated: %s = %r (was %r) by=%s",
            field_name, new_value, old_value, current_user.get("user_id"),
        )

    return {
        "success": True,
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "updated": updated,
        "skipped": skipped,
    }


# ---------- 固定路径：必须在 /{category} 之前 ----------
@router.get("/admin/config/meta/categories")
async def get_config_categories(
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CONFIG_VIEW)),
):
    """获取配置分类清单

    供前端渲染配置面板的 tab/分组用。
    """
    categories = [
        {
            "key": k,
            "label": v["label"],
            "description": v["description"],
            "field_count": len(v["fields"]),
        }
        for k, v in CONFIG_CATEGORIES.items()
    ]
    return {
        "total": len(categories),
        "categories": categories,
    }


@router.get("/admin/config/features")
async def list_feature_flags(
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CONFIG_VIEW)),
):
    """获取所有 Feature Flag 状态

    返回所有布尔型配置项的当前状态，便于一键查看功能开关。
    """
    flags: List[Dict[str, Any]] = []
    for cat_key, cat_meta in CONFIG_CATEGORIES.items():
        for field_name in cat_meta["fields"]:
            if _get_field_type(field_name) is not bool:
                continue
            value = _get_field_value(field_name)
            default = _get_field_default(field_name)
            flags.append({
                "name": field_name,
                "enabled": bool(value),
                "is_default": (value == default),
                "category": cat_key,
                "category_label": cat_meta["label"],
            })

    enabled_count = sum(1 for f in flags if f["enabled"])
    return {
        "total": len(flags),
        "enabled": enabled_count,
        "disabled": len(flags) - enabled_count,
        "flags": flags,
    }


@router.put("/admin/config/features/{flag}")
async def toggle_feature_flag(
    flag: str = Path(..., description="Feature flag 名称，如 rerank_enabled"),
    req: FeatureFlagUpdateRequest = Body(...),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CONFIG_MANAGE)),
):
    """切换单个 Feature Flag（需 config:manage 权限）

    示例：
        PUT /admin/config/features/rerank_enabled
        Body: {"enabled": true}
    """
    # 检查是否是有效的布尔型字段
    if flag not in _UPDATABLE_FIELDS:
        raise HTTPException(
            status_code=404,
            detail=f"Feature flag 不存在或不可更新: {flag}",
        )

    if _get_field_type(flag) is not bool:
        raise HTTPException(
            status_code=400,
            detail=f"字段 {flag} 不是布尔型，无法作为 feature flag 切换",
        )

    old_value = _get_field_value(flag)
    _set_field_value(flag, req.enabled)

    logger.info(
        "Feature flag toggled: %s = %r (was %r) by=%s",
        flag, req.enabled, old_value, current_user.get("user_id"),
    )

    return {
        "success": True,
        "flag": flag,
        "enabled": req.enabled,
        "previous_value": old_value,
    }


@router.post("/admin/config/reset")
async def reset_config(
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CONFIG_MANAGE)),
):
    """重置所有可更新配置到默认值（需 config:manage 权限）

    将白名单中的所有字段重置为 Settings 类定义的默认值。
    注意：此操作不影响 .env 文件，只重置内存中的值。
    """
    reset_fields: List[Dict[str, Any]] = []

    for field_name in _UPDATABLE_FIELDS:
        if _is_sensitive(field_name):
            continue
        old_value = _get_field_value(field_name)
        default_value = _get_field_default(field_name)
        if old_value != default_value:
            _set_field_value(field_name, default_value)
            reset_fields.append({
                "field": field_name,
                "old_value": old_value,
                "default_value": default_value,
            })

    logger.info(
        "Config reset to defaults: %d fields changed by=%s",
        len(reset_fields), current_user.get("user_id"),
    )

    return {
        "success": True,
        "reset_count": len(reset_fields),
        "reset_fields": reset_fields,
    }


@router.post("/admin/config/reset/{category}")
async def reset_config_category(
    category: str = Path(..., description="配置分类 key"),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CONFIG_MANAGE)),
):
    """重置指定分类的配置到默认值（需 config:manage 权限）"""
    cat_meta = CONFIG_CATEGORIES.get(category)
    if cat_meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"配置分类不存在: {category}，可用: {list(CONFIG_CATEGORIES.keys())}",
        )

    reset_fields: List[Dict[str, Any]] = []

    for field_name in cat_meta["fields"]:
        if _is_sensitive(field_name):
            continue
        old_value = _get_field_value(field_name)
        default_value = _get_field_default(field_name)
        if old_value != default_value:
            _set_field_value(field_name, default_value)
            reset_fields.append({
                "field": field_name,
                "old_value": old_value,
                "default_value": default_value,
            })

    logger.info(
        "Config category reset: %s, %d fields changed by=%s",
        category, len(reset_fields), current_user.get("user_id"),
    )

    return {
        "success": True,
        "category": category,
        "reset_count": len(reset_fields),
        "reset_fields": reset_fields,
    }


# ---------- 动态路径：必须放在所有固定路径之后 ----------
@router.get("/admin/config/{category}")
async def get_config_by_category(
    category: str = Path(..., description="配置分类 key"),
    current_user: Dict[str, Any] = Depends(require_permissions(Permission.CONFIG_VIEW)),
):
    """获取指定分类的配置

    需要 config:view 权限
    """
    cat_meta = CONFIG_CATEGORIES.get(category)
    if cat_meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"配置分类不存在: {category}，可用: {list(CONFIG_CATEGORIES.keys())}",
        )

    fields = [_field_to_dict(f) for f in cat_meta["fields"]]
    return {
        "key": category,
        "label": cat_meta["label"],
        "description": cat_meta["description"],
        "fields": fields,
    }
