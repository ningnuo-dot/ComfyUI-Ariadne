"""Kie 图生图服务商注册表（自 ariadne-visual-pro src/providers.py 移植，2026-09-10 实读 docs.kie.ai 核对）。

字段名跨模型不通用，组装请求必须查本表，不允许猜：
- nano-banana-pro / nano-banana-2 → image_input（nano-banana-pro 的 image_urls 会被静默忽略，
  2026-09-08 本仓事故）
- seedream / grok-imagine → image_urls
- gpt-image 系 → input_urls
分辨率参数名：nano 系 / gpt-image 系 → resolution；seedream → quality（basic=1K/high=2K）；grok 无。
⚠️ 2026-09-11 首跑实测：gpt-image-2-5-sunburst 4K 纹理软糊，图生图场景暂不录用（保留登记）。
"""
from __future__ import annotations

DEFAULT_PLATFORM = "kie-nano-banana-pro"

ALIASES: dict[str, str] = {
    "nano-banana-pro": "kie-nano-banana-pro",
    "seedream-5-pro": "kie-seedream-5-pro",
    "grok-imagine-2": "kie-grok-imagine-2",
    "gpt-image-2": "kie-gpt-image-2",
    "gpt-image-2-5-flare": "kie-gpt-image-2-5-flare",
    "gpt-image-2-5-sunburst": "kie-gpt-image-2-5-sunburst",
    "nano-banana-2": "kie-nano-banana-2",
}

PROVIDERS: dict[str, dict] = {
    "kie-nano-banana-pro": {
        "key": "kie-nano-banana-pro", "channel": "kie", "vendor": "Google",
        "label": "Google Nano Banana Pro",
        "model": "nano-banana-pro", "ref_field": "image_input", "ref_limit": 8,
        "aspects": ["9:16", "16:9", "1:1", "3:4", "3:2", "2:3", "4:3", "4:5", "5:4", "21:9"],
        "resolution_field": "resolution", "resolution_default": "2K",
        "resolutions": [("1K", "1K"), ("2K", "2K"), ("4K", "4K")],
        "extra": {"output_format": "png", "nsfw_checker": True},
        "credits_hint": "约 8 credits/张",
    },
    "kie-seedream-5-pro": {
        "key": "kie-seedream-5-pro", "channel": "kie", "vendor": "ByteDance",
        "label": "ByteDance Seedream 5.0 Pro",
        "model": "seedream/5-pro-image-to-image", "ref_field": "image_urls", "ref_limit": 10,
        "aspects": ["9:16", "16:9", "1:1", "3:4", "3:2", "2:3", "4:3", "21:9"],
        "resolution_field": "quality", "resolution_default": "high",
        "resolutions": [("basic", "1K·基础"), ("high", "2K·高清")],
        "extra": {"output_format": "png", "nsfw_checker": True},
        "credits_hint": "约 7 credits/张",
    },
    "kie-grok-imagine-2": {
        "key": "kie-grok-imagine-2", "channel": "kie", "vendor": "xAI",
        "label": "xAI Grok Imagine 2.0",
        "model": "grok-imagine-image-2-0/image-edit", "ref_field": "image_urls", "ref_limit": 5,
        "aspects": ["9:16", "16:9", "1:1", "2:3", "3:2"],
        "resolution_field": None, "resolution_default": None, "resolutions": [],
        "extra": {},
        "credits_hint": "约 4 credits/张",
    },
    "kie-gpt-image-2": {
        "key": "kie-gpt-image-2", "channel": "kie", "vendor": "OpenAI",
        "label": "OpenAI GPT Image 2",
        "model": "gpt-image-2-image-to-image", "ref_field": "input_urls", "ref_limit": 16,
        "aspects": ["9:16", "16:9", "1:1", "3:4", "3:2", "2:3", "4:3", "2:1", "21:9"],
        "resolution_field": "resolution", "resolution_default": "2K",
        "resolutions": [("1K", "1K"), ("2K", "2K"), ("4K", "4K")],
        "extra": {},
        "credits_hint": "2K≈5 / 4K≈8 credits",
    },
    "kie-gpt-image-2-5-flare": {
        "key": "kie-gpt-image-2-5-flare", "channel": "kie", "vendor": "OpenAI",
        "label": "OpenAI GPT Image 2.5 Flare",
        "model": "gpt-image-2-5-flare-image-to-image", "ref_field": "input_urls", "ref_limit": 16,
        "aspects": ["9:16", "16:9", "1:1", "3:4", "3:2", "2:3", "4:3", "21:9"],
        "resolution_field": "resolution", "resolution_default": "2K",
        "resolutions": [("1K", "1K"), ("2K", "2K"), ("4K", "4K")],
        "extra": {},
        "credits_hint": "文档示例 ≈3 credits/张（待首跑核实）",
    },
    "kie-gpt-image-2-5-sunburst": {
        "key": "kie-gpt-image-2-5-sunburst", "channel": "kie", "vendor": "OpenAI",
        "label": "OpenAI GPT Image 2.5 Sunburst",
        "model": "gpt-image-2-5-sunburst-image-to-image", "ref_field": "input_urls", "ref_limit": 16,
        "aspects": ["9:16", "16:9", "1:1", "3:4", "3:2", "2:3", "4:3", "21:9"],
        "resolution_field": "resolution", "resolution_default": "2K",
        "resolutions": [("1K", "1K"), ("2K", "2K"), ("4K", "4K")],
        "extra": {},
        "credits_hint": "文档示例 ≈3 credits/张（2026-09-11 实测纹理软糊，图生图暂不录用）",
    },
    "kie-nano-banana-2": {
        "key": "kie-nano-banana-2", "channel": "kie", "vendor": "Google",
        "label": "Google Nano Banana 2",
        "model": "nano-banana-2", "ref_field": "image_input", "ref_limit": 14,
        "aspects": ["9:16", "16:9", "1:1", "3:4", "3:2", "2:3", "4:3", "21:9"],
        "resolution_field": "resolution", "resolution_default": "2K",
        "resolutions": [("1K", "1K"), ("2K", "2K"), ("4K", "4K")],
        "extra": {"output_format": "png"},
        "credits_hint": "约 8 credits/张",
    },
}


def get_provider(platform: str) -> dict:
    """按 key 取服务商定义（旧 key 自动归一）；未知名抛 ValueError。"""
    value = str(platform or "").strip()
    value = ALIASES.get(value, value)
    provider = PROVIDERS.get(value)
    if not provider:
        raise ValueError(f"未知服务商：{platform}（可选 {'/'.join(PROVIDERS)}）")
    return provider


def resolve_aspect(provider: dict, aspect: str) -> str:
    value = str(aspect or "").strip()
    if value not in provider["aspects"]:
        raise ValueError(f"{provider['label']} 不支持画幅 {value}（可选 {'/'.join(provider['aspects'])}）")
    return value


def resolve_resolution(provider: dict, resolution: str) -> str | None:
    """分辨率换算成提交值；服务商无分辨率参数时返回 None（请求不带该字段）。"""
    field = provider["resolution_field"]
    if not field:
        return None
    value = str(resolution or "").strip()
    for submit_value, label in provider["resolutions"]:
        if value == submit_value or value == label.split("·")[0]:
            return submit_value
    labels = "/".join(label for _v, label in provider["resolutions"])
    raise ValueError(f"{provider['label']} 分辨率需为 {labels}")
