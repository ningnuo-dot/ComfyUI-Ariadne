// 优化器客户端：走 /ariadne/optimize 服务端中转（SSE 流式），AbortController 中断。
// SSE 增量解析与 ariadne_core/seedance/optimizer.py 同契约：心跳、半包、[DONE]、
// 非 data 行一律忽略；服务端以 data: {"delta": "..."} / {"error": "..."} / {"done": true} 下发。
// 纯模块（无宿主依赖），可被 node --test 直接导入。

export function newStreamState() {
    return { buffer: "", text: "", error: "", done: false };
}

export function feedStreamEvent(state, chunk) {
    state.buffer += String(chunk ?? "");
    const lines = state.buffer.split("\n");
    state.buffer = lines.pop() || "";
    for (const raw of lines) {
        const line = raw.replace(/\r$/, "");
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload || payload === "[DONE]") continue;
        let event;
        try {
            event = JSON.parse(payload);
        } catch {
            continue;
        }
        if (typeof event?.delta === "string" && event.delta) state.text += event.delta;
        if (typeof event?.error === "string" && event.error && !state.error) state.error = event.error;
        if (event?.done) state.done = true;
    }
    return state;
}

// 发起优化。options: {onDelta(text), signal, skill}；resolve 最终全文，中断 resolve 已生成的部分。
export async function runOptimizer(userContent, options = {}) {
    const state = newStreamState();
    const response = await fetch("/ariadne/optimize", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt: userContent, skill: options.skill }),
        signal: options.signal,
    });
    if (!response.ok) {
        let detail = "";
        try {
            detail = (await response.json())?.error || "";
        } catch { /* 忽略非 JSON 错误体 */ }
        throw new Error(`优化请求失败（HTTP ${response.status}）${detail.slice(0, 200)}`);
    }
    if (!response.body) throw new Error("响应没有内容流");
    // 兼容回落：旧版后端返回 {"text": ...} JSON（非流式）时，一次性并入文本，不伪造逐字动画。
    if (String(response.headers.get("content-type") || "").includes("application/json")) {
        const payload = await response.json().catch(() => ({}));
        if (payload.error) throw new Error(payload.error);
        const text = typeof payload.text === "string" ? payload.text.trim() : "";
        if (!text) throw new Error("模型没有返回内容，请检查优化器配置或稍后重试");
        options.onDelta?.(text);
        return text;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        feedStreamEvent(state, decoder.decode(value, { stream: true }));
        if (options.onDelta && state.text) options.onDelta(state.text);
    }
    if (state.error) throw new Error(state.error);
    return state.text.trim();
}
