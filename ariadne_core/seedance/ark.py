"""方舟官方异步任务：提交 → 轮询 → 取回视频 URL（画布插件 ark.ts 的 Python 版）。

官方素材规则（2026-09-09 实测）：视频仅公网 http(s) URL 或 asset:// 素材 ID（不支持
Base64）；图片/音频可 URL/Base64/asset://。归一化在 ark_media.py 完成，本模块发送前兜底拦截。
"""
from __future__ import annotations

import re
import time

from ..http import request_json
from .contract import ENDPOINT, SeedanceJobSpec, SeedanceAsset

ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

_URL_RULE = re.compile(r"^(https?://|data:|asset:)", re.IGNORECASE)
_PIXEL_HINT = re.compile(r"video pixel count.*greater than or equal to (\d+)", re.IGNORECASE)
_POSITION = re.compile(r"content\[(\d+)\]")
_SENSITIVE = re.compile(r"InputImageSensitiveContentDetected|real person", re.IGNORECASE)
_TERMINAL_OK = re.compile(r"succeed|success|completed|done", re.IGNORECASE)
_TERMINAL_BAD = re.compile(r"fail|error|cancel|expire", re.IGNORECASE)


def _content_url(item: dict) -> str:
    for key in ("image_url", "video_url", "audio_url"):
        if key in item:
            return str(item[key].get("url", ""))
    return ""


def _kind_label(item: dict | None) -> str:
    if not item:
        return "@图片"
    return {"video_url": "@视频", "audio_url": "@音频"}.get(item.get("type", ""), "@图片")


def _kind_type(item: dict | None) -> str:
    if not item:
        return "image_url"
    return str(item.get("type", "image_url"))


def read_ark_error(response, payload, request_body: dict) -> RuntimeError:
    """把方舟错误翻译成可操作的中文（素材编号 + 官方限制 + 替代方案）。error 为字符串/非 dict 均安全。"""
    if not isinstance(payload, dict):
        payload = {}
    error = payload.get("error")
    error_message = error.get("message") if isinstance(error, dict) else str(error) if error else ""
    error_code = error.get("code") if isinstance(error, dict) else ""
    detail = str(payload.get("message") or error_message or response.text[:300] or "未知错误")
    index = _POSITION.search(detail)
    content = request_body.get("content", [])
    position = int(index.group(1)) if index else -1
    item = content[position] if 0 <= position < len(content) else None

    minimum = _PIXEL_HINT.search(detail)
    if minimum and item and item.get("type") == "video_url":
        number = len([entry for entry in content[: position + 1] if entry.get("type") == "video_url"])
        return RuntimeError(
            f"@视频{number} 参考视频尺寸过小：宽×高至少需要 {minimum.group(1)} 像素。"
            f"请等比例放大视频并重新导入；修改输出分辨率无效。\n{detail}"
        )
    if _SENSITIVE.search(detail):
        item_type = _kind_type(item)
        ordinal = len([entry for entry in content[1 : max(position + 1, 1)] if entry.get("type") == item_type]) or 1
        return RuntimeError(
            f"方舟拒绝生成：{_kind_label(item)}{ordinal} 疑似包含真人面孔（官方禁止真人参考素材）。"
            "重试无效；请更换非真人素材（剪影、远景、人体模型、雕塑感照片等）后再生成。\n原始报错：" + detail
        )
    return RuntimeError(f"Seedance 请求失败（HTTP {response.status_code}）：{detail}")


def validate_content_urls(request_body: dict) -> None:
    """发送前兜底：拦截仍未合规的素材地址并翻译成「第几个素材」。"""
    for item in request_body.get("content", []):
        value = _content_url(item)
        if value and not _URL_RULE.match(value):
            kind = {"video_url": "视频", "audio_url": "音频"}.get(item.get("type", ""), "图片")
            extra = (
                "视频只接受公网 http(s) URL 或 asset:// 素材 ID（不支持 Base64），"
                if item.get("type") == "video_url"
                else "图片/音频接受 http(s) URL、Base64 或 asset:// 素材 ID，"
            )
            raise RuntimeError(
                f"Seedance 素材地址无效（{kind}）：{extra}当前地址是 {value[:60]}。请重新导入素材后重试。"
            )


def compile_body_for_send(spec: SeedanceJobSpec, request_body: dict) -> dict:
    """发送前收敛：adaptive 删 ratio、-1 删 duration、首尾帧角色收敛为 reference_image（官方只认参考角色）。"""
    body = dict(request_body)
    if body.get("ratio") == "adaptive":
        body.pop("ratio", None)
    if body.get("duration") == -1:
        body.pop("duration", None)
    content = []
    for item in body.get("content", []):
        if item.get("role") in ("first_frame", "last_frame"):
            item = {**item, "role": "reference_image"}
        content.append(item)
    body["content"] = content
    body.pop("omni_reference_task_type", None)  # 显式声明字段待官方实测验证，先不下发（与画布版一致）
    return body


def run_ark_seedance(
    spec: SeedanceJobSpec,
    request_body: dict,
    api_key: str,
    poll_interval_seconds: int = 5,
    timeout_seconds: int = 1800,
    progress=None,
) -> dict:
    """提交 + 轮询；返回 {taskId, videoUrl}。progress 可选回调打印状态。"""
    validate_content_urls(request_body)
    body = compile_body_for_send(spec, request_body)
    headers = {"content-type": "application/json", "authorization": f"Bearer {api_key.strip()}"}

    if progress:
        progress("提交 Seedance 任务…")
    response, payload = request_json("POST", f"{ARK_BASE_URL}{ENDPOINT}", phase="提交 Seedance 任务", headers=headers, json_body=body)
    if response.status_code != 200:
        raise read_ark_error(response, payload, body)
    task_id = str((payload or {}).get("id") or (payload or {}).get("task_id") or "")
    if not task_id:
        raise RuntimeError("Seedance 未返回任务 ID")

    deadline = time.time() + timeout_seconds
    last_status = ""
    while time.time() < deadline:
        response, payload = request_json(
            "GET", f"{ARK_BASE_URL}{ENDPOINT}/{task_id}", phase="查询 Seedance 任务", headers=headers
        )
        if response.status_code != 200:
            raise RuntimeError(f"查询 Seedance 任务失败（HTTP {response.status_code}）：{response.text[:300]}")
        status = str((payload or {}).get("status") or "running")
        if status != last_status:
            last_status = status
            if progress:
                progress(f"生成中（{status}）…")
        output = (payload or {}).get("output") or {}
        video_url = str(
            output.get("video_url") or output.get("url")
            or (payload or {}).get("video_url") or (payload or {}).get("url") or ""
        )
        if video_url and _TERMINAL_OK.search(status):
            return {"taskId": task_id, "videoUrl": video_url}
        if _TERMINAL_BAD.search(status):
            error = (payload or {}).get("error")
            if isinstance(error, dict):
                message = error.get("message") or f"任务{status}"
            else:
                message = str(error) if error else f"任务{status}"
            raise RuntimeError(str(message))
        time.sleep(poll_interval_seconds)
    raise RuntimeError("Seedance 任务等待超时（30 分钟）")
