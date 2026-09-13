"""本地 mock OpenAI 兼容优化器（验证 /ariadne/optimize 流式链路用，零付费）。

用法：D:\\GitHub\\ComfyUI\\.venv\\Scripts\\python.exe tests/mock_optimizer_server.py [port]
- POST /chat/completions：SSE 流式返回五段回声文本（校验 system 规则已注入）；
- POST /chat/completions?mode=plain：返回非流式 JSON（验证回落）；
- GET /models：模型列表（不必须）。
"""
from __future__ import annotations

import asyncio
import json
import sys

from aiohttp import web


def _reply_text(body: dict) -> str:
    messages = body.get("messages") or []
    system = messages[0].get("content", "") if messages else ""
    user = messages[1].get("content", "") if len(messages) > 1 else ""
    has_rule = "Seedance 2.5 Prompt Optimizer" in system
    mode = "未知模式"
    for line in user.splitlines():
        if line.startswith("任务模式（用户已在页面选择）："):
            mode = line.split("：", 1)[1]
    return (
        f"【生成目标】\n（mock 流式回复）优化后的提示词正文。任务模式={mode}，系统规则{'已注入' if has_rule else '缺失'}。\n"
        "【参考素材职责】\n（mock）素材职责句占位。\n"
        "【事件脚本】\n开始时：占位。结束时：占位。\n"
        "【保持一致】\n（mock）保持项占位。"
    )


async def chat_completions(request: web.Request) -> web.StreamResponse:
    body = await request.json()
    if request.query.get("mode") == "plain":
        return web.json_response({"choices": [{"message": {"role": "assistant", "content": _reply_text(body)}}]})
    response = web.StreamResponse(headers={
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache",
    })
    await response.prepare(request)
    text = _reply_text(body)
    # 按字符小步发送，制造真实流式节奏（含中文多字节边界）
    for index in range(0, len(text), 3):
        chunk = text[index:index + 3]
        payload = json.dumps({"choices": [{"delta": {"content": chunk}}]}, ensure_ascii=False)
        await response.write(f"data: {payload}\n\n".encode("utf-8"))
        await asyncio.sleep(0.02)
    await response.write(b"data: [DONE]\n\n")
    await response.write_eof()
    return response


async def models(_: web.Request) -> web.Response:
    return web.json_response({"data": [{"id": "mock-optimizer"}]})


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8192
    app = web.Application()
    app.router.add_post("/chat/completions", chat_completions)
    app.router.add_get("/models", models)
    print(f"mock optimizer on http://127.0.0.1:{port}")
    web.run_app(app, host="127.0.0.1", port=port, print=None)


if __name__ == "__main__":
    main()
