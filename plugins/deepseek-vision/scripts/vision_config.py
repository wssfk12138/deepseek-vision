"""统一的视觉 API 配置解析与校验（供插件所有脚本共用）。

新用户必须自行配置 API 请求地址与 API Key；插件不内置任何密钥或默认地址。
标准模板：MCP_OCR_PROVIDER=custom + MCP_OCR_BASE_URL + MCP_OCR_API_KEY + MCP_OCR_MODEL。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

PRESETS: dict[str, dict[str, str]] = {
    "dashscope": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_env": "DASHSCOPE_API_KEY",
        "model_env": "DASHSCOPE_MODEL",
        "default_model": "qwen-vl-max",
    },
    "volcengine": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "key_env": "VOLCENGINE_API_KEY",
        "model_env": "VOLCENGINE_MODEL",
        "default_model": "doubao-1.5-vision-pro-32k",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4o",
    },
}


class ConfigError(Exception):
    pass


def load_env() -> None:
    load_dotenv(PLUGIN_ROOT / ".env")


def resolve_config() -> dict[str, str]:
    """读取 .env 并返回 {provider, api_key, base_url, model}，缺失必填项时抛 ConfigError。"""
    load_env()
    provider = os.environ.get("MCP_OCR_PROVIDER", "custom").strip().lower()

    if provider == "custom":
        api_key = os.environ.get("MCP_OCR_API_KEY", "").strip()
        base_url = os.environ.get("MCP_OCR_BASE_URL", "").strip()
        model = os.environ.get("MCP_OCR_MODEL", "").strip()
    elif provider in PRESETS:
        preset = PRESETS[provider]
        api_key = os.environ.get(preset["key_env"], "").strip()
        base_url = preset["base_url"]
        model = os.environ.get(preset["model_env"], "").strip() or preset["default_model"]
    else:
        raise ConfigError(
            f"MCP_OCR_PROVIDER 不支持: {provider}（通用配置请使用 custom）"
        )

    missing = []
    if not base_url:
        missing.append("API 请求地址（MCP_OCR_BASE_URL）")
    if not api_key:
        missing.append("API Key（MCP_OCR_API_KEY）")
    if not model:
        missing.append("视觉模型名（MCP_OCR_MODEL）")
    if missing:
        raise ConfigError(
            "未配置 " + "、".join(missing) + "。请编辑插件根目录 .env 完成配置，"
            "然后运行 scripts\\check_config.py 验证。"
        )
    return {"provider": provider, "api_key": api_key, "base_url": base_url, "model": model}


def mask_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "***"
    return api_key[:6] + "***" + api_key[-2:]
