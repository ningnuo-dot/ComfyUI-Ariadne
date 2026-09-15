"""Ariadne · Veo 3.1 视频生成（Kie 专属端点族，画布 veo-3-1 契约层移植）。

参考素材只支持图片（1-3 张）；不支持视频/音频参考。任务成功必须未做过 1080P 升级才能延长。
"""
from __future__ import annotations

from pathlib import Path

from ariadne_core import config, kie as kie_core, media
from ariadne_core.http import request_bytes
from ariadne_core import veo31

MODELS = ["veo3(质量)", "veo3_fast(均衡)", "veo3_lite(经济)"]


def _model_of(value: str) -> str:
    return str(value or "veo3").split("(")[0].strip()


def _default_download_folder():
    try:
        import folder_paths

        return str(Path(folder_paths.get_output_directory()) / "ariadne")
    except ImportError:
        return str(Path.cwd() / "output" / "ariadne")


class AriadneVeo31Video:
    """Ariadne · Veo 3.1 视频生成（Kie：文生/首尾帧/全能参考/延长）"""

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
                                      "tooltip": "Veo 无官方素材编号语法，提示词原样发送；素材经 imageUrls 按序传入。"}),
                "task_type": (["text(文生视频)", "first-last(首尾帧)", "reference(全能参考)", "extend(延长)"], {"default": "text(文生视频)"}),
                "model": (MODELS, {"default": MODELS[1]}),
                "duration": (["4", "6", "8"], {"default": "8"}),
                "resolution": (["720p", "1080p", "4k"], {"default": "1080p"}),
                "aspect_ratio": (["16:9", "9:16", "Auto"], {"default": "16:9"}),
                "watermark": ("STRING", {"default": "", "tooltip": "官方 watermark 字段是「加水印的文字」；留空 = 不加水印（成片禁止水印）"}),
                "download_folder": ("STRING", {"default": _default_download_folder()}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首尾帧模式：第一张为首帧（顺序语义待官方验证）"}),
                "last_frame": ("IMAGE", {"tooltip": "尾帧（仅首尾帧模式）"}),
                "reference_images": ("IMAGE", {"tooltip": "全能参考图（1-3 张，JPG/PNG/WebP）"}),
                "extend_task_id": ("STRING", {"default": "", "tooltip": "延长模式必填：/api/v1/veo/generate 创建的原任务 ID，且未做过 1080P 升级"}),
                "extend_seeds": ("INT", {"default": 0, "min": 0, "max": 99999, "tooltip": "仅延长：10000-99999，同种子结果相近；0 = 随机"}),
                "poll_interval_seconds": ("INT", {"default": 5, "min": 2, "max": 60}),
                "timeout_seconds": ("INT", {"default": 1800, "min": 60, "max": 7200}),
            },
        }

    def generate(
        self, prompt, task_type, model, duration, resolution, aspect_ratio, watermark,
        download_folder, first_frame=None, last_frame=None, reference_images=None,
        extend_task_id="", extend_seeds=0, poll_interval_seconds=5, timeout_seconds=1800,
    ):
        task_type = str(task_type).split("(")[0].strip()
        model = _model_of(model)
        if not str(prompt or '').strip():
            raise RuntimeError("提示词不能为空。")
        api_key = config.resolve_kie_key()

        assets: list[dict] = []
        if task_type == "first-last":
            if first_frame is None:
                raise RuntimeError("首尾帧模式需要连接 first_frame。")
            if last_frame is None:
                raise RuntimeError("首尾帧模式同时需要 last_frame（只连首帧请改用图生视频任务类型）。")
            assets.append({"url": kie_core.upload_to_kie("image", media.image_to_file(first_frame), api_key)})
            if last_frame is not None:
                assets.append({"url": kie_core.upload_to_kie("image", media.image_to_file(last_frame), api_key)})
        elif task_type == "reference":
            if reference_images is None:
                raise RuntimeError("全能参考模式需要连接 reference_images（1-3 张）。")
            paths = media.images_to_files(reference_images)
            if not 1 <= len(paths) <= 3:
                raise RuntimeError(f"Veo 全能参考只支持 1-3 张参考图，当前 {len(paths)} 张。")
            for path in paths:
                assets.append({"url": kie_core.upload_to_kie("image", path, api_key)})
        elif task_type == "text":
            if first_frame is not None or last_frame is not None or reference_images is not None:
                raise RuntimeError("文生视频模式不能连接任何参考素材；请切换任务类型或移除连线。")
        elif task_type == "extend":
            if first_frame is not None or last_frame is not None or reference_images is not None:
                raise RuntimeError("延长模式不接收参考素材（延长的是来源任务的成片）；请移除素材连线。")
        # 反向组合：首尾帧误连参考图 / 全能参考误连首尾帧
        if task_type == "first-last" and reference_images is not None:
            raise RuntimeError("首尾帧模式不接收 reference_images；请改用全能参考模式。")
        if task_type == "reference" and (first_frame is not None or last_frame is not None):
            raise RuntimeError("全能参考模式不接收首帧/尾帧；请把参考图连到 reference_images。")

        spec = {
            "taskType": task_type, "prompt": prompt, "assets": assets, "model": model,
            "duration": int(duration), "resolution": resolution, "aspectRatio": aspect_ratio,
            "watermark": watermark, "extendTaskId": extend_task_id,
            "extendSeeds": int(extend_seeds) if 10000 <= int(extend_seeds) <= 99999 else None,
        }
        is_extend = task_type == "extend"
        body = veo31.compile_extend_request(spec) if is_extend else veo31.compile_generate_request(spec)
        result = veo31.run_veo(body, is_extend, api_key, poll_interval_seconds, timeout_seconds, progress=print)

        destination = Path(download_folder).expanduser() if str(download_folder).strip() else Path(_default_download_folder())
        destination.mkdir(parents=True, exist_ok=True)
        video_url = result["videoUrl"]
        local_path = destination / f"Veo31_{result['taskId']}.mp4"
        local_path.write_bytes(request_bytes("GET", video_url, phase="下载成片"))

        from comfy_api.latest import InputImpl

        credits = veo31.estimate_veo_credits(task_type, model, resolution)
        info = [
            f"Veo 3.1 完成（{task_type} / {model} / {resolution}）",
            f"任务ID: {result['taskId']}",
            f"本地文件: {local_path}",
        ]
        if credits is None:
            info.append("预估积分: --（价目表未列出该组合，可能不受支持；以账单为准）")
        else:
            info.append(f"预估积分: {credits}（≈${credits * 0.005:.3f}，以账单为准）")
        return {"ui": {"text": [video_url, str(local_path)]}, "result": (InputImpl.VideoFromFile(str(local_path)), "\n".join(info))}


NODE_CLASS_MAPPINGS = {"AriadneVeo31Video": AriadneVeo31Video}
NODE_DISPLAY_NAME_MAPPINGS = {"AriadneVeo31Video": "Ariadne · Veo 3.1 视频生成（Kie）"}
