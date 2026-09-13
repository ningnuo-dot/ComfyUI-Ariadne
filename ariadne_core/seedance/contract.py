"""Seedance 2.5 统一输入契约（画布插件 contract.ts 的 Python 版，逐字段对齐）。"""
from __future__ import annotations

from dataclasses import dataclass, field

MODEL = "doubao-seedance-2-5-260628"
# 相对路径：ark.py 的 ARK_BASE_URL 已含 /api/v3，这里不能再带一遍（曾拼成 /api/v3/api/v3/... 空包 404）
ENDPOINT = "/contents/generations/tasks"

ROLES = ("character", "wardrobe", "scene", "motion", "audio", "first-frame", "last-frame", "annotation")
KINDS = ("image", "video", "audio")
TASK_TYPES = ("auto", "text", "reference", "first-frame", "first-last", "edit", "extend")
RESOLUTIONS = ("480p", "720p", "1080p")
ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive")

# 面板本地标签是 @图片N/@视频N/@音频N；提交方舟时编译为官方 @图像N/@视频N/@音频N。
KIND_PREFIX_ARK = {"image": "图像", "video": "视频", "audio": "音频"}
KIND_PREFIX_KIE = {"image": "Image", "video": "Video", "audio": "Audio"}


@dataclass
class SeedanceAsset:
    kind: str                 # image | video | audio
    role: str                 # 见 ROLES
    url: str = ""             # 归一化后的地址（本地文件路径先经 ark_media 归一化）
    label: str = ""           # 面板本地标签，如 @图片1
    timestamp_seconds: float | None = None  # 仅 role=annotation：抽帧时刻（秒）


@dataclass
class SeedanceJobSpec:
    task_type: str
    prompt: str
    assets: list[SeedanceAsset] = field(default_factory=list)
    duration: int = 10        # 4-30 整数或 -1（自适应）
    resolution: str = "720p"
    aspect_ratio: str = "9:16"
    generate_audio: bool = True
    output_format: str = "mp4"
    return_last_frame: bool = False
