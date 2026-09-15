"""Ariadne · Google Omni 1.1（Kie 渠道）：参考素材视频 + 首尾帧过渡。

契约移植自本机实测基线 ComfyUI-Kie omni_node.py（真实出片验证）；固定角色ID 可直接连
ComfyUI-Kie 包「Kie · 创建固定角色」节点的输出（不再重复造角色节点）。
提示词占位符：<IMAGE_REF_N>/<VIDEO_REF_0>/<CHARACTER_ID_0> 由节点按输入构成自动前置。
"""
from __future__ import annotations

from pathlib import Path

from ariadne_core import config, kie as kie_core, media
from ariadne_core.http import request_bytes
from ariadne_core import omni as omni_core

DEFAULT_FASHION_PROMPT_EN = """A realistic, premium fashion-travel short film for womenswear.

[Character and wardrobe] The fixed character ID and character reference image are the sole authority for identity, face, body proportions, hairstyle, and the complete outfit. Keep the garment silhouette, colors, fabric, pattern, footwear, socks, bag, and accessories consistent throughout. Do not replace, remove, or add any wardrobe item.

[Locations] The supplied scene-reference images are the only sources of locations in the film. Change locations only at scene cuts specified by the automatic shot plan. Within each shot, keep the location, architecture, surroundings, time of day, and lighting continuous. Never copy the location, architecture, road, vehicles, people, wardrobe, or lighting of the motion-reference video.

[Camera movement] The motion-reference video is the highest authority for camera language. Preserve its visible camera height, tracking direction, push-in or pull-back rhythm, natural lateral movement, subtle handheld breathing, and settling inertia. Do not turn a reference with authentic breathing into a rigid gimbal shot; do not copy its real location or composition. When the location changes, adapt the same camera language to the new location.

[Image quality] Real photographic texture. Keep garment texture, stitching, and silhouette crisp. No text, logo, watermark, or additional main subject."""


def _default_download_folder():
    try:
        import folder_paths

        return str(Path(folder_paths.get_output_directory()) / "ariadne")
    except ImportError:
        return str(Path.cwd() / "output" / "ariadne")


def _format_estimate(estimate: dict | None) -> str | None:
    if estimate is None:
        return None
    text = f"预估积分: {estimate['credits']}（≈${estimate['usd']} / ¥{estimate['cny']}）"
    if estimate.get("rounded_up_duration"):
        text += f"，时长取上一档 {estimate['rounded_up_duration']}s"
    if estimate.get("upper_bound"):
        text += "，仅连图片按带视频档上界"
    return text


def _download_result(urls: list[str], destination: Path, task_id: str) -> str:
    video_url = urls[0]
    suffix = Path(video_url.split("?", 1)[0]).suffix or ".mp4"
    local_path = destination / f"Omni版_{task_id}{suffix}"
    local_path.write_bytes(request_bytes("GET", video_url, phase="下载成片"))
    return str(local_path)


