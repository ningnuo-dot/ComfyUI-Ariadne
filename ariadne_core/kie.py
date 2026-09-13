"""Kie（api.kie.ai）共用客户端：上传、createTask/recordInfo 任务流（画布插件 kie.ts + 本机
ComfyUI-Kie 基线的 Python 合并版），供 Seedance/Veo/Kling/图片节点共用。

坑位继承：上传文件名必须带随机后缀（Date.now 同毫秒撞名会按名去重，2026-09-10 任务
e7d40b79 的多图坍缩根因）；上传偶发 TLS 断开重试 3 次；input 字段白名单严格核对。
"""
from __future__ import annotations

import json
import random
import time
import urllib.parse
from pathlib import Path

from .http import request_json

KIE_BASE_URL = "https://api.kie.ai"
KIE_UPLOAD_URL = "https://kieai.redpandaai.co/api/file-stream-upload"
UPLOAD_RETRIES = 3
UPLOAD_PATH = {"image": "images/user-uploads", "video": "videos/user-uploads", "audio": "audio/user-uploads"}
KIND_LABEL = {"image": "图片", "video": "视频", "audio": "音频"}


UPLOAD_PROGRESS: dict[str, dict] = {}  # 上传进度注册表（节点 id → sent/total/name），执行线程内原子赋值，GIL 安全


class _CountingFile:
    """包装只读句柄：requests 分块读取时累计已发字节并写入进度注册表。"""

    def __init__(self, handle, total: int, progress_key: str):
        self._handle = handle
        self._key = progress_key
        self.len = total  # requests 的 super_len 读 .len 定 Content-Length

    def read(self, size: int = -1):
        chunk = self._handle.read(size)
        entry = UPLOAD_PROGRESS.get(self._key)
        if entry is not None:
            entry["sent"] += len(chunk)
        return chunk

    def close(self):
        self._handle.close()


def upload_to_kie(kind: str, file_path: str, api_key: str, progress_key: str | None = None) -> str:
    """上传本地文件到 Kie 自家接口（图片≤30MB/视频≤200MB/音频≤15MB），返回公网 downloadUrl。

    progress_key 给定时把上传进度写进 UPLOAD_PROGRESS[progress_key]（面板轮询用），结束后移除。
    """
    path = Path(file_path)
    last_error: Exception | None = None
    try:
        for attempt in range(1, UPLOAD_RETRIES + 1):
            try:
                import requests

                name = f"ariadne-{kind}-{int(time.time() * 1000)}-{random.randbytes(4).hex()}{path.suffix or ''}"
                with open(path, "rb") as handle:
                    upload_source = handle
                    if progress_key:
                        total = path.stat().st_size
                        UPLOAD_PROGRESS[progress_key] = {"sent": 0, "total": total, "name": path.name}
                        upload_source = _CountingFile(handle, total, progress_key)
                    response = requests.post(
                        KIE_UPLOAD_URL,
                        headers={"authorization": f"Bearer {api_key.strip()}"},
                        files={"file": (name, upload_source)},
                        data={"uploadPath": UPLOAD_PATH[kind], "fileName": name},
                        timeout=600,
                    )
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                if response.status_code != 200 or not (payload or {}).get("data"):
                    raise RuntimeError(
                        f"Kie 上传接口返回 HTTP {response.status_code}：{(payload or {}).get('message') or '无响应体'}"
                    )
                url = str((payload["data"] or {}).get("downloadUrl") or (payload["data"] or {}).get("fileUrl") or "")
                if not url:
                    raise RuntimeError("Kie 上传接口未返回 downloadUrl")
                return url
            except Exception as error:  # noqa: BLE001 - 重试后统一抛出
                last_error = error
                if attempt < UPLOAD_RETRIES:
                    time.sleep(0.8 * attempt)
    finally:
        if progress_key:
            UPLOAD_PROGRESS.pop(progress_key, None)
    raise RuntimeError(f"向 Kie 上传{KIND_LABEL[kind]}素材失败（已重试 {UPLOAD_RETRIES} 次）：{last_error}")


