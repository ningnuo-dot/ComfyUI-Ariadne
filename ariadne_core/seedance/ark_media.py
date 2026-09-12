"""方舟素材地址归一化（画布插件 ark-media.ts 的服务端 Python 版）。

服务端素材来自本机文件路径（input 目录/临时文件）：
- 图片/音频：≤上限直接 Base64 data URL；超限走 TOS 上传拿公网 URL
- 视频：官方只认公网 http(s) 或 asset://，必须走 TOS（未配 TOS 给可操作报错）
- 公网 http(s)/data:/asset:// 地址原样放行
"""
from __future__ import annotations

import base64
import mimetypes
import os
import re
import time
import uuid

MAX_BYTES = {"image": 30 * 1024 * 1024, "audio": 15 * 1024 * 1024}
MIN_VIDEO_PIXELS = 407696  # 官方实测拦截线（480×854 起可过）

_LOCAL_HOST = re.compile(r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:\d+)?", re.IGNORECASE)


def is_public_http_url(url: str) -> bool:
    return bool(re.match(r"^https?://", url, re.IGNORECASE)) and not _LOCAL_HOST.match(url)


def is_ark_asset_id(url: str) -> bool:
    return bool(re.match(r"^asset://", url, re.IGNORECASE))


def is_local_path(url: str) -> bool:
    """本机文件路径（input 目录相对名或绝对路径）；data:/http(s)/asset: 都不是。"""
    return bool(url) and not re.match(r"^(https?://|data:|asset:)", url, re.IGNORECASE) and not _LOCAL_HOST.match(url)


def probe_video(path: str) -> dict:
    """用 PyAV 探测视频宽高/时长（秒）；失败抛中文错误。"""
    try:
        import av

        with av.open(path) as container:
            stream = container.streams.video[0]
            width, height = stream.codec_context.width, stream.codec_context.height
            duration = float(container.duration) / 1_000_000 if container.duration else 0.0
        return {"width": width, "height": height, "seconds": round(duration, 1), "pixels": width * height}
    except Exception as error:  # noqa: BLE001 - 统一翻译成可操作提示
        raise RuntimeError(f"无法读取视频信息（{os.path.basename(path)}）：{error}") from error


def validate_video_pixels(path: str, label: str) -> dict:
    """用文件实际尺寸校验参考视频像素下限（官方 407696 拦截线）。"""
    info = probe_video(path)
    if info["pixels"] < MIN_VIDEO_PIXELS:
        raise RuntimeError(
            f"{label} 参考视频尺寸过小：{info['width']}×{info['height']} = {info['pixels']} 像素，"
            f"至少需要 {MIN_VIDEO_PIXELS} 像素。请等比例放大视频并重新导入，例如竖屏 480×854、"
            "横屏 854×480；修改输出分辨率无效。"
        )
    return info


def _data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode()
    return f"data:{mime};base64,{encoded}"


def _unique_tos_key(url: str) -> str:
    """TOS 对象 key 带毫秒时间戳 + 随机段：同名素材互不覆盖（Kie 撞名多图坍缩事故的同型根因）。"""
    return f"seedance/{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}-{os.path.basename(url)}"


def to_ark_safe_url(url: str, kind: str, tos_settings: dict | None) -> str:
    """把素材地址归一化为方舟可接受形式；本地文件路径在服务端上传/内联。"""
    if not url:
        return url
    if is_public_http_url(url) or url.startswith("data:") or is_ark_asset_id(url):
        return url
    if not os.path.isfile(url):
        raise RuntimeError(f"素材文件不存在：{url}。请重新导入素材后重试。")
    size = os.path.getsize(url)
    if kind == "video":
        if not tos_settings or not tos_settings.get("accessKey"):
            raise RuntimeError(
                "参考视频必须提供公网 http(s) URL（官方不支持 Base64）。请在 Ariadne 工作台配置 TOS "
                "（对象存储）AK/SK 与桶名后重试；或把视频上传到公网地址后直接填 URL。"
            )
        from ..tos import upload_file

        return upload_file(tos_settings, _unique_tos_key(url), url)
    limit = MAX_BYTES.get(kind, MAX_BYTES["image"])
    label = {"audio": "音频"}.get(kind, "图片")
    if tos_settings and tos_settings.get("accessKey"):
        from ..tos import upload_file

        try:
            return upload_file(tos_settings, _unique_tos_key(url), url)
        except Exception as error:  # noqa: BLE001 - TOS 故障时小图/音频回退 Base64（与画布版一致）
            if size <= limit:
                return _data_url(url)
            raise RuntimeError(
                f"{label}素材上传 TOS 失败且 {size / 1024 / 1024:.1f}MB 超过内联上限 "
                f"{limit // 1024 // 1024}MB，无法回退 Base64。原始错误：{error}"
            ) from error
    if size > limit:
        raise RuntimeError(
            f"{label}素材 {size / 1024 / 1024:.1f}MB，超过内联上限 {limit // 1024 // 1024}MB。"
            "请在 Ariadne 工作台配置 TOS，或改用更小的素材。"
        )
    return _data_url(url)
