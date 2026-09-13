"""Ariadne · Seedance 2.5 视频生成（火山方舟直连为主渠道 + Kie 副渠道）。

参考素材双入口（编号规则：节点内瓦片先编 @图片1…N，连线输入接着编）：
- 瓦片：前端「素材」widget 拖入/上传，存 JSON（kind/role/name/subfolder）；
- 插座：character_images / wardrobe_images / scene_images / motion_video / reference_audio /
  first_frame / last_frame，角色固定。

产物硬性落盘 output/ariadne/（方舟结果 URL 24 小时过期，禁止只回写时效链接）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ariadne_core import config, kie as kie_core, media
from ariadne_core.http import request_bytes
from ariadne_core.seedance.ark import run_ark_seedance
from ariadne_core.seedance.ark_media import to_ark_safe_url, validate_video_pixels, is_public_http_url
from ariadne_core.seedance.compile import compile_request
from ariadne_core.seedance.contract import ASPECTS, RESOLUTIONS, TASK_TYPES, SeedanceAsset, SeedanceJobSpec
from ariadne_core.seedance import pricing
from ariadne_core.seedance.kie_channel import compile_kie_request, run_kie_seedance
from ariadne_core.seedance.validate import validate_job

TASK_TYPE_LABELS = ["auto(全能参考)", "text(文生视频)", "reference(多模态参考)", "first-frame(首帧)", "first-last(首尾帧)", "edit(视频编辑)", "extend(视频延长)"]


def _task_type_of(value: str) -> str:
    return str(value or "auto").split("(")[0].strip()


def _default_download_folder():
    try:
        import folder_paths

        return str(Path(folder_paths.get_output_directory()) / "ariadne")
    except ImportError:
        return str(Path.cwd() / "output" / "ariadne")


def _resolve_input_path(name: str, subfolder: str = "ariadne") -> str:
    """input 目录相对名 → 绝对路径（含子目录安全校验）。"""
    import folder_paths

    base = Path(folder_paths.get_input_directory()).resolve()
    if subfolder and (os.path.isabs(subfolder) or ":" in subfolder or ".." in Path(subfolder).parts):
        raise RuntimeError(f"素材子目录不合法：{subfolder}")
    target = (base / subfolder / name).resolve() if subfolder else (base / name).resolve()
    norm_base = os.path.normcase(str(base))
    norm_target = os.path.normcase(str(target))
    if norm_target == norm_base or not norm_target.startswith(norm_base + os.sep):
        raise RuntimeError(f"素材路径越界：{name}")
    if not target.is_file():
        raise RuntimeError(f"素材文件不存在：{subfolder}/{name}（可能已被移动或删除，请重新导入）")
    return str(target)


def _tiles_from_widget(value: str) -> list[dict]:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except ValueError:
        return []


def _assign_labels(assets: list[SeedanceAsset]) -> None:
    counters = {"image": 0, "video": 0, "audio": 0}
    prefix = {"image": "图片", "video": "视频", "audio": "音频"}
    for asset in assets:
        counters[asset.kind] += 1
        asset.label = f"@{prefix[asset.kind]}{counters[asset.kind]}"


def _normalize_to_channel(asset: SeedanceAsset, channel: str, tos: dict | None, api_key: str, progress_key: str | None = None) -> str:
    """本地文件路径 → 渠道可用地址；公网 URL 原样透传。"""
    url = asset.url
    if not url or is_public_http_url(url) or url.startswith(("data:", "asset:")):
        return url
    if channel == "kie":
        kind = "video" if asset.kind == "video" else ("audio" if asset.kind == "audio" else "image")
        return kie_core.upload_to_kie(kind, url, api_key, progress_key=progress_key)
    return to_ark_safe_url(url, asset.kind, tos)


def _run_generation(*, prompt, task_type, duration, resolution, aspect_ratio, generate_audio,
                    output_format, channel, download_folder, ariadne_assets,
                    socket_assets, motion_seconds, motion_video_connected,
                    return_last_frame, poll_interval_seconds, timeout_seconds, node):
    """共享提交流程：瓦片组装 → 编号 → 校验 → 归一化 → 双渠道提交 → 成片落盘。"""
    # ---- 组装素材序列：瓦片在前（保持面板顺序），插座接着编 ----
    assets: list[SeedanceAsset] = []
    tiles = _tiles_from_widget(ariadne_assets)
    for tile in tiles:
        role = str(tile.get("role") or "")
        kind = str(tile.get("kind") or "")
        if kind not in ("image", "video", "audio") or not role:
            continue
        path = _resolve_input_path(str(tile["name"]), str(tile.get("subfolder") or "ariadne"))
        if kind == "video" and role != "annotation":
            validate_video_pixels(path, tile.get("label") or tile["name"])
        assets.append(SeedanceAsset(kind=kind, role=role, url=path, timestamp_seconds=tile.get("timestampSeconds")))
    assets.extend(socket_assets)
    _assign_labels(assets)

    spec = SeedanceJobSpec(
        task_type=task_type, prompt=prompt, assets=assets, duration=int(duration),
        resolution=resolution, aspect_ratio=aspect_ratio, generate_audio=bool(generate_audio),
        output_format=output_format, return_last_frame=bool(return_last_frame) and channel == "kie",
    )
    errors = validate_job(spec)
    if errors:
        raise RuntimeError("Seedance 任务校验失败：\n- " + "\n- ".join(errors))

    # 输入视频总时长（估价用：两渠道含视频输入均按（输入+输出）时长计费）。
    def _tile_seconds(tile: dict) -> float:
        try:
            return max(0.0, float(tile.get("seconds") or 0.0))
        except (TypeError, ValueError):
            return 0.0

    input_seconds = motion_seconds + sum(
        _tile_seconds(tile) for tile in tiles if tile.get("kind") == "video"
    )

    # ---- 素材归一化 + 提交 ----
    if channel == "ark":
        api_key = config.resolve_ark_key()
        tos = config.tos_settings()
        normalized = [
            SeedanceAsset(asset.kind, asset.role, _normalize_to_channel(asset, "ark", tos, api_key),
                          asset.label, asset.timestamp_seconds)
            for asset in spec.assets
        ]
        spec.assets = normalized
        request = compile_request(spec)
        result = run_ark_seedance(spec, request["body"], api_key, poll_interval_seconds, timeout_seconds,
                                  progress=print)
    else:
        api_key = config.resolve_kie_key()
        normalized = [
            SeedanceAsset(asset.kind, asset.role, _normalize_to_channel(asset, "kie", None, api_key,
                              progress_key=str(getattr(node, "id", ""))), asset.label, asset.timestamp_seconds)
            for asset in spec.assets
        ]
        spec.assets = normalized
        request = compile_kie_request(spec)
        result = run_kie_seedance(spec, request, api_key, poll_interval_seconds, timeout_seconds, progress=print)

    # ---- 成片下载：智能分流（时效 URL 必须立即下载，禁回写） ----
    # 下游接了保存节点（SaveVideo 等）→ 交由它落盘，本节点只下到临时文件供连线使用；
    # 没接 → 自动落盘兜底，存到 download_folder（默认 output/ariadne）。
    video_url = result["videoUrl"]
    suffix = Path(video_url.split("?", 1)[0]).suffix or ".mp4"
    video_connected = node._video_output_connected()
    if video_connected:
        import tempfile

        local_path = Path(tempfile.gettempdir()) / f"ariadne-seedance-{result['taskId']}{suffix}"
    else:
        destination = Path(download_folder).expanduser() if str(download_folder).strip() else Path(_default_download_folder())
        if not destination.is_absolute():
            destination = (Path.cwd() / destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        local_path = destination / f"Seedance版_{result['taskId']}{suffix}"
    local_path.write_bytes(request_bytes("GET", video_url, phase="下载成片"))

    video_output = node._video_from_file(str(local_path))
    info_lines = [
        f"Seedance 2.5 完成（渠道 {channel} / {task_type}）",
        f"任务ID: {result['taskId']}",
        f"素材: {', '.join(asset.label for asset in spec.assets) or '无'}",
        f"视频已由下游保存节点落盘" if video_connected else f"本地文件: {local_path}",
    ]
    if channel == "kie":
        estimate = pricing.estimate_kie_credits(resolution, int(duration), motion_video_connected or any(t.get("kind") == "video" for t in tiles), 0)
        if estimate:
            info_lines.append(f"预估积分（输入时长未计入部分以账单为准）: ≈{estimate:.0f}")
        if result.get("remainedCredits") is not None:
            info_lines.append(f"剩余积分: {result['remainedCredits']}")
        if result.get("lastFrameUrl"):
            info_lines.append(f"尾帧图 URL（24h 有效，请尽快保存）: {result['lastFrameUrl']}")
    else:
        estimate = pricing.estimate_ark_price(resolution, int(duration), includes_video=input_seconds > 0, input_video_seconds=input_seconds)
        if estimate:
            info_lines.append(f"预估费用（仅展示，以账单为准）: ≈¥{estimate}")
    return {"ui": {"text": [video_url, str(local_path)]}, "result": (video_output, "\n".join(info_lines))}


class AriadneSeedance25Video:
    """Ariadne · Seedance 2.5 视频生成（方舟直连/Kie 双渠道，全能参考/编辑/延长/首尾帧全模式）。"""

    CATEGORY = "Ariadne/视频"
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
                "prompt": ("STRING", {
                    "multiline": True, "default": "", "defaultInput": True,
                    "tooltip": "描述画面。瓦片/连线素材用 @图片1/@视频1/@音频1 引用（面板标签，提交自动编译为官方 @图像N/@ImageN）。",
                }),
                "task_type": (TASK_TYPE_LABELS, {"default": TASK_TYPE_LABELS[0]}),
                "duration": ("INT", {"default": 10, "min": -1, "max": 30, "tooltip": "4-30 秒；视频编辑/延长必须 -1（自适应）"}),
                "resolution": (RESOLUTIONS, {"default": "720p"}),
                "aspect_ratio": (ASPECTS, {"default": "9:16"}),
                "generate_audio": ("BOOLEAN", {"default": True}),
                "output_format": (["mp4", "mov"], {"default": "mp4"}),
                "channel": (["ark(火山方舟直连)", "kie(Kie积分)"], {"default": "ark(火山方舟直连)"}),
                "download_folder": ("STRING", {"default": _default_download_folder()}),
                "ariadne_assets": ("STRING", {"default": "[]", "tooltip": "节点内瓦片素材（前端维护的 JSON，一般无需手改）"}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧（首帧/首尾帧模式必连）"}),
                "last_frame": ("IMAGE", {"tooltip": "尾帧（仅首尾帧模式）"}),
                "character_images": ("IMAGE", {"tooltip": "人物参考图（可多张）：人物外观与服装"}),
                "wardrobe_images": ("IMAGE", {"tooltip": "服装参考图：款式与面料细节"}),
                "scene_images": ("IMAGE", {"tooltip": "场景参考图：结构、光线与构图"}),
                "motion_video": ("VIDEO", {"tooltip": "动作参考视频：动作、运镜与节奏（计费按输入+输出时长）"}),
                "reference_audio": ("AUDIO", {"tooltip": "参考音频：音色/台词/音乐"}),
                "return_last_frame": ("BOOLEAN", {"default": False, "tooltip": "额外返回尾帧图（仅 Kie 渠道支持；方舟渠道无对应字段）"}),
                "poll_interval_seconds": ("INT", {"default": 5, "min": 2, "max": 60}),
                "timeout_seconds": ("INT", {"default": 1800, "min": 60, "max": 7200}),
            },
        }

    def generate(
        self, prompt, task_type, duration, resolution, aspect_ratio, generate_audio,
        output_format, channel, download_folder, ariadne_assets="[]",
        first_frame=None, last_frame=None, character_images=None, wardrobe_images=None,
        scene_images=None, motion_video=None, reference_audio=None,
        return_last_frame=False, poll_interval_seconds=5, timeout_seconds=1800,
    ):
        task_type = _task_type_of(task_type)
        channel = "kie" if str(channel).startswith("kie") else "ark"
        if task_type in ("edit", "extend"):
            duration = -1  # 官方约束：编辑/延长自适应时长
        if channel == "kie":
            if task_type in ("edit", "extend"):
                raise RuntimeError("Kie 渠道暂不支持「视频编辑 / 视频延长」（未开通该模式）；请切回火山方舟渠道。")
            if duration == -1 or int(duration) < 4 or int(duration) > 30:
                raise RuntimeError("Kie 渠道生成时长必须为 4-30 秒的整数（不支持自适应）。")

        # ---- 插座素材（角色固定）----
        socket_assets: list[SeedanceAsset] = []
        if first_frame is not None:
            socket_assets.append(SeedanceAsset("image", "first-frame", media.image_to_file(first_frame)))
        if last_frame is not None:
            socket_assets.append(SeedanceAsset("image", "last-frame", media.image_to_file(last_frame)))
        for role, images in (("character", character_images), ("wardrobe", wardrobe_images), ("scene", scene_images)):
            if images is not None:
                for path in media.images_to_files(images):
                    socket_assets.append(SeedanceAsset("image", role, path))
        motion_seconds = 0.0
        if motion_video is not None:
            motion_path = media.video_to_file(motion_video)
            validate_video_pixels(motion_path, "@视频(动作参考)")  # 上传 TOS 前拦截，省白传大文件
            socket_assets.append(SeedanceAsset("video", "motion", motion_path))
            try:
                motion_seconds = media.probe_video(motion_path).get("seconds", 0.0)
            except Exception:
                motion_seconds = 0.0
        if reference_audio is not None:
            socket_assets.append(SeedanceAsset("audio", "audio", media.audio_to_wav(reference_audio)))

        return _run_generation(
            prompt=prompt, task_type=task_type, duration=duration, resolution=resolution,
            aspect_ratio=aspect_ratio, generate_audio=generate_audio, output_format=output_format,
            channel=channel, download_folder=download_folder, ariadne_assets=ariadne_assets,
            socket_assets=socket_assets, motion_seconds=motion_seconds,
            motion_video_connected=motion_video is not None,
            return_last_frame=return_last_frame, poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds, node=self,
        )

    def _video_output_connected(self) -> bool:
        """VIDEO 输出口是否已连线下游（如 SaveVideo）。API 直跑/检测不到时按未连接处理，自动落盘兜底。"""
        try:
            outputs = getattr(self, "outputs", None) or []
            if outputs:
                links = getattr(outputs[0], "links", None)
                if links:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _video_from_file(path: str):
        from comfy_api.latest import InputImpl

        return InputImpl.VideoFromFile(path)


FREE_TASK_TYPE_LABELS = TASK_TYPE_LABELS[:3]  # 自由引用版只保留 全能参考/文生视频/多模态参考


class AriadneSeedance25Free(AriadneSeedance25Video):
    """Ariadne · Seedance 2.5 视频生成（自由引用版，2026-09-14 应用户要求复制的姊妹节点）。

    与标准版差异：去掉首帧/尾帧/人物/服装/场景/动作/音频全部预设角色插座，仅保留三个自由图像
    插座；role="free" 不在 ROLE_DUTY，编译层只编号（@图片N→@图像N/@ImageN）不生成素材职责句——
    图像的身份与职责由用户在提示词里手工指定。
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True, "default": "", "defaultInput": True,
                    "tooltip": "描述画面，并手工说明每张图像的身份/职责。图像按 图像1→图像2→图像3 顺序编号为 @图片N（提交自动编译为官方 @图像N）。",
                }),
                "task_type": (FREE_TASK_TYPE_LABELS, {"default": FREE_TASK_TYPE_LABELS[0]}),
                "duration": ("INT", {"default": 10, "min": 4, "max": 30, "tooltip": "4-30 秒"}),
                "resolution": (RESOLUTIONS, {"default": "720p"}),
                "aspect_ratio": (ASPECTS, {"default": "9:16"}),
                "generate_audio": ("BOOLEAN", {"default": True}),
                "output_format": (["mp4", "mov"], {"default": "mp4"}),
                "channel": (["ark(火山方舟直连)", "kie(Kie积分)"], {"default": "ark(火山方舟直连)"}),
                "download_folder": ("STRING", {"default": _default_download_folder()}),
                "ariadne_assets": ("STRING", {"default": "[]", "tooltip": "节点内瓦片素材（前端维护的 JSON，一般无需手改）"}),
            },
            "optional": {
                "image_1": ("IMAGE", {"tooltip": "自由图像 1：身份/职责在提示词中手工说明，不做预设角色"}),
                "image_2": ("IMAGE", {"tooltip": "自由图像 2：同上，编号在 图像1 之后"}),
                "image_3": ("IMAGE", {"tooltip": "自由图像 3：同上，编号在 图像2 之后"}),
                "return_last_frame": ("BOOLEAN", {"default": False, "tooltip": "额外返回尾帧图（仅 Kie 渠道支持；方舟渠道无对应字段）"}),
                "poll_interval_seconds": ("INT", {"default": 5, "min": 2, "max": 60}),
                "timeout_seconds": ("INT", {"default": 1800, "min": 60, "max": 7200}),
            },
        }

    def generate(
        self, prompt, task_type, duration, resolution, aspect_ratio, generate_audio,
        output_format, channel, download_folder, ariadne_assets="[]",
        image_1=None, image_2=None, image_3=None,
        return_last_frame=False, poll_interval_seconds=5, timeout_seconds=1800,
    ):
        task_type = _task_type_of(task_type)
        channel = "kie" if str(channel).startswith("kie") else "ark"
        if channel == "kie" and (int(duration) < 4 or int(duration) > 30):
            raise RuntimeError("Kie 渠道生成时长必须为 4-30 秒的整数（不支持自适应）。")
        socket_assets: list[SeedanceAsset] = []
        for images in (image_1, image_2, image_3):
            if images is not None:
                for path in media.images_to_files(images):
                    socket_assets.append(SeedanceAsset("image", "free", path))
        return _run_generation(
            prompt=prompt, task_type=task_type, duration=int(duration), resolution=resolution,
            aspect_ratio=aspect_ratio, generate_audio=generate_audio, output_format=output_format,
            channel=channel, download_folder=download_folder, ariadne_assets=ariadne_assets,
            socket_assets=socket_assets, motion_seconds=0.0, motion_video_connected=False,
            return_last_frame=return_last_frame, poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds, node=self,
        )


NODE_CLASS_MAPPINGS = {
    "AriadneSeedance25Video": AriadneSeedance25Video,
    "AriadneSeedance25Free": AriadneSeedance25Free,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "AriadneSeedance25Video": "Ariadne · Seedance 2.5 视频生成",
    "AriadneSeedance25Free": "Ariadne · Seedance 2.5 视频生成（自由引用）",
}
