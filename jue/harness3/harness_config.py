"""Harness③ API配置管理

三层优先级（从高到低）：
1. harness自己的api_config_name → config.json里configs字典对应配置
2. config.json里的global配置
3. 主Jue配置（兜底，从环境变量或主配置文件读取）

config.json格式：
{
    "global": {"base_url": "...", "api_key": "...", "model_id": "..."},
    "configs": {
        "safe-model": {"base_url": "...", "api_key": "...", "model_id": "..."},
        "fast-model": {"base_url": "...", "api_key": "...", "model_id": "..."}
    }
}

模型只能写api_config_name（引用名），不能直接写key。
真实的 provider routing / fallback / credential pool 仍由 Jue runtime 执行；
这里做的只是“命名配置 -> 运行时引用”的桥接。
"""

import json
import os
import logging
from dataclasses import dataclass
from pathlib import Path

from jue_constants import get_jue_home

logger = logging.getLogger(__name__)


@dataclass
class ApiConfig:
    """单个API配置"""
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    api_mode: str = ""
    model_id: str = ""
    credential_pool_name: str = ""
    fallback_providers: list[dict] | None = None

    def __post_init__(self) -> None:
        if self.fallback_providers is None:
            self.fallback_providers = []


def _merge_layer(result: ApiConfig, layer: dict) -> None:
    if not isinstance(layer, dict):
        return
    if not result.provider:
        result.provider = str(layer.get("provider", "") or "")
    if not result.base_url:
        result.base_url = str(layer.get("base_url", "") or "")
    if not result.api_key:
        result.api_key = str(layer.get("api_key", "") or "")
    if not result.api_mode:
        result.api_mode = str(layer.get("api_mode", "") or "")
    if not result.model_id:
        result.model_id = str(layer.get("model_id", "") or "")
    if not result.credential_pool_name:
        result.credential_pool_name = str(
            layer.get("credential_pool_name")
            or layer.get("credential_pool")
            or ""
        )
    if not result.fallback_providers:
        fallbacks = layer.get("fallback_providers")
        if isinstance(fallbacks, list):
            result.fallback_providers = [f for f in fallbacks if isinstance(f, dict)]
        elif isinstance(layer.get("fallback_model"), dict):
            result.fallback_providers = [dict(layer["fallback_model"])]


def _config_path() -> Path:
    """config.json路径"""
    return get_jue_home() / "harness3" / "config.json"


def load_config() -> dict:
    """加载config.json，不存在则返回空结构"""
    path = _config_path()
    if not path.exists():
        return {"global": {}, "configs": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not load harness config: %s", e)
        return {"global": {}, "configs": {}}


def save_config(config: dict) -> None:
    """写入config.json"""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Harness③ config saved to %s", path)


def resolve_api(api_config_name: str = "") -> ApiConfig:
    """三层优先级解析API配置

    1. api_config_name → configs[name]
    2. global
    3. 环境变量兜底（JUE_BASE_URL, JUE_API_KEY, JUE_MODEL_ID）

    任何层级的字段为空都意味着"这一层没配，该字段往下一层找"。
    """
    config = load_config()
    result = ApiConfig()

    # 第1层：harness指定的配置名
    if api_config_name:
        _merge_layer(result, config.get("configs", {}).get(api_config_name, {}))

    # 第2层：global补缺
    _merge_layer(result, config.get("global", {}))

    # 第3层：环境变量兜底
    if not result.provider:
        result.provider = os.environ.get("JUE_PROVIDER", "")
    if not result.base_url:
        result.base_url = os.environ.get("JUE_BASE_URL", "")
    if not result.api_key:
        result.api_key = os.environ.get("JUE_API_KEY", "")
    if not result.api_mode:
        result.api_mode = os.environ.get("JUE_API_MODE", "")
    if not result.model_id:
        result.model_id = os.environ.get("JUE_MODEL_ID", "")
    if not result.credential_pool_name:
        result.credential_pool_name = os.environ.get("JUE_CREDENTIAL_POOL", "")

    return result


def set_global_config(
    base_url: str = "",
    api_key: str = "",
    model_id: str = "",
    provider: str = "",
    api_mode: str = "",
    credential_pool_name: str = "",
    fallback_providers: list[dict] | None = None,
) -> None:
    """设置全局API配置"""
    config = load_config()
    if provider:
        config.setdefault("global", {})["provider"] = provider
    if base_url:
        config.setdefault("global", {})["base_url"] = base_url
    if api_key:
        config.setdefault("global", {})["api_key"] = api_key
    if api_mode:
        config.setdefault("global", {})["api_mode"] = api_mode
    if model_id:
        config.setdefault("global", {})["model_id"] = model_id
    if credential_pool_name:
        config.setdefault("global", {})["credential_pool_name"] = credential_pool_name
    if fallback_providers:
        config.setdefault("global", {})["fallback_providers"] = list(fallback_providers)
    save_config(config)


def set_named_config(
    name: str,
    base_url: str = "",
    api_key: str = "",
    model_id: str = "",
    provider: str = "",
    api_mode: str = "",
    credential_pool_name: str = "",
    fallback_providers: list[dict] | None = None,
) -> None:
    """设置命名API配置（模型只能引用name，不能直接写key）"""
    if not name.strip():
        logger.warning("Cannot set config with empty name")
        return
    config = load_config()
    config.setdefault("configs", {})[name] = {
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "api_mode": api_mode,
        "model_id": model_id,
        "credential_pool_name": credential_pool_name,
        "fallback_providers": list(fallback_providers or []),
    }
    save_config(config)


def list_named_configs() -> list[str]:
    """列出所有命名配置的名字"""
    config = load_config()
    return list(config.get("configs", {}).keys())
