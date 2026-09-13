"""Kie · Topaz 视频超分（topaz/video-upscale）契约层：请求编译、来源校验、费用预估。

画布插件 ariadne-topaz.js 移植；字段与枚举按官方 OpenAPI 核对
（docs.kie.ai/market/topaz/video-upscale.md，2026-09-14）：input 仅 video_url（必填）+
upscale_factor（字符串 '1'/'2'/'4'，默认 '2'）。官方未列 nsfw_checker，故不做该控件
（用户铁律：官方没列的字段不给空壳）。
"""
from __future__ import annotations

from pathlib import Path

MODEL = "topaz/video-upscale"
MAX_SOURCE_BYTES = 50 * 1024 * 1024  # 官方上限 50.0MB
ACCEPTED_EXTS = (".mp4", ".mov", ".mkv")  # 官方接受 video/mp4、video/quicktime、video/x-matroska
FACTOR_LABELS = {"1": "修复增强", "2": "2倍放大", "4": "4倍放大"}
# 画布版估价口径（1×/2× 同价、4× 翻倍）；credits→¥ 单价同为画布版常数，均以账单为准。
_CREDITS_PER_SECOND = {"1": 8, "2": 8, "4": 14}
_CNY_PER_CREDIT = 0.036


def parse_factor(widget_value) -> str:
    """下拉值（如 '2(2倍放大)' 或裸 '2'）→ 官方枚举字符串 '1'/'2'/'4'。"""
    factor = str(widget_value).split("(")[0].strip()
    if factor not in FACTOR_LABELS:
        raise ValueError(f"放大倍数必须是 1/2/4，当前为 {widget_value!r}。")
    return factor


def validate_source(path: str) -> None:
    """上传前本地拦截官方硬限制（超了 Kie 也拒，早失败不浪费上传时间）。"""
    file = Path(path)
    if not file.exists():
        raise RuntimeError(f"源视频不存在：{path}")
    if file.suffix.lower() not in ACCEPTED_EXTS:
        raise RuntimeError(
            f"Topaz 只接受 {'/'.join(ext.lstrip('.').upper() for ext in ACCEPTED_EXTS)}，"
            f"当前 {file.suffix or '无扩展名'}。请先转码。"
        )
    size = file.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise RuntimeError(
            f"源视频 {size / 1048576:.1f}MB 超过 Kie 上限 50MB，请先用本包裁剪功能或压缩后再超分。"
        )


def compile_request(video_url: str, factor: str) -> dict:
    """createTask 请求体：字段白名单以官方 OpenAPI 为准，不加未列字段。"""
    return {"model": MODEL, "input": {"video_url": video_url, "upscale_factor": str(factor)}}


def estimate_cny(duration_seconds: float, factor: str) -> float:
    """按画布版口径预估费用（人民币）：时长 × 每秒 credits × 单价。"""
    return round(float(duration_seconds) * _CREDITS_PER_SECOND.get(str(factor), 8) * _CNY_PER_CREDIT, 2)
