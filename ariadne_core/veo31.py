"""Veo 3.1（Kie 专属端点族 /api/v1/veo/*）契约与任务流（画布插件 veo-3-1 契约层的 Python 版）。

字段与枚举来自 Kie 官方文档 docs.kie.ai/veo3-api（2026-09-08 实读）；未在官方页面出现的
字段一律不做。费率表为 2026-09-08 用户全表截图（15 行）——查不到的组合返回 None 不外推。
"""
from __future__ import annotations

import re
import time
import urllib.parse

from . import kie
from .http import request_json, request_bytes

VEO_MODELS = ("veo3", "veo3_fast", "veo3_lite")
VEO_ASPECTS = ("16:9", "9:16", "Auto")
VEO_RESOLUTIONS = ("720p", "1080p", "4k")
VEO_DURATIONS = (4, 6, 8)

_GENERATION_TYPE = {"text": "TEXT_2_VIDEO", "first-last": "FIRST_AND_LAST_FRAMES_2_VIDEO", "reference": "REFERENCE_2_VIDEO"}
# 延长端点的模型档位与生成端点不同名（fast|quality|lite），按档位语义映射（映射关系待线上验证）。
_EXTEND_MODEL = {"veo3": "quality", "veo3_fast": "fast", "veo3_lite": "lite"}

# 生成主端点：模式-模型档-分辨率 → credits/次（全表 15 行原文照录；未列组合 = 官方未列出）。
VEO_CREDIT_RATES = {
    "usdPerCredit": 0.005,
    "generation": {
        "reference-veo3_lite-720p": 15, "reference-veo3_lite-1080p": 22.5, "reference-veo3_lite-4k": 75,
        "reference-veo3_fast-1080p": 37.5, "reference-veo3_fast-4k": 90,
        "text-veo3-720p": 225, "text-veo3-1080p": 232.5, "text-veo3-4k": 285,
        "image-veo3-720p": 225, "image-veo3-1080p": 232.5, "image-veo3-4k": 285,
        "text-veo3_fast-1080p": 37.5, "text-veo3_fast-4k": 90, "image-veo3_fast-4k": 90,
    },
    "extend": {"lite": 15},
    "upgrade1080p": 5,
    "upgrade4k": 120,
}


def estimate_veo_credits(task_type: str, model: str, resolution: str) -> int | float | None:
    """当前组合的 credits；费率表未覆盖的组合/未知模型返回 None（显示 credits --），不外推。"""
    if task_type == "extend":
        return VEO_CREDIT_RATES["extend"].get(_EXTEND_MODEL.get(model, ""))
    mode = {"text": "text", "first-last": "image", "reference": "reference"}.get(task_type)
    if not mode:
        return None
    return VEO_CREDIT_RATES["generation"].get(f"{mode}-{model}-{resolution}")


def compile_generate_request(spec: dict) -> dict:
    """spec = {taskType, prompt, assets[{url}], model, duration, resolution, aspectRatio, watermark}。"""
    task_type = spec["taskType"]
    if task_type == "extend":
        raise RuntimeError("延长任务请走 compile_extend_request（/api/v1/veo/extend）。")
    body: dict = {
        "prompt": spec["prompt"].strip(),
        "model": spec["model"],
        "generationType": _GENERATION_TYPE[task_type],
        "aspect_ratio": spec["aspectRatio"],
        "resolution": spec["resolution"],
        "duration": int(spec["duration"]),
    }
    if task_type != "text" and spec.get("assets"):
        # 顺序即语义：首尾帧模式约定第一张为首帧、第二张为尾帧（官方未写明顺序语义，待验证）。
        body["imageUrls"] = [asset["url"] for asset in spec["assets"]]
    watermark = str(spec.get("watermark") or "").strip()
    if watermark:
        body["watermark"] = watermark
    return body


def compile_extend_request(spec: dict) -> dict:
    body: dict = {
        "taskId": str(spec.get("extendTaskId") or "").strip(),
        "prompt": spec["prompt"].strip(),
        "model": _EXTEND_MODEL[spec["model"]],
    }
    if not body["taskId"]:
        raise RuntimeError("延长任务必须填写来源任务 ID（须为 /api/v1/veo/generate 创建的原任务，且未做过 1080P 升级）。")
    seeds = spec.get("extendSeeds")
    if isinstance(seeds, (int, float)) and seeds == int(seeds):  # 数值即发（与 TS 一致），不静默丢弃
        body["seeds"] = int(seeds)
    watermark = str(spec.get("watermark") or "").strip()
    if watermark:
        body["watermark"] = watermark
    return body


def run_veo(
    body: dict,
    is_extend: bool,
    api_key: str,
    poll_interval_seconds: int = 5,
    timeout_seconds: int = 1800,
    progress=None,
) -> dict:
    """提交 /api/v1/veo/generate 或 /extend → 轮询 record-info → 返回 {taskId, videoUrl, extraUrls}。"""
    headers = {"content-type": "application/json", "authorization": f"Bearer {api_key.strip()}"}
    endpoint = "/api/v1/veo/extend" if is_extend else "/api/v1/veo/generate"
    if progress:
        progress("提交 Veo 任务…")
    response, payload = request_json("POST", f"{kie.KIE_BASE_URL}{endpoint}", phase="提交 Veo 任务", headers=headers, json_body=body)
    if response.status_code != 200:
        raise kie.translate_kie_error(response.status_code, payload, "创建 Veo 任务")
    # generate 返回 {code,msg,data:{taskId}}；extend 返回 {code,msg,data:{taskId,seeds,...}}。
    data = payload.get("data") if isinstance(payload, dict) else None
    task_id = str((data or {}).get("taskId") or "")
    if not task_id:
        raise RuntimeError(f"Veo 未返回任务 ID：{str(payload)[:200]}")

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(poll_interval_seconds)
        response, payload = request_json(
            "GET", f"{kie.KIE_BASE_URL}/api/v1/veo/record-info?taskId={urllib.parse.quote(task_id)}", phase="查询 Veo 任务", headers=headers
        )
        if response.status_code != 200:
            raise kie.translate_kie_error(response.status_code, payload, "查询 Veo 任务")
        data = payload.get("data") if isinstance(payload, dict) else None
        data = data or {}
        flag = data.get("successFlag")
        if flag == 1:
            inner = data.get("response") or {}
            urls = _normalize_urls(inner.get("resultUrls"))
            video_url = next((url for url in urls if re.search(r"\.(mp4|mov|webm)(\?|$)", url, re.IGNORECASE)), "")
            if not video_url:
                raise RuntimeError(f"Veo 任务成功但未返回视频地址：{str(inner)[:200]}")
            return {"taskId": task_id, "videoUrl": video_url, "extraUrls": [url for url in urls if url != video_url]}
        if flag in (2, 3):
            raise RuntimeError(f"Veo 任务失败（successFlag={flag}）：{data.get('errorMessage') or '未知错误'}")
        if progress:
            progress("生成中…")
    raise RuntimeError("Veo 任务等待超时（30 分钟）")


def _normalize_urls(value) -> list[str]:
    """resultUrls 兼容解析：数组原样；字符串尝试 JSON 解析失败按单元素（官方两处文档矛盾）。"""
    if isinstance(value, list):
        return [url for url in value if isinstance(url, str) and url]
    if isinstance(value, str) and value.strip():
        try:
            import json

            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [url for url in parsed if isinstance(url, str) and url]
        except ValueError:
            pass
        return [value]
    return []
