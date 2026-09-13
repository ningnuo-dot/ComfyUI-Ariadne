"""Ariadne 自有 HTTP 路由：素材上传 / ffmpeg 裁剪与切点 / 估价 / 配置 / TOS 试传 / 提示词优化。

守卫照抄本机 ComfyUI-Kie 实测模式：loopback 限定（全部端点）+ 注册幂等（_routes._items 查重）。
阻塞调用（ffmpeg/requests/probe）一律 asyncio.to_thread，防止冻结事件循环拖死 Web UI。
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

from ariadne_core import config, topaz
from ariadne_core.media import detect_cut_points, trim_video
from ariadne_core.seedance import pricing
from ariadne_core.seedance.ark_media import probe_video

UPLOAD_SIZE_CAP = 200 * 1024 * 1024


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
        """input 目录内解析素材路径；relative_to 收口防兄弟目录穿越（normcase 兼容 Windows 大小写）。"""
        base = _input_base()
        if subfolder and (os.path.isabs(subfolder) or ":" in subfolder or ".." in Path(subfolder).parts):
            raise ValueError("subfolder 不允许绝对路径或 ..")
        target = (base / subfolder / name).resolve() if subfolder else (base / name).resolve()
        norm_base = os.path.normcase(str(base))
        norm_target = os.path.normcase(str(target))
        if norm_target == norm_base or not norm_target.startswith(norm_base + os.sep):
            raise ValueError("素材路径越界")
        return target

    async def _json_body(request) -> dict:
        """畸形请求统一 400（不让 JSONDecodeError/类型错打 500）。"""
        try:
            body = await request.json()
        except Exception as error:  # noqa: BLE001
            raise ValueError(f"请求体不是合法 JSON：{error}") from error
        if not isinstance(body, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return body

    # ---- 素材上传（瓦片入口）：分块写盘，不全量进内存 ----
    if _ensure("POST", "/ariadne/upload"):
        @routes.post("/ariadne/upload")
        async def ariadne_upload(request):
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)
            try:
                reader = await request.multipart()
            except Exception as error:  # noqa: BLE001
                return web.json_response({"error": f"不是 multipart 请求：{error}"}, status=400)
            field = await reader.next()
            if field is None or field.name != "file":
                return web.json_response({"error": "缺少 file 字段"}, status=400)
            original_name = field.filename or "asset.bin"
            ext = Path(original_name).suffix.lower() or ".bin"
            kind = request.query.get("kind", "")
            if kind not in ("image", "video", "audio"):
                kind = "video" if ext in (".mp4", ".mov", ".webm", ".mkv", ".m4v") else ("audio" if ext in (".mp3", ".wav", ".m4a", ".aac", ".flac") else "image")
            subfolder = f"ariadne/{kind}"
            target_dir = _input_base() / subfolder
            target_dir.mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex[:8]}-{Path(original_name).stem[:40]}{ext}"
            target = target_dir / name
            written = 0
            try:
                with open(target, "wb") as handle:
                    while not field.at_eof():
                        chunk = await field.read_chunk(1 << 20)
                        written += len(chunk)
                        if written > UPLOAD_SIZE_CAP:
                            raise ValueError("文件超过 200MB 上限")
                        handle.write(chunk)
            except ValueError as error:
                target.unlink(missing_ok=True)
                return web.json_response({"error": str(error)}, status=400)
            except Exception as error:  # noqa: BLE001
                target.unlink(missing_ok=True)
                return web.json_response({"error": f"上传中断：{error}"}, status=400)

            payload = {"kind": kind, "name": name, "subfolder": subfolder, "role": request.query.get("role", ""), "seconds": 0, "width": 0, "height": 0, "pixels": 0}
            if kind == "video":
                try:
                    info = await asyncio.to_thread(probe_video, str(target))
                    payload.update(info)
                    payload["pixelsOk"] = info["pixels"] >= 407696
                except Exception as error:  # noqa: BLE001
                    payload["probeError"] = str(error)
            return web.json_response(payload)

    # ---- 打开素材文件夹：让用户直接看到 input/ariadne 下的原始文件（可手动清理） ----
    if _ensure("POST", "/ariadne/open_assets_folder"):
        @routes.post("/ariadne/open_assets_folder")
        async def ariadne_open_assets_folder(request):
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)
            target = _input_base() / "ariadne"
            target.mkdir(parents=True, exist_ok=True)
            try:
                if hasattr(os, "startfile"):  # Windows：资源管理器打开
                    os.startfile(str(target))  # noqa: S606
                else:
                    import subprocess
                    import sys
                    opener = "open" if sys.platform == "darwin" else "xdg-open"
                    subprocess.Popen([opener, str(target)])
                return web.json_response({"ok": True, "path": str(target)})
            except Exception as error:  # noqa: BLE001
                return web.json_response({"error": f"打开失败：{error}"}, status=500)

    # ---- 裁剪：切点检测 + 执行 ----
    if _ensure("POST", "/ariadne/trim"):
        @routes.post("/ariadne/trim")
        async def ariadne_trim(request):
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)
            try:
                body = await _json_body(request)
                path = _resolve_input(str(body.get("name")), str(body.get("subfolder") or "ariadne/video"))
            except ValueError as error:
                return web.json_response({"error": str(error)}, status=400)
            if not path.is_file():
                return web.json_response({"error": f"视频不存在：{body.get('name')}"}, status=404)
            if body.get("detect"):
                try:
                    points = await asyncio.to_thread(detect_cut_points, str(path))
                except Exception as error:  # noqa: BLE001
                    return web.json_response({"error": f"切点检测失败：{error}"}, status=400)
                return web.json_response({"cutPoints": points})
            ranges = body.get("ranges") or []
            try:
                output = await asyncio.to_thread(
                    trim_video, str(path), ranges, str(_input_base() / "ariadne" / "trim"), str(body.get("name") or path.name)
                )
            except RuntimeError as error:
                return web.json_response({"error": str(error)}, status=400)
            info = await asyncio.to_thread(probe_video, output)
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
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)
            try:
                body = await _json_body(request)
                # kind=topaz：按源视频时长 × 倍数估价（Topaz 节点专用，与 Seedance 口径独立）
                if str(body.get("kind") or "") == "topaz":
                    factor = topaz.parse_factor(body.get("factor") or "2")
                    seconds = float(body.get("durationSeconds") or 0)
                    if seconds <= 0:
                        return web.json_response({"estimate": None})
                    return web.json_response({"estimate": {"cny": topaz.estimate_cny(seconds, factor), "unit": "CNY"}})
                channel = str(body.get("channel") or "ark")
                resolution = str(body.get("resolution") or "720p")
                duration = int(body.get("duration") or 0)
                includes_video = bool(body.get("includesVideoInput"))
                input_seconds = float(body.get("inputVideoSeconds") or 0)
            except (ValueError, TypeError) as error:
                return web.json_response({"error": f"参数无效：{error}"}, status=400)
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
            try:
                body = await _json_body(request)
            except ValueError as error:
                return web.json_response({"error": str(error)}, status=400)
            try:
                config.save_config(body)
            except (TypeError, AttributeError, OSError) as error:
                return web.json_response({"error": f"配置写入失败：{error}"}, status=400)
            return web.json_response(config.masked_config())

    # ---- TOS 试传（一键验证桶配置） ----
    if _ensure("POST", "/ariadne/tos_test"):
        @routes.post("/ariadne/tos_test")
        async def ariadne_tos_test(request):
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)

            def _test():
                from ariadne_core.tos import upload_file

                settings = config.tos_settings()
                if not settings:
                    raise RuntimeError("尚未配置 TOS AK/SK")
                import tempfile

                probe = Path(tempfile.gettempdir()) / f"ariadne-tos-test-{uuid.uuid4().hex[:6]}.txt"
                probe.write_text("ariadne tos test", encoding="utf-8")
                try:
                    url = upload_file(settings, f"seedance/test/{probe.name}", str(probe))
                finally:
                    probe.unlink(missing_ok=True)
                return url

            try:
                url = await asyncio.to_thread(_test)
                return web.json_response({"ok": True, "urlHead": url[:120]})
            except Exception as error:  # noqa: BLE001
                return web.json_response({"error": str(error)}, status=400)

    # ---- 优化器模型列表代理（原版拉取模型能力；表单里填的站点/Key 可直接用于拉取，
    #      但只在本次请求内使用，不落盘——Key 始终不进浏览器存储） ----
    if _ensure("POST", "/ariadne/optimize_models"):
        @routes.post("/ariadne/optimize_models")
        async def ariadne_optimize_models(request):
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)
            from ariadne_core.seedance import optimizer as optimizer_core

            try:
                body = await _json_body(request)
            except ValueError as error:
                return web.json_response({"error": str(error)}, status=400)
            opt = config.load_config().get("optimizer") or {}
            base_url = optimizer_core.normalize_base_url(str(body.get("base_url") or opt.get("base_url") or ""))
            api_key = str(body.get("api_key") or opt.get("api_key") or "").strip()
            if not (base_url and api_key):
                return web.json_response({"error": "请先填写站点与 API Key 再拉取"}, status=400)
            if not optimizer_core.valid_base_url(base_url):
                return web.json_response({"error": "优化器站点地址必须以 http:// 或 https:// 开头"}, status=400)
            import aiohttp

            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as client:
                    async with client.get(f"{base_url}/models",
                                          headers={"authorization": f"Bearer {api_key}"}) as upstream:
                            text = await upstream.text()
                            if upstream.status != 200:
                                return web.json_response({"error": f"拉取模型失败（HTTP {upstream.status}）：{text[:160]}"}, status=502)
                            payload = json.loads(text) if text.strip() else {}
            except Exception as error:  # noqa: BLE001
                return web.json_response({"error": f"拉取模型失败：{error}"}, status=502)
            ids = []
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, list):
                ids = sorted({str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")})
            return web.json_response({"models": ids})

    # ---- 提示词优化：服务端中转 OpenAI 兼容接口（SSE 流式透传，非流式回落）。
    #      系统规则（sd25-pe 技能原文）只在服务端注入；密钥只在服务端使用，不回传浏览器。
    #      守卫：loopback 限定 + base_url 必须 http(s)（base_url 来自请求体，缺守卫即 SSRF）。 ----
    if _ensure("POST", "/ariadne/optimize"):
        @routes.post("/ariadne/optimize")
        async def ariadne_optimize(request):
            if not _loopback_only(request):
                return web.json_response({"error": "仅限本机访问"}, status=403)
            try:
                body = await _json_body(request)
            except ValueError as error:
                return web.json_response({"error": str(error)}, status=400)
            opt = config.load_config().get("optimizer") or {}
            from ariadne_core.seedance import optimizer as optimizer_core

            base_url = optimizer_core.normalize_base_url(str(body.get("base_url") or opt.get("base_url") or ""))
            model = str(body.get("model") or opt.get("model") or "").strip()
            api_key = str(opt.get("api_key") or "").strip()  # 请求体不再收 Key：密钥只在服务端
            user_content = str(body.get("prompt") or "")
            # skill 按节点类型区分（Seedance 2.5 = sd25-pe；文件名白名单校验防路径注入）。
            skill = str(body.get("skill") or optimizer_core.DEFAULT_SKILL).strip()
            if not optimizer_core.valid_skill_name(skill):
                return web.json_response({"error": f"未知优化技能：{skill}"}, status=400)
            if not (base_url and model and api_key):
                return web.json_response({"error": "优化器未配置完整：请在侧栏「Ariadne 设置」填写站点/模型/Key"}, status=400)
            if not optimizer_core.valid_base_url(base_url):
                return web.json_response({"error": "优化器站点地址必须以 http:// 或 https:// 开头"}, status=400)
            disable_thinking = optimizer_core.supports_thinking_toggle(base_url)

            import json as _json

            import aiohttp  # ComfyUI 服务端自带依赖

            upstream_body = optimizer_core.build_chat_body(model, user_content, disable_thinking, skill)
            headers = {"content-type": "application/json", "authorization": f"Bearer {api_key}"}
            timeout = aiohttp.ClientTimeout(total=300, connect=15)

            def _parser():
                return optimizer_core.new_sse_parser()

            # 已向客户端 prepare 的流；一旦建立，后续错误一律以 SSE error 事件下发，
            # 绝不再返回 JSON 响应（同一连接上二次写响应会污染字节流）。
            live_stream: list = []

            async def _stream_response(client):
                """SSE 透传：上游 delta → 本地 data: {delta}; 结束发 data: [DONE]。"""
                response = web.StreamResponse(headers={
                    "content-type": "text/event-stream; charset=utf-8",
                    "cache-control": "no-cache",
                    "x-accel-buffering": "no",
                })
                await response.prepare(request)
                live_stream.append(response)

                async def _send(payload: dict):
                    await response.write(f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8"))

                # 上游非 200：无论内容型是否 SSE，统一先报错，不把错误体当对话正文解析/透传。
                if upstream.status != 200:
                    error_text = await upstream.text()
                    await _send({"error": f"优化器返回 HTTP {upstream.status}：{error_text[:200]}"})
                    await _send({"done": True})
                    await response.write_eof()
                    return response

                # upstream.headers 是 CIMultiDict（大小写不敏感）；转成普通 dict 会丢这个性质。
                if "text/event-stream" in upstream.headers.get("content-type", ""):
                    state = _parser()
                    buf = b""
                    async for raw in upstream.content:
                        buf += raw
                        # 只解码到最近一个完整行（\n 不会出现在多字节 UTF-8 序列内部，
                        # 按行切分不会切碎中文字符；残行留在 buf 等下一个 chunk）。
                        while b"\n" in buf:
                            line, buf = buf.split(b"\n", 1)
                            for delta in optimizer_core.feed_sse(state, line.decode("utf-8", "replace") + "\n"):
                                await _send({"delta": delta})
                    if buf.strip():
                        # 上游末尾无换行的残行：收尾补喂一次，避免丢最后一个事件
                        for delta in optimizer_core.feed_sse(state, buf.decode("utf-8", "replace") + "\n"):
                            await _send({"delta": delta})
                else:
                    # 非流式回落：上游不支持 SSE 时一次性取回正文，不伪造逐字动画。
                    text = await upstream.text()
                    try:
                        payload = _json.loads(text) if text.strip() else {}
                    except ValueError:
                        payload = {}  # 上游错误页/纯文本：按结构异常报错
                    try:
                        content = payload["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError):
                        await _send({"error": f"优化器响应结构异常：{str(payload)[:200]}"})
                    else:
                        if content:
                            await _send({"delta": content})
                await _send({"done": True})
                await response.write_eof()
                return response

            try:
                async with aiohttp.ClientSession(timeout=timeout) as client:
                    async with client.post(f"{base_url}/chat/completions", headers=headers,
                                           json=upstream_body) as upstream:
                        return await _stream_response(client)
            except asyncio.CancelledError:
                # 前端 AbortController 断开：aiohttp 取消处理协程，直接上抛结束透传。
                raise
            except asyncio.TimeoutError:
                if live_stream:
                    return live_stream[0]
                return web.json_response({"error": "优化请求超时（300s）"}, status=504)
            except Exception as error:  # noqa: BLE001
                import traceback

                traceback.print_exc()  # 流式链路错误留痕（静默 502 最难查）
                if live_stream:
                    try:
                        error_event = _json.dumps({"error": f"优化请求失败：{error}"}, ensure_ascii=False)
                        await live_stream[0].write(f"data: {error_event}\n\n".encode("utf-8"))
                        await live_stream[0].write_eof()
                    except Exception:  # noqa: BLE001
                        pass
                    return live_stream[0]
                return web.json_response({"error": f"优化请求失败：{error}"}, status=502)
