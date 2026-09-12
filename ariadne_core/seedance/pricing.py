"""火山方舟刊例价费用预估（画布插件 pricing.ts + kie-pricing.ts 的 Python 版）。

方舟费率：docs.volcengine.com/docs/82379/1099320（2026-09-07 实读）；
Kie 积分：官网 bytedance/seedance-2-5 价格页（2026-09-10，480p 含视频档 17/秒经任务
e7d40b79 实测 306 = 17×(14+4) 精确复现）。调价只改表。
估价仅展示不扣费，以实际账单为准。
"""
from __future__ import annotations

from datetime import datetime, timezone

# 模型 → 分辨率 → {无视频输入价, 含视频输入价}（元/百万token），discount 为限时折扣。
SEEDANCE_RATES = {
    "seedance-2.5": {
        "480p": {"withoutVideo": 70, "withVideo": 42},
        "720p": {"withoutVideo": 70, "withVideo": 42},
        "1080p": {"withoutVideo": 77, "withVideo": 46, "discount": (0.72, "2026-09-17T14:00:00+08:00")},
    },
    "seedance-2.0-mini": {
        "480p": {"withoutVideo": 23, "withVideo": 14, "discount": (0.4, "2026-10-07T14:00:00+08:00")},
        "720p": {"withoutVideo": 23, "withVideo": 14, "discount": (0.4, "2026-10-07T14:00:00+08:00")},
    },
    "seedance-2.0-fast": {
        "480p": {"withoutVideo": 37, "withVideo": 22, "discount": (0.75, "2026-10-07T14:00:00+08:00")},
        "720p": {"withoutVideo": 37, "withVideo": 22, "discount": (0.75, "2026-10-07T14:00:00+08:00")},
    },
}
_DIMENSIONS = {"480p": (854, 480), "720p": (1280, 720), "1080p": (1920, 1080)}

# Kie 积分单价（credits/秒）。
KIE_RATES = {
    "usdPerCredit": 0.005,
    "cnyPerCredit": 0.036,
    "creditsPerSecond": {
        "480p": {"withoutVideo": 28, "withVideo": 17},
        "720p": {"withoutVideo": 63, "withVideo": 38},
        "1080p": {"withoutVideo": 114, "withVideo": 68.5},
    },
}


def _parse_iso(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def seedance_unit_rate(resolution: str, model: str = "seedance-2.5", includes_video: bool = False, now: float | None = None) -> float | None:
    """当前适用单价（元/百万token）；无费率档位返回 None。now 可注入以测限时折扣。"""
    row = SEEDANCE_RATES.get(model, {}).get(resolution)
    if not row:
        return None
    price = row["withVideo"] if includes_video else row["withoutVideo"]
    discount = row.get("discount")
    if discount:
        factor, until = discount
        ts = now if now is not None else datetime.now(timezone.utc).timestamp()
        if ts <= _parse_iso(until):
            return round(price * factor, 4)
    return float(price)


def estimate_ark_price(resolution: str, duration: int, model: str = "seedance-2.5", includes_video: bool = False, input_video_seconds: float = 0.0, fps: int = 24, now: float | None = None) -> float | None:
    """方舟预估费用（元）。自适应（-1）编辑/延长按输入视频时长估算，未知返回 None。"""
    rate = seedance_unit_rate(resolution, model, includes_video, now)
    if rate is None:
        return None
    width, height = _DIMENSIONS[resolution]
    input_seconds = max(input_video_seconds or 0.0, 0.0) if includes_video else 0.0
    output_seconds = duration if duration >= 0 else (input_seconds if input_seconds > 0 else -1)
    if output_seconds < 0:
        return None
    token_millions = (output_seconds + input_seconds) * width * height * fps / 1024 / 1_000_000
    return round(rate * token_millions, 4)


def estimate_kie_credits(resolution: str, duration: int, includes_video: bool = False, input_video_seconds: float = 0.0) -> float | None:
    """Kie 渠道预估积分；时长 -1 返回 None（Kie 本就不支持自适应）。"""
    row = KIE_RATES["creditsPerSecond"].get(resolution)
    if not row or duration < 0:
        return None
    rate = row["withVideo"] if includes_video else row["withoutVideo"]
    input_seconds = max(input_video_seconds or 0.0, 0.0) if includes_video else 0.0
    return rate * (input_seconds + duration)
