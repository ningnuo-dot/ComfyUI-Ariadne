"""Ariadne · 可灵 Kling 3.0 视频生成（Kie 聚合路径，画布 kling 契约层移植）。

特色能力：@元素名 角色元素（图片 2-4 张或视频 1 段）、1-6 shot 多镜头编排。
元素/分镜 v0.1 以 JSON widget 传入（前端编辑器后续补齐）；提示词用 `@名字` 引用元素。
"""
from __future__ import annotations

import json
from pathlib import Path

from ariadne_core import config, kie as kie_core, media
from ariadne_core.http import request_bytes
from ariadne_core import kling as kling_core


def _default_download_folder():
    try:
        import folder_paths

        return str(Path(folder_paths.get_output_directory()) / "ariadne")
    except ImportError:
        return str(Path.cwd() / "output" / "ariadne")


def _json_of(value: str, field: str) -> list:
    try:
        parsed = json.loads(value or "[]")
    except ValueError:
        raise RuntimeError(f"{field} 不是合法的 JSON 数组。")
    if not isinstance(parsed, list):
        # 非数组静默当空会把元素全丢、任务照发照扣费——必须显式报错。
        raise RuntimeError(f"{field} 必须是 JSON 数组（[]），当前为 {type(parsed).__name__}。")
    return parsed


class AriadneKlingVideo:
    """Ariadne · 可灵 Kling 3.0 视频生成（Kie：文生/首帧/首尾帧/全能参考元素/多镜头）"""

    CATEGORY = "1、Ariadne/视频"
    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("视频", "任务信息")
    OUTPUT_NODE = True
    FUNCTION = "generate"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 视频生成是外部付费副作用：工作流含本节点并 Queue 时必须真实重跑，
        # 严禁静默命中缓存回放旧成片（避坑手册 #1：NaN = 永远视为已更改；禁用优化是有意为之）。
        return float("NaN")


    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "", "defaultInput": True,
                                      "tooltip": "描述画面；元素用 @元素名 引用（名字即 kling_elements 里的 name）。多镜头模式不发送本字段。"}),
                "task_type": (["text(文生视频)", "first-frame(首帧)", "first-last(首尾帧)", "omni(全能参考)", "multi-shot(多镜头)"], {"default": "text(文生视频)"}),
                "duration": ("INT", {"default": 5, "min": 3, "max": 15, "tooltip": "3-15 秒；多镜头模式自动取各镜头之和"}),
                "aspect_ratio": (["16:9", "9:16", "1:1"], {"default": "9:16"}),
                "sound": ("BOOLEAN", {"default": True, "tooltip": "是否生成音频（Kie 只有开关；官方 original 三态属直连路径）"}),
                "quality_mode": (["std", "pro"], {"default": "std"}),
                "download_folder": ("STRING", {"default": _default_download_folder()}),
                "kling_elements": ("STRING", {"default": "[]", "multiline": True,
                                              "tooltip": "角色元素 JSON 数组：[{\"name\":\"角色1\",\"imageUrls\":[...] 或 \"videoUrl\":\"...\", \"description\":\"...\"}]；提示词用 @角色1 引用"}),
                "kling_shots": ("STRING", {"default": "[]", "multiline": True,
                                           "tooltip": "多镜头分镜 JSON 数组（2-5 个）：[{\"prompt\":\"...\",\"duration\":5}]；总时长 = 各镜头之和"}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧（多镜头模式作为 image_urls[0]）"}),
                "last_frame": ("IMAGE", {"tooltip": "尾帧（仅首尾帧模式；顺序语义待官方验证）"}),
                "poll_interval_seconds": ("INT", {"default": 5, "min": 2, "max": 60}),
                "timeout_seconds": ("INT", {"default": 1800, "min": 60, "max": 7200}),
            },
        }

    def generate(
        self, prompt, task_type, duration, aspect_ratio, sound, quality_mode, download_folder,
        kling_elements="[]", kling_shots="[]", first_frame=None, last_frame=None,
        poll_interval_seconds=5, timeout_seconds=1800,
    ):
        task_type = str(task_type).split("(")[0].strip()
        api_key = config.resolve_kie_key()

        first_url = last_url = ""
        if first_frame is not None:
            first_url = kie_core.upload_to_kie("image", media.image_to_file(first_frame), api_key)
        if last_frame is not None:
            last_url = kie_core.upload_to_kie("image", media.image_to_file(last_frame), api_key)

        elements = _json_of(kling_elements, "kling_elements")
        # 元素里的本地文件路径（{"localPath": ...}）自动上传 Kie；公网 URL 直用。
        video_exts = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi")
        image_exts = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic")
        for element in elements:
            local = str(element.get("localPath") or "")
            if local:
                ext = local.lower().rsplit(".", 1)[-1]
                if f".{ext}" in video_exts:
                    element["videoUrl"] = kie_core.upload_to_kie("video", local, api_key)
                elif f".{ext}" in image_exts:
                    element["imageUrls"] = [kie_core.upload_to_kie("image", local, api_key)]  # imageUrls 必须是数组
                else:
                    raise RuntimeError(f"元素素材 {local} 扩展名不在支持清单（图片 {image_exts} / 视频 {video_exts}）。")
        shots = _json_of(kling_shots, "kling_shots")

        spec = {
            "taskType": task_type, "prompt": prompt, "firstFrameUrl": first_url,
            "lastFrameUrl": last_url, "elements": elements, "shots": shots,
            "duration": int(duration), "aspectRatio": aspect_ratio,
            "sound": bool(sound), "qualityMode": quality_mode,
        }
        kling_core.validate_job(spec)
        body = kling_core.compile_request(spec)
        result = kling_core.run_kling(body, api_key, poll_interval_seconds=poll_interval_seconds,
                                      timeout_seconds=timeout_seconds, progress=print)

        destination = Path(download_folder).expanduser() if str(download_folder).strip() else Path(_default_download_folder())
        destination.mkdir(parents=True, exist_ok=True)
        video_url = result["videoUrl"]
        local_path = destination / f"Kling_{result['taskId']}.mp4"
        local_path.write_bytes(request_bytes("GET", video_url, phase="下载成片"))

        from comfy_api.latest import InputImpl

        estimate = kling_core.estimate_kie(int(body["input"]["duration"]))  # 多镜头=Σ镜头，与实扣一致
        info = [
            f"可灵 Kling 3.0 完成（{task_type}）",
            f"任务ID: {result['taskId']}",
            f"本地文件: {local_path}",
            f"预估费用: {estimate['credits']} credits ≈ ${estimate['usd']} / ¥{estimate['cny']}（以账单为准）",
        ]
        return {"ui": {"text": [video_url, str(local_path)]}, "result": (InputImpl.VideoFromFile(str(local_path)), "\n".join(info))}


NODE_CLASS_MAPPINGS = {"AriadneKlingVideo": AriadneKlingVideo}
NODE_DISPLAY_NAME_MAPPINGS = {"AriadneKlingVideo": "Ariadne · 可灵 Kling 3.0 视频生成（Kie）"}
