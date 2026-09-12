"""Ariadne · Kie 图生图（摆拍/场景五家服务商，visual-pro providers 注册表移植）。

服务商差异（字段名跨模型不通用，组装必须查注册表）：
nano 系 → image_input；seedream/grok → image_urls；gpt-image 系 → input_urls。
分辨率参数：nano/gpt-image → resolution；seedream → quality；grok 无。
真实出片由用户扣费实测；除 nano-banana-pro 外均待验证（2026-09-10 登记）。
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np

from ariadne_core import config, kie as kie_core
from ariadne_core import providers
from ariadne_core.http import request_bytes, request_json

_ASPECT_UNION = sorted({aspect for provider in providers.PROVIDERS.values() for aspect in provider["aspects"]})


def _default_download_folder():
    try:
        import folder_paths

        return str(Path(folder_paths.get_output_directory()) / "ariadne")
    except ImportError:
        return str(Path.cwd() / "output" / "ariadne")


class AriadneKieImage:
    """Ariadne · Kie 图生图（nano-banana-pro 默认 / seedream / grok / gpt-image）"""

    CATEGORY = "Ariadne/图像"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("图像", "任务信息")
    OUTPUT_NODE = True
    FUNCTION = "generate"

    @classmethod
    def INPUT_TYPES(cls):
        platforms = list(providers.PROVIDERS)
        return {
            "required": {
                "platform": (platforms, {"default": providers.DEFAULT_PLATFORM}),
                "prompt": ("STRING", {"multiline": True, "default": "", "defaultInput": True}),
                "aspect_ratio": (_ASPECT_UNION, {"default": "9:16"}),
                "resolution": (["1K", "2K", "4K", "basic", "high"], {"default": "2K"}),
                "download_folder": ("STRING", {"default": _default_download_folder()}),
            },
            "optional": {
                "reference_images": ("IMAGE", {"tooltip": "参考图（张数上限随服务商：nano-pro 8 / seedream 10 / grok 5 / gpt-image 16）"}),
            },
        }

    def generate(self, platform, prompt, aspect_ratio, resolution, download_folder, reference_images=None):
        provider = providers.get_provider(platform)
        api_key = config.resolve_kie_key()
        aspect = providers.resolve_aspect(provider, aspect_ratio)
        submit_resolution = providers.resolve_resolution(provider, resolution)

        input_data: dict = {"prompt": prompt.strip()}
        if not input_data["prompt"]:
            raise RuntimeError("提示词不能为空。")
        input_data["aspect_ratio"] = aspect

        if reference_images is not None:
            paths = media_images(reference_images)
            limit = provider["ref_limit"]
            if len(paths) > limit:
                raise RuntimeError(f"{provider['label']} 参考图最多 {limit} 张，当前 {len(paths)} 张。")
            urls = [kie_core.upload_to_kie("image", path, api_key) for path in paths]
            if urls:
                input_data[provider["ref_field"]] = urls
        if submit_resolution:
            input_data[provider["resolution_field"]] = submit_resolution
        input_data.update(provider.get("extra") or {})

        body = {"model": provider["model"], "input": input_data}
        task_id = kie_core.create_task(body, api_key, phase=f"创建 {provider['label']} 任务")
        result = kie_core.poll_task(task_id, api_key, progress=print)
        urls = result["resultUrls"]
        if not urls:
            raise RuntimeError(f"{provider['label']} 任务成功但未返回图片地址。")

        destination = Path(download_folder).expanduser() if str(download_folder).strip() else Path(_default_download_folder())
        destination.mkdir(parents=True, exist_ok=True)
        local_path = destination / f"Ariadne图_{provider['key']}_{task_id}.png"
        local_path.write_bytes(request_bytes("GET", urls[0], phase="下载图片"))

        from PIL import Image

        image = Image.open(io.BytesIO(local_path.read_bytes())).convert("RGB")
        tensor = torch_from_image(image)
        info = [
            f"{provider['label']} 完成",
            f"任务ID: {task_id}",
            f"本地文件: {local_path}",
            f"参考费用: {provider['credits_hint']}（以账单为准）",
        ]
        return {"ui": {"text": [urls[0], str(local_path)]}, "result": (tensor, "\n".join(info))}


def media_images(images):
    from ariadne_core.media import images_to_files

    return images_to_files(images)


def torch_from_image(pil_image):
    import torch
    from PIL import Image

    array = np.asarray(pil_image.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(array)[None,]


NODE_CLASS_MAPPINGS = {"AriadneKieImage": AriadneKieImage}
NODE_DISPLAY_NAME_MAPPINGS = {"AriadneKieImage": "Ariadne · Kie 图生图"}