def translate_kie_error(status: int, payload: dict | None, phase: str, api_key_hint: str = "「Ariadne 设置」侧栏") -> RuntimeError:
    """createTask/轮询错误翻译：Kie 业务错误放在信封 msg 字段且 HTTP 常为 200，必须读信封而非状态码。"""
    payload = payload if isinstance(payload, dict) else {}
    code = payload.get("code")
    raw = str(payload.get("msg") or payload.get("message") or "")
    if not raw and payload.get("data") is not None:
        raw = json.dumps(payload.get("data"), ensure_ascii=False)[:300]
    if not raw:
        raw = f"HTTP {status}" + ("（响应体为空或非 JSON）" if status == 200 else "")
    raw_lower = raw.lower()
    if status == 401 or "api key" in raw_lower:
        return RuntimeError(f"Kie 密钥无效或未授权（{phase}）：请在 {api_key_hint} 里检查 Kie Key。原始信息：{raw}")
    if "model name you specified is not supported" in raw_lower:
        return RuntimeError(f"Kie 不支持该模型标识（{phase}）。原始信息：{raw}")
    if "model format is incorrect" in raw_lower:
        return RuntimeError(f"Kie 模型标识格式错误（{phase}）：标识最多两段 provider/模型。原始信息：{raw}")
    if "server exception" in raw_lower:
        return RuntimeError(f"Kie 拒绝了请求中的未知参数（{phase}）：input 只允许官方页面列出的字段。原始信息：{raw}")
    prefix = f"（code={code}）" if code not in (None, 200) else ""
    return RuntimeError(f"Kie {phase}失败{prefix}（HTTP {status}）：{raw}")


def create_task(body: dict, api_key: str, phase: str = "创建任务") -> str:
    """Kie 统一任务端点 POST /api/v1/jobs/createTask，返回 taskId。"""
    headers = {"content-type": "application/json", "authorization": f"Bearer {api_key.strip()}"}
    response, payload = request_json("POST", f"{KIE_BASE_URL}/api/v1/jobs/createTask", phase=phase, headers=headers, json_body=body)
    data = payload.get("data") if isinstance(payload, dict) else None
    if response.status_code != 200 or not (data or {}).get("taskId"):
        raise translate_kie_error(response.status_code, payload, phase)
    return str(data["taskId"])


# 终态收敛（kling TS 契约枚举 waiting/queuing/generating/success/failed + 实测 fail/completed 变体）：
_TERMINAL_BAD = ("fail", "failed", "error")
_TERMINAL_OK = ("success", "completed")


def poll_task(
    task_id: str,
    api_key: str,
    poll_interval_seconds: int = 5,
    timeout_seconds: int = 1800,
    progress=None,
    fail_hints: dict | None = None,
) -> dict:
    """轮询 recordInfo 到终态；返回 {state, resultUrls, remainedCredits}。"""
    headers = {"authorization": f"Bearer {api_key.strip()}"}
    deadline = time.time() + timeout_seconds
    last_state = ""
    while time.time() < deadline:
        time.sleep(poll_interval_seconds)
        response, payload = request_json(
            "GET", f"{KIE_BASE_URL}/api/v1/jobs/recordInfo?taskId={urllib.parse.quote(task_id)}", phase="查询任务", headers=headers
        )
        if response.status_code != 200:
            raise translate_kie_error(response.status_code, payload, "查询任务")
        data = payload.get("data") if isinstance(payload, dict) else None
        data = data or {}
        state = str(data.get("state") or "unknown")
        if state != last_state:
            last_state = state
            if progress:
                progress("生成完成，取回成片…" if state in _TERMINAL_OK else f"生成中（{state}）…")
        if state in _TERMINAL_BAD:
            fail_msg = str(data.get("failMsg") or "任务失败")
            hint = ""
            fail_lower = fail_msg.lower()
            for pattern, text in (fail_hints or {}).items():
                if pattern.lower() in fail_lower:
                    hint = text
                    break
            raise RuntimeError(f"任务失败：{fail_msg}{('' if not hint else chr(10) + hint)}")
        if state in _TERMINAL_OK:
            urls = normalize_result_urls(str(data.get("resultJson") or ""))
            credits = data.get("remainedCredits")
            consumed = data.get("creditsConsumed")
            return {
                "state": state,
                "resultUrls": urls,
                "remainedCredits": credits if isinstance(credits, (int, float)) else None,
                # 实耗积分（recordInfo 原样带回，部分模型可能缺失）：用于任务信息展示。
                "creditsConsumed": consumed if isinstance(consumed, (int, float)) else None,
            }
    raise RuntimeError("任务等待超时（30 分钟）")


def normalize_result_urls(result_json: str | None) -> list[str]:
    """resultJson 容错解析：JSON 字符串 → resultUrls 数组；坏值返回空数组不让轮询层崩。"""
    import json

    if not result_json:
        return []
    try:
        parsed = json.loads(result_json)
        raw = parsed.get("resultUrls") if isinstance(parsed, dict) else None
        if isinstance(raw, list):
            return [url for url in raw if isinstance(url, str) and url]
        if isinstance(raw, str) and raw:
            return [raw]
    except ValueError:
        pass
    return []
