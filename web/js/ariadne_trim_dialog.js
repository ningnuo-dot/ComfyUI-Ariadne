// 裁剪参考视频浮层：原画布插件 trim-page 同款布局——左侧视频预览 + 顶部全宽时间轴卡尺 + 右侧控制列。
// 交互：自动循环播放选中段；时间轴悬停出掠动跟随线（跟随开 = 擦洗预览）；手动模式可拖卡尺与整段平移，
// 悬停卡尺出 ±0.1s 微调（滚轮）；对齐/分镜只读展示；应用截断调 /ariadne/trim 产出上传瓦片。

import { tileKey, widgetValue } from "./ariadne_adapter.js";
import { commitTiles, viewUrl } from "./ariadne_media.js";

const TRIM_FMT = (value) => (Math.round(value * 10) / 10).toFixed(1);

function seekVideoTo(video, time) {
    return new Promise((resolve) => {
        if (Math.abs(video.currentTime - time) < 0.04) return resolve();
        const done = () => {
            video.removeEventListener("seeked", done);
            resolve();
        };
        video.addEventListener("seeked", done);
        video.currentTime = time;
    });
}

export function openTrimDialog(node, tile, onDone) {
    if (tile.kind !== "video") return;
    const url = viewUrl(tile);
    let sourceSeconds = Number(tile.seconds || 0);
    const outputDuration = Math.max(Number(widgetValue(node, "duration") ?? 0), 0);
    let mode = "align";
    let manual = { start: 0, end: Math.min(Math.max(outputDuration || 4, 1), Math.max(sourceSeconds || 1, 1)) };
    let cuts = null;
    let cutsReady = false;
    let playing = true;
    let skimFollow = true;
    let busyLabel = "";
    let range = { start: 0, end: sourceSeconds || 0 };

    const overlay = document.createElement("div");
    overlay.className = "ariadne-overlay";
    overlay.innerHTML = `
        <div class="ariadne-dialog ariadne-trim2">
            <div class="ariadne-trim2-head">
                <button type="button" class="ariadne-dock-mini ariadne-trim2-back" aria-label="返回">‹</button>
                <strong>✂ 裁剪参考视频</strong>
                <span class="ariadne-trim2-sub"></span>
            </div>
            <div class="ariadne-trim2-main">
                <div class="ariadne-trim2-preview">
                    <video class="ariadne-trim-video" src="${url}" muted playsinline loop></video>
                    <span class="ariadne-trim2-rangebadge"></span>
                </div>
                <div class="ariadne-trim2-controls">
                    <div class="ariadne-trim2-timeline">
                        <div class="ariadne-trim2-band"></div>
                        <div class="ariadne-trim2-tick"></div>
                        <div class="ariadne-trim2-handle ariadne-trim2-start" title="起点卡尺（手动模式可拖；悬停滚轮 ±0.1s）"></div>
                        <div class="ariadne-trim2-handle ariadne-trim2-end" title="终点卡尺（手动模式可拖；悬停滚轮 ±0.1s）"></div>
                        <div class="ariadne-trim2-skim"></div>
                        <div class="ariadne-trim2-playhead"></div>
                    </div>
                    <div class="ariadne-trim2-row">
                        <button type="button" class="ariadne-pill ariadne-dock-minitoggle ariadne-trim2-play">暂停</button>
                        <button type="button" class="ariadne-pill ariadne-dock-minitoggle ariadne-trim2-follow">⌖ 跟随 开</button>
                        <span class="ariadne-trim2-timetext"></span>
                    </div>
                    <div class="ariadne-trim2-row">
                        <div class="ariadne-trim2-modes">
                            <button type="button" class="ariadne-pill ariadne-dock-minitoggle" data-mode="align">对齐</button>
                            <button type="button" class="ariadne-pill ariadne-dock-minitoggle" data-mode="shots">分镜</button>
                            <button type="button" class="ariadne-pill ariadne-dock-minitoggle" data-mode="manual">手动</button>
                        </div>
                        <span class="ariadne-trim2-msg"></span>
                    </div>
                    <div class="ariadne-trim2-row ariadne-trim2-actionsrow">
                        <span class="ariadne-trim2-error"></span>
                        <button type="button" class="ariadne-pill ariadne-pill-apply ariadne-trim2-apply">应用截断</button>
                    </div>
                </div>
            </div>
            <div class="ariadne-trim2-hint">计费提示：两渠道均按（输入+输出）时长计费，参考视频比输出长的部分全是白付的输入时长。</div>
        </div>`;
    document.body.appendChild(overlay);

    const q = (sel) => overlay.querySelector(sel);
    const video = q(".ariadne-trim-video");
    const timeline = q(".ariadne-trim2-timeline");
    const band = q(".ariadne-trim2-band");
    const tick = q(".ariadne-trim2-tick");
    const playhead = q(".ariadne-trim2-playhead");
    const skimLine = q(".ariadne-trim2-skim");
    const rangeBadge = q(".ariadne-trim2-rangebadge");
    const timeText = q(".ariadne-trim2-timetext");
    const msgEl = q(".ariadne-trim2-msg");
    const errEl = q(".ariadne-trim2-error");
    const subEl = q(".ariadne-trim2-sub");
    const applyBtn = q(".ariadne-trim2-apply");
    const playBtn = q(".ariadne-trim2-play");
    const followBtn = q(".ariadne-trim2-follow");

    const msg = (text) => { msgEl.textContent = text || ""; };
    const fail = (text) => { errEl.textContent = text || ""; };

    function computeRange() {
        if (mode === "manual") return { start: manual.start, end: manual.end };
        if (mode === "align") {
            if (!sourceSeconds) return { start: 0, end: sourceSeconds };
            const keep = outputDuration > 0 ? Math.min(outputDuration, sourceSeconds) : sourceSeconds;
            return { start: 0, end: Math.max(keep, Math.min(1, sourceSeconds)) };
        }
        // shots：分镜均摊（水位法，每段保留开头，凑足输出时长）
        if (!cuts?.length || !outputDuration) return { start: 0, end: sourceSeconds };
        const bounds = [0, ...cuts.filter((c) => c > 0 && c < sourceSeconds), sourceSeconds];
        const segments = bounds.slice(0, -1).map((b, i) => [b, bounds[i + 1]]);
        const ranges = [];
        let remaining = outputDuration;
        for (const [s, e] of segments) {
            if (remaining <= 0.01) break;
            const take = Math.min(e - s, remaining);
            ranges.push([s, s + take]);
            remaining -= take;
        }
        if (!ranges.length) return { start: 0, end: sourceSeconds };
        return { start: ranges[0][0], end: ranges[ranges.length - 1][1], multi: ranges };
    }

    function renderRange() {
        range = computeRange();
        const pctS = sourceSeconds ? (range.start / sourceSeconds) * 100 : 0;
        const pctE = sourceSeconds ? (range.end / sourceSeconds) * 100 : 100;
        band.style.left = `${pctS}%`;
        band.style.width = `${pctE - pctS}%`;
        rangeBadge.textContent = `${TRIM_FMT(range.start)}–${TRIM_FMT(range.end)}s`;
        const keep = range.end - range.start;
        const saving = sourceSeconds > keep ? sourceSeconds - keep : 0;
        subEl.textContent = sourceSeconds
            ? `${tile.name}（源 ${sourceSeconds.toFixed(1)}s · 保留 ${keep.toFixed(1)}s${saving > 0.05 ? ` · 省 ${saving.toFixed(1)}s 输入计费` : ""}）`
            : tile.name;
        applyBtn.disabled = !sourceSeconds || !!busyLabel;
        applyBtn.textContent = busyLabel || "应用截断";
        timeText.textContent = `${TRIM_FMT(range.start)}s – ${TRIM_FMT(range.end)}s`;
        timeline.classList.toggle("manual", mode === "manual");
        tick.innerHTML = "";
        for (const cut of cuts || []) {
            if (cut <= 0 || cut >= sourceSeconds) continue;
            const line = document.createElement("div");
            line.style.left = `${(cut / sourceSeconds) * 100}%`;
            line.title = `切点 ${cut.toFixed(1)}s`;
            tick.appendChild(line);
        }
    }

    function refreshModeButtons() {
        for (const btn of overlay.querySelectorAll("[data-mode]")) {
            btn.classList.toggle("active", btn.dataset.mode === mode);
        }
    }

    // 播放循环：预览循环选中段 + 播放头跟随（单 rAF）
    function loop() {
        if (!overlay.isConnected) return;
        if (video && sourceSeconds) {
            const t = video.currentTime;
            if (playing && (t >= range.end - 0.05 || t < range.start - 0.1)) {
                void seekVideoTo(video, range.start);
            }
            playhead.style.left = `${Math.min(100, Math.max(0, (t / sourceSeconds) * 100))}%`;
        }
        requestAnimationFrame(loop);
    }

    playBtn.addEventListener("click", () => {
        playing = !playing;
        playBtn.textContent = playing ? "暂停" : "播放";
        if (playing) void video.play().catch(() => {});
        else video.pause();
    });
    followBtn.addEventListener("click", () => {
        skimFollow = !skimFollow;
        followBtn.textContent = `⌖ 跟随 ${skimFollow ? "开" : "关"}`;
        followBtn.classList.toggle("active", skimFollow);
    });
    video.addEventListener("loadedmetadata", () => {
        if (video.duration && isFinite(video.duration) && !sourceSeconds) {
            sourceSeconds = video.duration;
            manual.end = Math.min(Math.max(outputDuration || 4, 1), sourceSeconds);
        }
        renderRange();
    });
    void video.play().catch(() => {});

    // 模式切换
    for (const btn of overlay.querySelectorAll("[data-mode]")) {
        btn.addEventListener("click", async () => {
            mode = btn.dataset.mode;
            refreshModeButtons();
            fail("");
            if (mode === "shots" && !cutsReady) {
                msg("检测切点中…");
                try {
                    const response = await fetch("/ariadne/trim", {
                        method: "POST", headers: { "content-type": "application/json" },
                        body: JSON.stringify({ name: tile.name, subfolder: tile.subfolder || "", detect: true }),
                    });
                    const data = await response.json();
                    if (data.error) throw new Error(data.error);
                    cuts = (data.cutPoints || []).filter((c) => c > 0 && c < (sourceSeconds || Infinity));
                    cutsReady = true;
                    msg(cuts.length ? `检测到 ${cuts.length} 个切点` : "未检测到切点，按整段处理");
                } catch (error) {
                    msg(`切点检测失败：${error?.message || error}`);
                }
            }
            renderRange();
        });
    }

    // 时间轴交互：点击 seek、悬停掠动跟随、手动拖卡尺/整段
    let drag = null;
    const timeFromEvent = (event) => {
        const rect = timeline.getBoundingClientRect();
        const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
        return ratio * sourceSeconds;
    };
    timeline.addEventListener("pointermove", (event) => {
        if (drag && mode === "manual") {
            const t = timeFromEvent(event);
            if (drag.kind === "start") manual.start = Math.min(Math.max(t, 0), manual.end - 0.5);
            else if (drag.kind === "end") manual.end = Math.max(Math.min(t, sourceSeconds), manual.start + 0.5);
            else {
                const len = manual.end - manual.start;
                manual.start = Math.min(Math.max(t - drag.grabOffset, 0), sourceSeconds - len);
                manual.end = manual.start + len;
            }
            renderRange();
            return;
        }
        const rect = timeline.getBoundingClientRect();
        const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
        skimLine.style.display = "block";
        skimLine.style.left = `${ratio * 100}%`;
        if (skimFollow && video && sourceSeconds) {
            const t = ratio * sourceSeconds;
            if (playing) {
                playing = false;
                video.pause();
                playBtn.textContent = "播放";
            }
            if (Math.abs(video.currentTime - t) > 0.04) void seekVideoTo(video, t);
        }
    });
    timeline.addEventListener("pointerleave", () => { skimLine.style.display = "none"; });
    timeline.addEventListener("pointerdown", (event) => {
        const handle = event.target.closest?.(".ariadne-trim2-handle");
        if (handle && mode === "manual") {
            drag = { kind: handle.classList.contains("ariadne-trim2-start") ? "start" : "end" };
            timeline.setPointerCapture?.(event.pointerId);
            event.preventDefault();
            return;
        }
        if (mode === "manual") {
            const t = timeFromEvent(event);
            const len = manual.end - manual.start;
            if (t >= manual.start && t <= manual.end) {
                drag = { kind: "band", grabOffset: t - manual.start };
                timeline.setPointerCapture?.(event.pointerId);
                event.preventDefault();
                return;
            }
        }
        if (video && sourceSeconds) void seekVideoTo(video, timeFromEvent(event));
    });
    timeline.addEventListener("pointerup", () => { drag = null; });
    timeline.addEventListener("pointercancel", () => { drag = null; });
    for (const handle of overlay.querySelectorAll(".ariadne-trim2-handle")) {
        handle.addEventListener("wheel", (event) => {
            if (mode !== "manual") return;
            event.preventDefault();
            const delta = event.deltaY > 0 ? 0.1 : -0.1;
            if (handle.classList.contains("ariadne-trim2-start")) {
                manual.start = Math.min(Math.max(manual.start + delta, 0), manual.end - 0.5);
            } else {
                manual.end = Math.max(Math.min(manual.end + delta, sourceSeconds), manual.start + 0.5);
            }
            renderRange();
        }, { passive: false });
    }

    // 应用截断：/ariadne/trim 产出上传瓦片；连线素材裁完也落到瓦片
    applyBtn.addEventListener("click", async () => {
        if (!sourceSeconds || busyLabel) return;
        busyLabel = "截断中…";
        applyBtn.disabled = true;
        applyBtn.textContent = busyLabel;
        fail("");
        const ranges = mode === "manual"
            ? [[manual.start, manual.end]]
            : mode === "shots"
                ? (range.multi || [[range.start, range.end]])
                : [[range.start, range.end]];
        try {
            const response = await fetch("/ariadne/trim", {
                method: "POST", headers: { "content-type": "application/json" },
                body: JSON.stringify({ name: tile.name, subfolder: tile.subfolder || "", ranges, role: tile.role || "motion" }),
            });
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            const tiles = tilesOf(node).filter((item) => tileKey(item) !== tileKey(tile));
            tiles.push({
                kind: "video", name: data.name, subfolder: data.subfolder, role: data.role || tile.role || "motion",
                seconds: data.seconds, width: data.width, height: data.height, pixelsOk: data.pixelsOk, trimmed: true,
            });
            commitTiles(node, tiles);
            overlay.remove();
            onDone?.();
            return;
        } catch (error) {
            fail(`截断失败：${error?.message || error}`);
        }
        busyLabel = "";
        applyBtn.disabled = false;
        applyBtn.textContent = "应用截断";
    });

    q(".ariadne-trim2-back").addEventListener("click", () => overlay.remove());
    const escClose = (event) => {
        if (event.key === "Escape") {
            overlay.remove();
            document.removeEventListener("keydown", escClose);
        }
    };
    document.addEventListener("keydown", escClose);
    refreshModeButtons();
    renderRange();
    requestAnimationFrame(loop);
}
