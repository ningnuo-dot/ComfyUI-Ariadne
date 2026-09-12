"""Kie 渠道 Seedance 2.5：编译 + 任务流（画布插件 kie.ts 的 Python 版）。

与方舟渠道并列的第二渠道：jobs 接口 + input 平铺字段 + @ImageN 引用 + Kie 自家上传。
编辑/延长模式 Kie 未开通，编译层直接拒绝（与画布版双重拦截一致）。
"""
from __future__ import annotations

import re

from .. import kie
from .compile import ROLE_DUTY
from .contract import KIND_PREFIX_KIE, MODEL, SeedanceJobSpec

KIE_SEEDANCE_MODEL = "bytedance/seedance-2-5"

# Kie input 的合法字段清单（官方页面）；编译产物超出即视为实现错误——
# 未知键会被 500 拒绝或静默忽略（空壳不生效）。
KIE_INPUT_FIELDS = {
    "prompt", "first_frame_url", "last_frame_url", "reference_image_urls",
    "reference_video_urls", "reference_audio_urls", "generate_audio",
    "return_last_frame", "resolution", "aspect_ratio", "duration", "output_format",
}


def compile_kie_prompt(prompt: str, assets: list) -> str:
    """面板标签（@图片N）编译为 Kie 官方引用（@ImageN）；编号一致，仅前缀翻译 + 职责句。"""
    counters = {"image": 0, "video": 0, "audio": 0}
    text = prompt.strip()
    for asset in assets:
        if not asset.label:
            continue
        counters[asset.kind] += 1
        local = asset.label if asset.label.startswith("@") else f"@{asset.label}"
        text = text.replace(local, f"@{KIND_PREFIX_KIE[asset.kind]}{counters[asset.kind]}")
    counters2 = {"image": 0, "video": 0, "audio": 0}
    duties = []
    for asset in assets:
        if asset.role not in ROLE_DUTY:
            continue
        counters2[asset.kind] += 1
        duties.append(f"@{KIND_PREFIX_KIE[asset.kind]}{counters2[asset.kind]}提供{ROLE_DUTY[asset.role]}")
    return f"{text}\n素材职责：{'；'.join(duties)}。" if duties else text


def compile_kie_request(spec: SeedanceJobSpec) -> dict:
    """把 spec 编译为 Kie createTask 的 input（仅文生/首帧/首尾帧/多模态参考）。"""
    if spec.task_type in ("edit", "extend"):
        raise RuntimeError(
            "Kie 渠道暂不支持「视频编辑 / 视频延长」任务（Kie 未开通该模式）。"
            "请切回火山方舟渠道，或改用全能参考/文生视频任务。"
        )
    if spec.duration == -1:
        raise RuntimeError("Kie 渠道不支持自适应时长。请选择 4–30 秒的具体时长。")
    duration = int(spec.duration)
    if duration < 4 or duration > 30:
        raise RuntimeError(f"Kie 渠道生成时长必须在 4–30 秒之间，当前为 {spec.duration} 秒。")

    prompt = compile_kie_prompt(spec.prompt, spec.assets)
    first = next((asset for asset in spec.assets if asset.role == "first-frame"), None)
    last = next((asset for asset in spec.assets if asset.role == "last-frame"), None)
    rest = [asset for asset in spec.assets if asset.role not in ("first-frame", "last-frame")]

    input_data: dict = {"prompt": prompt}
    if first:
        input_data["first_frame_url"] = first.url
    if last:
        input_data["last_frame_url"] = last.url
    for key, kind in (("reference_image_urls", "image"), ("reference_video_urls", "video"), ("reference_audio_urls", "audio")):
        urls = [asset.url for asset in rest if asset.kind == kind]
        if urls:
            input_data[key] = urls
    input_data["generate_audio"] = spec.generate_audio
    if spec.return_last_frame:
        input_data["return_last_frame"] = True
    input_data["resolution"] = spec.resolution
    input_data["aspect_ratio"] = spec.aspect_ratio
    input_data["duration"] = duration
    input_data["output_format"] = spec.output_format
    unknown = set(input_data) - KIE_INPUT_FIELDS
    if unknown:
        raise RuntimeError(f"Kie 契约出现未登记字段 {sorted(unknown)}，已阻止发送（Kie 对未知字段会拒绝或静默忽略）。")
    return {"model": KIE_SEEDANCE_MODEL, "input": input_data}


FAIL_HINTS = {
    "PROMINENT_PEOPLE": "Kie 的公众人物审核拦截了参考素材里的人脸（AI 生成脸也可能误判）；重试无效，请对人脸做去识别化处理或更换素材。",
    "AUDIO_FILTERED": "Kie 的音频审核拦截了参考/生成的音轨；去掉参考视频音轨或改为无声后重试。",
}


def run_kie_seedance(
    spec: SeedanceJobSpec,
    request: dict,
    api_key: str,
    poll_interval_seconds: int = 5,
    timeout_seconds: int = 1800,
    progress=None,
) -> dict:
    """提交 + 轮询（5 秒节奏，30 分钟上限，与方舟渠道一致）；返回 {taskId, videoUrl, lastFrameUrl, remainedCredits}。"""
    if progress:
        progress("提交 Seedance 任务（Kie）…")
    task_id = kie.create_task(request, api_key, phase="提交 Seedance 任务（Kie）")
    result = kie.poll_task(
        task_id, api_key, poll_interval_seconds, timeout_seconds, progress=progress, fail_hints=FAIL_HINTS
    )
    urls = result["resultUrls"]
    video_url = next((url for url in urls if re.search(r"\.(mp4|mov)(\?|$)", url, re.IGNORECASE)), "")
    if not video_url:
        raise RuntimeError(f"Seedance（Kie）任务成功但未返回视频地址：{result['resultUrls'][:2]}")
    last_frame = urls[1] if spec.return_last_frame and len(urls) > 1 and urls[1] != video_url else None
    return {
        "taskId": task_id,
        "videoUrl": video_url,
        "lastFrameUrl": last_frame,
        "remainedCredits": result["remainedCredits"],
    }
