"""Ariadne · 一瞬入画（instant painting）：多帧参考 → 高保真场景图（gpt-image-2，Kie 渠道）。

移植自画布插件 tools/instant-painting（与本地 CLI 技能同一套已验证流程）。参考来源双入口：
连接 VIDEO 自动按范围均匀抽帧，或直接连 IMAGE 参考图；保真提示词模板由节点按模式生成。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ariadne_core import config, instant, kie as kie_core, media
from ariadne_core.http import request_bytes

FRAME_OUT_CAP = 8


def _default_download_folder():
    try:
        import folder_paths

        return str(Path(folder_paths.get_output_directory()) / "ariadne")
    except ImportError:
        return str(Path.cwd() / "output" / "ariadne")


def _tensor_from_png(path: str):
    import torch
    from PIL import Image

    array = np.asarray(Image.open(path).convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(array)[None,]


class AriadneInstantPainting:
    """Ariadne · 一瞬入画（视频/多图 → 高保真场景图）"""

    CATEGORY = "Ariadne/图像"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("图像", "任务信息")
    OUTPUT_NODE = True
    FUNCTION = "generate"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["scene(无人物纯场景)", "keep_people(保持人口构成)"], {"default": "scene(无人物纯场景)"}),
                "aspect_ratio": (list(instant.ASPECTS), {"default": "9:16"}),
                "quality": (list(instant.QUALITIES), {"default": "2K", "tooltip": f"费用参考：2K {instant.CREDITS_HINT['2K']} / 4K {instant.CREDITS_HINT['4K']}（以账单为准）"}),
                "extra_note": ("STRING", {"multiline": True, "default": "", "tooltip": "追加约束（会拼进保真提示词的 Extra user constraints）"}),
                "download_folder": ("STRING", {"default": _default_download_folder()}),
            },
            "optional": {
                "reference_video": ("VIDEO", {"tooltip": "参考视频：按下方起止秒均匀抽帧作为多帧参考。"}),
                "video_start_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "step": 0.1}),
                "video_end_seconds": ("FLOAT", {"default": 10.0, "min": 0.1, "step": 0.1}),
                "frame_count": ("INT", {"default": 4, "min": 1, "max": FRAME_OUT_CAP, "tooltip": "抽帧数量（1-8，均匀取中点帧）。"}),
                "reference_images": ("IMAGE", {"tooltip": "补充参考图（可多张，排在抽帧之后）。"}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def generate(
        self, mode, aspect_ratio, quality, extra_note, download_folder,
        reference_video=None, video_start_seconds=0.0, video_end_seconds=10.0,
        frame_count=4, reference_images=None, poll_interval_seconds=5, timeout_seconds=1800,
    ):
        mode = str(mode).split("(")[0].strip()
        api_key = config.resolve_kie_key()

        ref_paths: list[str] = []
        if reference_video is not None:
            video_path = media.video_to_file(reference_video)
            ref_paths.extend(media.extract_video_frames(
                video_path, float(video_start_seconds), float(video_end_seconds),
                int(frame_count), str(media.temp_dir()),
            ))
        if reference_images is not None:
            ref_paths.extend(media.images_to_files(reference_images))
        if not ref_paths:
            raise RuntimeError("至少需要 1 张参考：连接 reference_video（自动抽帧）或 reference_images。")

        prompt = instant.build_fidelity_prompt(aspect_ratio, mode, extra_note, len(ref_paths))
        urls = [kie_core.upload_to_kie("image", path, api_key) for path in ref_paths]
        input_data = instant.compile_input(urls, prompt, aspect_ratio, quality)

        task_id = kie_core.create_task({"model": instant.MODEL, "input": input_data}, api_key, phase="创建一瞬入画任务")
        result = kie_core.poll_task(task_id, api_key, poll_interval_seconds, timeout_seconds, progress=print)
        result_urls = result["resultUrls"]
        if not result_urls:
            raise RuntimeError("一瞬入画任务成功但未返回图片地址。")

        destination = Path(download_folder).expanduser() if str(download_folder).strip() else Path(_default_download_folder())
        destination.mkdir(parents=True, exist_ok=True)
        tensors = []
        for index, url in enumerate(result_urls[:4]):  # 最多取 4 张，防止批量过大
            suffix = Path(url.split("?", 1)[0]).suffix or ".png"
            local_path = destination / f"一瞬入画_{task_id}_{index}{suffix}"
            local_path.write_bytes(request_bytes("GET", url, phase="下载图片"))
            tensors.append(_tensor_from_png(str(local_path)))
        import torch

        image_output = torch.cat(tensors, dim=0) if len(tensors) > 1 else tensors[0]

        info = [
            f"一瞬入画完成（{mode} / {aspect_ratio} / {quality}，参考 {len(ref_paths)} 张）",
            f"任务ID: {task_id}",
            f"结果图: {len(tensors)} 张（已落 output/ariadne/）",
            f"参考费用: {instant.CREDITS_HINT.get(quality, '--')}（以账单为准）",
        ]
        return {"ui": {"text": [result_urls[0], str(destination)]}, "result": (image_output, "\n".join(info))}


NODE_CLASS_MAPPINGS = {"AriadneInstantPainting": AriadneInstantPainting}
NODE_DISPLAY_NAME_MAPPINGS = {"AriadneInstantPainting": "Ariadne · 一瞬入画（视频/多图 → 场景图）"}
