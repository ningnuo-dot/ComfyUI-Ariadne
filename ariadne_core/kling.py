"""可灵（Kling 3.0）Kie 聚合路径契约与任务流（画布插件 kling 契约层的 Python 版）。

契约依据 tools/kling/docs/KLING_API_CONTRACT.md（Kie 文档 2026-09-08 实读）；未经真实
请求验证的行为标「待验证」。角色元素提示词用 `@名字` 引用（名字本身不含 @）。
"""
from __future__ import annotations

import re

from . import kie

KLING_MODEL = "kling-3.0/video"
KLING_ASPECTS = ("16:9", "9:16", "1:1")
KLING_QUALITY = ("std", "pro")

# Kie 实价 $0.07/秒；官方中国站对照价（有声未指定音色档，2026-09-08 实读；未取得档位 None）。
KIE_USD_PER_SECOND = 0.07
KIE_CREDITS_PER_USD = 200
USD_TO_CNY = 7.2
OFFICIAL_CNY_PER_SECOND = {
    "kling-3.0": {"720p": 0.9, "1080p": 1.2, "4k": None},
    "kling-3.0-turbo": {"720p": 0.8, "1080p": 1.0, "4k": None},
}


def estimate_kie(seconds: float) -> dict:
    usd = round(KIE_USD_PER_SECOND * seconds, 2)
    return {"usd": usd, "credits": round(KIE_USD_PER_SECOND * KIE_CREDITS_PER_USD * seconds), "cny": round(usd * USD_TO_CNY, 2)}


def validate_job(spec: dict) -> None:
    """可灵任务校验（画布 validate.ts 关键层移植）：元素完整性、引用兑现、时长/画幅约束。"""
    prompt = str(spec.get("prompt") or "")
    elements = spec.get("elements") or []
    names: list[str] = []
    for element in elements:
        name = str(element.get("name") or "").strip()
        image_urls = [url for url in element.get("imageUrls") or [] if str(url).strip()]
        video_url = str(element.get("videoUrl") or "").strip()
        if not name:
            raise RuntimeError("角色元素缺少 name（提示词用 @名字 引用元素）。")
        if "@" in name:
            raise RuntimeError(f"元素名「{name}」不能包含 @（引用语法保留字）。")
        if name in names:
            raise RuntimeError(f"元素名「{name}」重复。")
        names.append(name)
        if image_urls:
            if video_url:
                raise RuntimeError(f"元素「{name}」图片与视频二选一。")
            if not 2 <= len(image_urls) <= 4:
                raise RuntimeError(f"图片元素「{name}」需要 2-4 张图（当前 {len(image_urls)} 张）。")
        elif not video_url:
            raise RuntimeError(f"元素「{name}」既无图片也无视频（图片元素 2-4 张，或视频元素 1 段）。")
        if spec.get("taskType") != "multi-shot" and f"@{name}" not in prompt:
            raise RuntimeError(f"元素「{name}」未在提示词中用 @{name} 引用（未被引用的元素会被丢弃）。")
    shots = spec.get("shots") or []
    for shot in shots:
        if not 1 <= int(shot.get("duration", 0)) <= 12:
            raise RuntimeError("多镜头每个镜头时长须为 1-12 秒。")
        if not str(shot.get("prompt") or "").strip():
            raise RuntimeError("多镜头分镜缺少镜头提示词。")


def compile_request(spec: dict) -> dict:
    """spec = {taskType, prompt, firstFrameUrl?, lastFrameUrl?, elements[], shots[], duration,
    aspectRatio?, sound, qualityMode}。编译只做类型收敛与字段裁剪：空值字段不发送。"""
    task_type = spec["taskType"]
    multi = task_type == "multi-shot"
    shots = spec.get("shots") or []
    if multi and not (2 <= len(shots) <= 5):
        raise RuntimeError("多镜头模式需要 2-5 个镜头分镜。")
    duration = sum(int(shot["duration"]) for shot in shots) if multi else int(spec["duration"])
    if duration < 3 or duration > 15:
        raise RuntimeError("可灵生成时长必须在 3-15 秒之间（多镜头为各镜头之和）。")

    input_data: dict = {"sound": bool(spec.get("sound")), "duration": str(duration), "mode": spec["qualityMode"]}
    if not multi:
        input_data["prompt"] = str(spec.get("prompt") or "").strip()
        if not input_data["prompt"]:
            raise RuntimeError("提示词不能为空。")

    # 顺序即语义：首尾帧模式约定 [首帧, 尾帧]（Kie 文档未写明顺序语义，待验证）。
    image_urls: list[str] = []
    if str(spec.get("firstFrameUrl") or "").strip():
        image_urls.append(str(spec["firstFrameUrl"]).strip())
    if task_type == "first-last" and str(spec.get("lastFrameUrl") or "").strip():
        image_urls.append(str(spec["lastFrameUrl"]).strip())
    if image_urls:
        input_data["image_urls"] = image_urls
    if spec.get("aspectRatio"):
        input_data["aspect_ratio"] = spec["aspectRatio"]
    if multi:
        input_data["multi_shots"] = True
        input_data["multi_prompt"] = [{"prompt": shot["prompt"], "duration": int(shot["duration"])} for shot in shots]

    elements = [item for item in (_to_kie_element(element) for element in spec.get("elements") or []) if item]
    if elements:
        input_data["kling_elements"] = elements
    return {"model": KLING_MODEL, "input": input_data}


def _to_kie_element(element: dict) -> dict | None:
    """图片元素（2-4 张）与视频元素（1 段）字段不同名，二选一；名字必填。"""
    name = str(element.get("name") or "").strip()
    image_urls = [url.strip() for url in element.get("imageUrls") or [] if str(url).strip()]
    video_url = str(element.get("videoUrl") or "").strip()
    if not name or (image_urls and video_url) or (not image_urls and not video_url):
        return None
    base = {"name": name}
    if str(element.get("description") or "").strip():
        base["description"] = str(element["description"]).strip()
    if image_urls:
        return {**base, "element_input_urls": image_urls}
    return {**base, "element_input_video_urls": [video_url]}


def run_kling(
    body: dict,
    api_key: str,
    upload_fn=None,
    poll_interval_seconds: int = 5,
    timeout_seconds: int = 1800,
    progress=None,
) -> dict:
    """提交 + 轮询（jobs 端点，与 Seedance Kie 渠道同构）；upload_fn(kind, path)->url 供上传元素素材。"""
    if progress:
        progress("提交可灵任务…")
    task_id = kie.create_task(body, api_key, phase="创建可灵任务")
    result = kie.poll_task(task_id, api_key, poll_interval_seconds, timeout_seconds, progress=progress)
    urls = result["resultUrls"]
    video_url = next((url for url in urls if re.search(r"\.(mp4|mov)(\?|$)", url, re.IGNORECASE)), "")
    if not video_url:
        video_url = urls[0] if urls else ""
    if not video_url:
        raise RuntimeError("可灵任务成功但未返回视频地址。")
    return {"taskId": task_id, "videoUrl": video_url, "extraUrls": [url for url in urls if url != video_url]}
