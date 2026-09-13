"""Ariadne · Topaz 视频超分（Kie：topaz/video-upscale，画布 ariadne-topaz 插件移植）。

上游视频（本包生成节点或 LoadVideo 等标准 VIDEO 输出）→ 上传 Kie → 云端放大
1×修复/2×/4× → 成片落 output/ariadne/ 返回 VIDEO。契约与限制见 ariadne_core/topaz.py。
"""
from __future__ import annotations

from pathlib import Path

from ariadne_core import config, kie as kie_core, media, topaz as topaz_core
from ariadne_core.http import request_bytes


def _default_download_folder():
    try:
        import folder_paths

        return str(Path(folder_paths.get_output_directory()) / "ariadne")
    except ImportError:
        return str(Path.cwd() / "output" / "ariadne")


class AriadneTopazUpscale:
    """Ariadne · Topaz 视频超分（Kie：1× 修复增强 / 2× / 4× 放大）"""

    CATEGORY = "Ariadne/视频"
    RETURN_TYPES = ("VIDEO", "STRING")
    RETURN_NAMES = ("视频", "任务信息")
    OUTPUT_NODE = True
    FUNCTION = "upscale"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # 付费外部副作用：必须真实重跑，严禁缓存回放旧成片（同 kling 节点）。
        return float("NaN")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_video": ("VIDEO", {"tooltip": "待超分视频（Topaz 官方只接受 MP4/MOV/MKV，≤50MB）"}),
                "upscale_factor": (["1(修复增强)", "2(2倍放大)", "4(4倍放大)"], {"default": "2(2倍放大)"}),
                "download_folder": ("STRING", {"default": _default_download_folder()}),
            },
            "optional": {
                "poll_interval_seconds": ("INT", {"default": 5, "min": 2, "max": 60}),
                "timeout_seconds": ("INT", {"default": 1800, "min": 60, "max": 7200}),
            },
        }

    def upscale(self, source_video, upscale_factor, download_folder, poll_interval_seconds=5, timeout_seconds=1800):
        factor = topaz_core.parse_factor(upscale_factor)
        api_key = config.resolve_kie_key()

        source_path = media.video_to_file(source_video)
        topaz_core.validate_source(source_path)

        duration = 0.0
        try:
            duration = float(media.probe_video(source_path).get("seconds") or 0)
        except Exception:  # noqa: BLE001 - 时长仅供估价，探测失败不阻断
            duration = 0.0

        video_url = kie_core.upload_to_kie("video", source_path, api_key)
        task_id = kie_core.create_task(topaz_core.compile_request(video_url, factor), api_key)
        print(f"[Ariadne] Topaz 超分任务已创建 {task_id}（{topaz_core.FACTOR_LABELS[factor]}），开始轮询…")
        result = kie_core.poll_task(task_id, api_key, poll_interval_seconds=poll_interval_seconds,
                                    timeout_seconds=timeout_seconds, progress=print)
        urls = result.get("resultUrls") or []
        if not urls:
            raise RuntimeError(f"任务完成但未返回成片地址（taskId={task_id}）。")

        destination = Path(download_folder).expanduser() if str(download_folder).strip() else Path(_default_download_folder())
        destination.mkdir(parents=True, exist_ok=True)
        local_path = destination / f"Topaz_{task_id}.mp4"
        local_path.write_bytes(request_bytes("GET", urls[0], phase="下载成片"))

        from comfy_api.latest import InputImpl

        estimate = f"预估费用: ¥{topaz_core.estimate_cny(duration, factor) if duration > 0 else '未知（源时长探测失败）'}（以账单为准）"
        consumed = result.get("creditsConsumed")
        info = [
            f"Topaz 视频超分完成（{topaz_core.FACTOR_LABELS[factor]}）",
            f"任务ID: {task_id}",
            f"本地文件: {local_path}",
            estimate + ("" if consumed is None else f"，实耗 {consumed} credits"),
        ]
        return {"ui": {"text": [urls[0], str(local_path)]}, "result": (InputImpl.VideoFromFile(str(local_path)), "\n".join(info))}


NODE_CLASS_MAPPINGS = {"AriadneTopazUpscale": AriadneTopazUpscale}
NODE_DISPLAY_NAME_MAPPINGS = {"AriadneTopazUpscale": "Ariadne · Topaz 视频超分（Kie）"}
