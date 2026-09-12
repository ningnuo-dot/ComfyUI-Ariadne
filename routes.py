"""Ariadne 自有 HTTP 路由：素材上传 / ffmpeg 裁剪与切点 / 估价 / 配置 / TOS 试传 / 提示词优化。

守卫照抄本机 ComfyUI-Kie 实测模式：loopback 限定 + 注册幂等（_routes._items 查重）。
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from ariadne_core import config
from ariadne_core.media import detect_cut_points, trim_video
from ariadne_core.seedance import pricing
from ariadne_core.seedance.ark_media import probe_video


def _loopback_only(request) -> bool:
    return request.remote in ("127.0.0.1", "::1", None)


def register_routes():
    """注册全部路由（PromptServer 未创建时静默跳过——单测/语法检查环境）。"""
    from aiohttp import web
    from server import PromptServer

    routes = PromptServer.instance.routes
    registered = {
        (getattr(item, "method", None), getattr(item, "path", None))
        for item in getattr(routes, "_items", ()) or ()
    }

    def _ensure(method: str, path: str):
        if (method, path) in registered:
            return False
        registered.add((method, path))
        return True

    def _input_base():
        import folder_paths

        return Path(folder_paths.get_input_directory()).resolve()

    def _resolve_input(name: str, subfolder: str) -> Path:
        base = _input_base()
        target = (base / subfolder / name).resolve() if subfolder else (base / name).resolve()
        if not str(target).startswith(str(base)):
            raise ValueError("素材路径越界")
        return target

    # ---- 素材上传（瓦片入口） ----
    if _ensure("POST", "/ariadne/upload"):
        @routes.post("/ariadne/upload")
        async def ariadne_upload(request):
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)
            reader = await request.multipart()
            field = await reader.next()
            if field is None or field.name != "file":
                return web.json_response({"error": "缺少 file 字段"}, status=400)
            size_cap = 200 * 1024 * 1024
            data = b""
            while not field.at_eof():
                chunk = await field.read_chunk(1 << 20)
                data += chunk
                if len(data) > size_cap:
                    return web.json_response({"error": "文件超过 200MB 上限"}, status=400)
            role = request.query.get("role", "")
            original_name = field.filename or "asset.bin"
            ext = Path(original_name).suffix.lower() or ".bin"
            kind = {"image": "image", "video": "video", "audio": "audio"}.get(request.query.get("kind", ""), None)
            if kind is None:
                kind = "video" if ext in (".mp4", ".mov", ".webm", ".m4v") else ("audio" if ext in (".mp3", ".wav", ".m4a", ".aac", ".flac") else "image")
            subfolder = f"ariadne/{kind}"
            target_dir = _input_base() / subfolder
            target_dir.mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex[:8]}-{Path(original_name).stem[:40]}{ext}"
            (target_dir / name).write_bytes(data)

            payload = {"kind": kind, "name": name, "subfolder": subfolder, "role": role, "seconds": 0, "width": 0, "height": 0, "pixels": 0}
            if kind == "video":
                try:
                    info = probe_video(str(target_dir / name))
                    payload.update(info)
                    payload["pixelsOk"] = info["pixels"] >= 407696
                except Exception as error:  # noqa: BLE001
                    payload["probeError"] = str(error)
            return web.json_response(payload)

    # ---- 裁剪：切点检测 + 执行 ----
    if _ensure("POST", "/ariadne/trim"):
        @routes.post("/ariadne/trim")
        async def ariadne_trim(request):
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)
            body = await request.json()
            try:
                path = _resolve_input(str(body.get("name")), str(body.get("subfolder") or "ariadne/video"))
            except ValueError:
                return web.json_response({"error": "素材路径越界"}, status=400)
            if not path.is_file():
                return web.json_response({"error": f"视频不存在：{body.get('name')}"}, status=404)
            if body.get("detect"):
                return web.json_response({"cutPoints": detect_cut_points(str(path))})
            ranges = body.get("ranges") or []
            try:
                output = trim_video(str(path), ranges, str(_input_base() / "ariadne" / "trim"), str(body.get("name") or path.name))
            except RuntimeError as error:
                return web.json_response({"error": str(error)}, status=400)
            info = probe_video(output)
            return web.json_response({
                "name": Path(output).name, "subfolder": "ariadne/trim", "kind": "video",
                "role": body.get("role") or "motion", "seconds": info["seconds"],
                "width": info["width"], "height": info["height"], "pixels": info["pixels"],
                "pixelsOk": info["pixels"] >= 407696, "trimmed": True,
            })

    # ---- 估价（仅展示不扣费） ----
    if _ensure("POST", "/ariadne/estimate"):
        @routes.post("/ariadne/estimate")
        async def ariadne_estimate(request):
            body = await request.json()
            channel = str(body.get("channel") or "ark")
            resolution = str(body.get("resolution") or "720p")
            duration = int(body.get("duration") or 0)
            includes_video = bool(body.get("includesVideoInput"))
            input_seconds = float(body.get("inputVideoSeconds") or 0)
            if channel == "kie":
                credits = pricing.estimate_kie_credits(resolution, duration, includes_video, input_seconds)
                if credits is None:
                    return web.json_response({"estimate": None})
                return web.json_response({"estimate": {
                    "credits": round(credits),
                    "cny": round(credits * pricing.KIE_RATES["cnyPerCredit"], 2),
                    "usd": round(credits * pricing.KIE_RATES["usdPerCredit"], 3),
                    "unit": "credits",
                }})
            price = pricing.estimate_ark_price(resolution, duration, includes_video=includes_video, input_video_seconds=input_seconds)
            return web.json_response({"estimate": None if price is None else {"cny": price, "unit": "CNY"}})

    # ---- 配置（脱敏回显 / 合并写入） ----
    if _ensure("GET", "/ariadne/config"):
        @routes.get("/ariadne/config")
        async def ariadne_config_get(request):
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)
            return web.json_response(config.masked_config())

    if _ensure("POST", "/ariadne/config"):
        @routes.post("/ariadne/config")
        async def ariadne_config_set(request):
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)
            body = await request.json()
            config.save_config(body)
            return web.json_response(config.masked_config())

    # ---- TOS 试传（一键验证桶配置） ----
    if _ensure("POST", "/ariadne/tos_test"):
        @routes.post("/ariadne/tos_test")
        async def ariadne_tos_test(request):
            from ariadne_core.tos import upload_file

            settings = config.tos_settings()
            if not settings:
                return web.json_response({"error": "尚未配置 TOS AK/SK"}, status=400)
            try:
                import tempfile

                probe = Path(tempfile.gettempdir()) / f"ariadne-tos-test-{uuid.uuid4().hex[:6]}.txt"
                probe.write_text("ariadne tos test", encoding="utf-8")
                url = upload_file(settings, f"seedance/test/{probe.name}", str(probe))
                os.remove(probe)
                return web.json_response({"ok": True, "urlHead": url[:120]})
            except Exception as error:  # noqa: BLE001
                return web.json_response({"error": str(error)}, status=400)

    # ---- 提示词优化（服务端中转 OpenAI 兼容接口，非流式 v0.1） ----
    if _ensure("POST", "/ariadne/optimize"):
        @routes.post("/ariadne/optimize")
        async def ariadne_optimize(request):
            from ariadne_core.http import request_json

            body = await request.json()
            opt = config.load_config().get("optimizer") or {}
            base_url = str(body.get("base_url") or opt.get("base_url") or "").strip().rstrip("/")
            model = str(body.get("model") or opt.get("model") or "").strip()
            api_key = str(body.get("api_key") or opt.get("api_key") or "").strip()
            prompt = str(body.get("prompt") or "")
            if not (base_url and model and api_key):
                return web.json_response({"error": "优化器未配置完整：请在 Ariadne 工作台填写站点/模型/Key"}, status=400)
            response, payload = request_json(
                "POST", f"{base_url}/chat/completions", phase="提示词优化",
                headers={"content-type": "application/json", "authorization": f"Bearer {api_key}"},
                json_body={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
                timeout=300,
            )
            if response.status_code != 200:
                return web.json_response({"error": f"优化器返回 HTTP {response.status_code}：{response.text[:200]}"}, status=502)
            try:
                text = payload["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                return web.json_response({"error": f"优化器响应结构异常：{str(payload)[:200]}"}, status=502)
            return web.json_response({"text": text})