class AriadneOmniVideo:
    """Ariadne · Omni 1.1 参考素材视频（Kie）：人物/场景/动作/固定角色四路输入"""

    CATEGORY = "1、Ariadne/视频"
    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("视频", "任务信息")
    FUNCTION = "generate"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": DEFAULT_FASHION_PROMPT_EN, "defaultInput": True}),
                "video_start_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "step": 0.1}),
                "video_end_seconds": ("FLOAT", {"default": 10.0, "min": 0.1, "step": 0.1}),
                "duration": (list(omni_core.DURATIONS), {"default": "10", "tooltip": "输出时长（秒）。连参考视频时模型可能自行决定实际输出时长。"}),
                "aspect_ratio": (list(omni_core.ASPECTS), {"default": "9:16"}),
                "resolution": (list(omni_core.RESOLUTIONS), {"default": "1080p"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647, "tooltip": "0 = 系统自动种子；大于 0 = 固定种子。"}),
                "download_folder": ("STRING", {"default": _default_download_folder()}),
            },
            "optional": {
                "reference_image": ("IMAGE", {"tooltip": "人物 + 服装参考（第一张，IMAGE_REF_0）。"}),
                "scene_reference_image": ("IMAGE", {"tooltip": "场景参考（可多张，按连接顺序编号）。"}),
                "reference_video": ("VIDEO", {"tooltip": "动作/运镜参考视频（1 段），配合起止秒使用。"}),
                "固定角色ID": ("STRING", {"default": "", "forceInput": True, "tooltip": "连接 ComfyUI-Kie 包「Kie · 创建固定角色」的角色ID输出，锁定人物身份。"}),
                "poll_interval_seconds": ("INT", {"default": 5, "min": 2, "max": 60}),
                "timeout_seconds": ("INT", {"default": 1800, "min": 60, "max": 7200}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 付费副作用任务：必须真实重跑，严禁缓存回放（避坑手册 #1）。
        return float("NaN")

    def generate(
        self, prompt, video_start_seconds, video_end_seconds, duration, aspect_ratio,
        resolution, seed, download_folder, reference_image=None, scene_reference_image=None,
        reference_video=None, 固定角色ID="", poll_interval_seconds=5, timeout_seconds=1800,
    ):
        if not str(prompt or "").strip():
            raise RuntimeError("提示词不能为空。")
        if video_end_seconds <= video_start_seconds:
            raise RuntimeError("video_end_seconds 必须大于 video_start_seconds。")
        api_key = config.resolve_kie_key()

        image_urls: list[str] = []
        if reference_image is not None:
            image_urls.append(kie_core.upload_to_kie("image", media.image_to_file(reference_image), api_key))
        scene_paths = media.images_to_files(scene_reference_image) if scene_reference_image is not None else []
        for scene_path in scene_paths:
            image_urls.append(kie_core.upload_to_kie("image", scene_path, api_key))
        video_list = []
        if reference_video is not None:
            video_list.append({
                "url": kie_core.upload_to_kie("video", media.video_to_file(reference_video), api_key),
                "start": float(video_start_seconds),
                "ends": float(video_end_seconds),
            })
        character_ids = [str(固定角色ID).strip()] if str(固定角色ID or "").strip() else []

        input_data = omni_core.compile_input(
            prompt, aspect_ratio, resolution, str(duration),
            has_character=reference_image is not None,
            scene_count=len(scene_paths),
            has_video=bool(video_list),
            has_character_id=bool(character_ids),
            image_urls=image_urls, character_ids=character_ids, video_list=video_list,
            seed=int(seed),
        )
        estimate = omni_core.estimate_omni(int(duration), resolution, bool(video_list), bool(image_urls))

        task_id = kie_core.create_task({"model": omni_core.MODEL, "input": input_data}, api_key, phase="创建 Omni 任务")
        result = kie_core.poll_task(task_id, api_key, poll_interval_seconds, timeout_seconds, progress=print)
        urls = result["resultUrls"]
        if not urls:
            raise RuntimeError("Omni 任务成功但未返回视频地址。")

        destination = Path(download_folder).expanduser() if str(download_folder).strip() else Path(_default_download_folder())
        destination.mkdir(parents=True, exist_ok=True)
        local_path = _download_result(urls, destination, task_id)

        from comfy_api.latest import InputImpl

        info = [
            f"Ariadne · Omni 1.1 完成（任务ID: {task_id}）",
            f"本地文件: {local_path}",
        ]
        estimate_text = _format_estimate(estimate)
        if estimate_text:
            info.append(estimate_text)
        if result.get("remainedCredits") is not None:
            info.append(f"剩余积分: {result['remainedCredits']}")
        return {"ui": {"text": [urls[0], local_path]}, "result": (InputImpl.VideoFromFile(local_path), "\n".join(info))}


class AriadneOmniFirstLastFrame:
    """Ariadne · Omni 1.1 首尾帧过渡（Kie）：首帧必填、尾帧可选"""

    CATEGORY = "1、Ariadne/视频"
    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("视频", "任务信息")
    FUNCTION = "generate"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "", "defaultInput": True, "tooltip": "描述两帧之间的过渡动作。"}),
                "duration": (list(omni_core.DURATIONS), {"default": "10"}),
                "aspect_ratio": (list(omni_core.ASPECTS), {"default": "9:16"}),
                "resolution": (list(omni_core.RESOLUTIONS), {"default": "1080p"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647}),
                "download_folder": ("STRING", {"default": _default_download_folder()}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧（必填）。"}),
                "last_frame": ("IMAGE", {"tooltip": "尾帧（可选）。"}),
                "poll_interval_seconds": ("INT", {"default": 5, "min": 2, "max": 60}),
                "timeout_seconds": ("INT", {"default": 1800, "min": 60, "max": 7200}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def generate(
        self, prompt, duration, aspect_ratio, resolution, seed, download_folder,
        first_frame=None, last_frame=None, poll_interval_seconds=5, timeout_seconds=1800,
    ):
        if not str(prompt or "").strip():
            raise RuntimeError("提示词不能为空。")
        if first_frame is None:
            raise RuntimeError("首尾帧过渡必须提供 first_frame。")
        api_key = config.resolve_kie_key()
        first_url = kie_core.upload_to_kie("image", media.image_to_file(first_frame), api_key)
        last_url = kie_core.upload_to_kie("image", media.image_to_file(last_frame), api_key) if last_frame is not None else ""

        input_data = omni_core.compile_input(
            prompt, aspect_ratio, resolution, str(duration),
            first_frame_url=first_url, last_frame_url=last_url, seed=int(seed),
        )
        estimate = omni_core.estimate_omni(int(duration), resolution, False, False)

        task_id = kie_core.create_task({"model": omni_core.MODEL, "input": input_data}, api_key, phase="创建 Omni 首尾帧任务")
        result = kie_core.poll_task(task_id, api_key, poll_interval_seconds, timeout_seconds, progress=print)
        urls = result["resultUrls"]
        if not urls:
            raise RuntimeError("Omni 任务成功但未返回视频地址。")

        destination = Path(download_folder).expanduser() if str(download_folder).strip() else Path(_default_download_folder())
        destination.mkdir(parents=True, exist_ok=True)
        local_path = _download_result(urls, destination, task_id)

        from comfy_api.latest import InputImpl

        info = [
            f"Ariadne · Omni 1.1 首尾帧完成（任务ID: {task_id}）",
            f"本地文件: {local_path}",
        ]
        estimate_text = _format_estimate(estimate)
        if estimate_text:
            info.append(estimate_text)
        if result.get("remainedCredits") is not None:
            info.append(f"剩余积分: {result['remainedCredits']}")
        return {"ui": {"text": [urls[0], local_path]}, "result": (InputImpl.VideoFromFile(local_path), "\n".join(info))}


NODE_CLASS_MAPPINGS = {
    "AriadneOmniVideo": AriadneOmniVideo,
    "AriadneOmniFirstLastFrame": AriadneOmniFirstLastFrame,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "AriadneOmniVideo": "Ariadne · Omni 1.1 参考素材视频（Kie）",
    "AriadneOmniFirstLastFrame": "Ariadne · Omni 1.1 首尾帧过渡（Kie）",
}
