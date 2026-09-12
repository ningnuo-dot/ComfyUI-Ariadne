"""包级配置：config.local.json 读写（密钥/站点/桶），脱敏回显。

密钥不进 Git（.gitignore 已排除 config.local.json）；解析顺序：config 文件 → 环境变量。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PACKAGE_DIR / "config.local.json"

DEFAULTS = {
    "ark_api_key": "",
    "kie_api_key": "",
    "tos": {"accessKey": "", "secretKey": "", "bucket": "huoshan-yinpin", "region": "cn-shanghai", "endpoint": "tos-cn-shanghai.volces.com"},
    "optimizer": {"base_url": "https://api.deepseek.com", "model": "", "api_key": ""},
}

SENSITIVE_KEYS = {"ark_api_key", "kie_api_key", "accessKey", "secretKey", "api_key"}


def load_config() -> dict:
    """读 config.local.json（缺省项用 DEFAULTS 补齐）；文件损坏按空配置处理。"""
    config = json.loads(json.dumps(DEFAULTS))
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for key, value in stored.items():
                if key in ("tos", "optimizer") and isinstance(value, dict):
                    config[key].update(value)
                else:
                    config[key] = value
        except (ValueError, OSError):
            pass
    return config


def save_config(updates: dict) -> dict:
    """合并写入；空串不覆盖已有值（防止前端漏传清空密钥）。返回更新后的完整配置。"""
    config = load_config()
    for key, value in (updates or {}).items():
        if key in ("tos", "optimizer") and isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if str(sub_value).strip() == "" and config[key].get(sub_key):
                    continue
                config[key][sub_key] = sub_value
        else:
            if str(value).strip() == "" and config.get(key):
                continue
            config[key] = value
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def masked_config(config: dict | None = None) -> dict:
    """脱敏回显：敏感字段只留前 4 后 2 位。"""
    import copy

    config = copy.deepcopy(config or load_config())

    def mask(value: str) -> str:
        value = str(value or "")
        if not value:
            return ""
        return f"{value[:4]}****{value[-2:]}" if len(value) > 8 else "****"

    for key, value in config.items():
        if key in SENSITIVE_KEYS:
            config[key] = mask(value)
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if sub_key in SENSITIVE_KEYS:
                    value[sub_key] = mask(sub_value)
    return config


def resolve_ark_key() -> str:
    config = load_config()
    key = str(config.get("ark_api_key") or "").strip() or os.environ.get("ARK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("尚未配置火山方舟 API Key：请在「Ariadne 工作台」侧栏填写方舟 Key（或设 ARK_API_KEY 环境变量）。")
    return key


def resolve_kie_key() -> str:
    config = load_config()
    key = str(config.get("kie_api_key") or "").strip() or os.environ.get("KIE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("尚未配置 Kie 密钥：请在「Ariadne 工作台」侧栏填写 Kie Key（或设 KIE_API_KEY 环境变量）。")
    return key


def tos_settings() -> dict | None:
    config = load_config()
    tos = config.get("tos") or {}
    if not str(tos.get("accessKey") or "").strip():
        return None
    return tos
