// Ariadne 前端扩展：中文标签 + 素材瓦片 + @胶囊提示词 + 裁剪浮层 + 费用预估 + 侧栏工作台。
// 避坑清单（D:\GitHub\ComfyUI\本地开发手册\避坑经验.md）落地：
// - widgets_values 双序列化（onSerialize 同时写 named 字段）
// - nodeCreated 加 app.configuringGraph 守卫 + loadedGraphNode 补挂 + requestAnimationFrame
// - DOM widget 用 computeLayoutSize 控高；宽度在 onResize 手动同步
// - 替换原生 widget 保持原位置并接住原 callback；升级动作幂等守卫
// - 每块独立 try/catch，任何前端失败都不影响节点本身

import { app } from "../../scripts/app.js";

const SEEDANCE_TYPE = "AriadneSeedance25Video";
const NODE_TYPES = new Set([SEEDANCE_TYPE, "AriadneVeo31Video", "AriadneKlingVideo", "AriadneKieImage"]);

const KIND_LABEL = { image: "图片", video: "视频", audio: "音频" };
const ROLE_OPTIONS = [
    ["character", "人物"], ["wardrobe", "服装"], ["scene", "场景"], ["motion", "动作"],
    ["audio", "音频"], ["first-frame", "首帧"], ["last-frame", "尾帧"], ["annotation", "标注帧"],
];
const ROLE_LABEL = Object.fromEntries(ROLE_OPTIONS);

function nodeType(node) {
    return node.comfyClass || node.constructor?.comfyClass || node.type;
}

// ---- CSS 注入（WEB_DIRECTORY 只自动加载 .js，其余动态注入） ----
function injectCss() {
    if (document.getElementById("ariadne-css")) return;
    const link = document.createElement("link");
    link.id = "ariadne-css";
    link.rel = "stylesheet";
    link.href = new URL("../ariadne.css", import.meta.url).href;
    document.head.appendChild(link);
}

// ---- 中文标签 ----
function applyChineseLabels(node) {
    const type = nodeType(node);
    const widgetLabels = type === SEEDANCE_TYPE ? {
        prompt: "提示词", task_type: "任务模式", duration: "时长（秒）", resolution: "分辨率",
        aspect_ratio: "画幅", generate_audio: "生成音频", output_format: "输出格式",
        channel: "生成渠道", download_folder: "保存文件夹", ariadne_assets: "素材",
        return_last_frame: "返回尾帧", poll_interval_seconds: "轮询间隔（秒）", timeout_seconds: "超时（秒）",
    } : type === "AriadneVeo31Video" ? {
        prompt: "提示词", task_type: "任务模式", model: "模型档位", duration: "时长（秒）",
        resolution: "分辨率", aspect_ratio: "画幅", watermark: "水印文字（留空不加）",
        download_folder: "保存文件夹", extend_task_id: "来源任务ID（延长）", extend_seeds: "延长种子",
        poll_interval_seconds: "轮询间隔（秒）", timeout_seconds: "超时（秒）",
    } : type === "AriadneKlingVideo" ? {
        prompt: "提示词", task_type: "任务模式", duration: "时长（秒）", aspect_ratio: "画幅",
        sound: "生成音频", quality_mode: "品质（std/pro）", download_folder: "保存文件夹",
        kling_elements: "角色元素（JSON）", kling_shots: "多镜头分镜（JSON）",
        poll_interval_seconds: "轮询间隔（秒）", timeout_seconds: "超时（秒）",
    } : {
        platform: "服务商", prompt: "提示词", aspect_ratio: "画幅", resolution: "分辨率",
        download_folder: "保存文件夹",
    };
    const inputLabels = {
        first_frame: "首帧", last_frame: "尾帧", character_images: "人物参考图",
        wardrobe_images: "服装参考图", scene_images: "场景参考图", motion_video: "动作参考视频",
        reference_audio: "参考音频", reference_images: "参考图",
    };
    const set = () => {
        const map = {};
        for (const w of node.widgets || []) map[w.name] = w;
        for (const [key, value] of Object.entries(widgetLabels)) if (map[key]) map[key].label = value;
        for (const input of node.inputs || []) if (inputLabels[input.name]) input.label = inputLabels[input.name];
        node.setDirtyCanvas(true, true);
    };
    set();
    setTimeout(set, 0);
    setTimeout(set, 250);
}

// ---- 双序列化（widgets_values + widgets_values_named） ----
function installCompactSerialization(node) {
    if (node.__ariadneCompact) return;
    node.__ariadneCompact = true;
    const original = node.onSerialize;
    node.onSerialize = function (info) {
        original?.call(this, info);
        const serialWidgets = (this.widgets || []).filter((w) => w.serialize !== false);
        info.widgets_values = serialWidgets.map((w) => w.value ?? null);
        info.widgets_values_named = Object.fromEntries(serialWidgets.map((w) => [w.name, w.value ?? null]));
    };
}

// ---- 素材瓦片（Seedance 节点专属） ----
function tileLabelOf(tiles, tile) {
    const counters = { image: 0, video: 0, audio: 0 };
    let label = "";
    for (const item of tiles) {
        counters[item.kind] += 1;
        if (item === tile) label = `@${KIND_LABEL[item.kind]}${counters[item.kind]}`;
    }
    return label;
}

function refreshTilesWidget(node) {
    const widget = node.widgets?.find((w) => w.name === "ariadne_assets");
    if (!widget?.element) return;
    const tiles = JSON.parse(widget.value || "[]");
    const grid = widget.element.querySelector(".ariadne-tiles");
    const summary = widget.element.querySelector(".ariadne-tiles-summary");
    if (!grid) return;
    grid.innerHTML = "";
    for (const tile of tiles) {
        const chip = document.createElement("div");
        chip.className = "ariadne-tile" + (tile.trimmed ? " ariadne-tile-trimmed" : "");
        const mark = document.createElement("span");
        mark.className = "ariadne-tile-mark";
        mark.textContent = tile.trimmed ? `✂ ${Math.round(tile.seconds || 0)}s` : KIND_LABEL[tile.kind];
        const name = document.createElement("span");
        name.className = "ariadne-tile-name";
        name.textContent = tileLabelOf(tiles, tile) || tile.name;
        name.title = `${tile.name}（${ROLE_LABEL[tile.role] || tile.role}${tile.trimmed ? `，已裁 ${Math.round(tile.seconds || 0)}s` : ""}）`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "ariadne-tile-remove";
        remove.textContent = "×";
        remove.title = "移除素材";
        remove.addEventListener("click", () => {
            const current = JSON.parse(widget.value || "[]").filter((item) => item !== tile);
            widget.value = JSON.stringify(current);
            refreshTilesWidget(node);
            refreshLabels(node);
            node.setDirtyCanvas(true, true);
        });
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "ariadne-tile-role";
        edit.textContent = ROLE_LABEL[tile.role] || tile.role;
        edit.title = "切换素材职责";
        edit.addEventListener("click", () => {
            const index = ROLE_OPTIONS.findIndex(([value]) => value === tile.role);
            tile.role = ROLE_OPTIONS[(index + 1) % ROLE_OPTIONS.length][0];
            widget.value = JSON.stringify(tiles);
            refreshTilesWidget(node);
            refreshLabels(node);
        });
        const trimBtn = document.createElement("button");
        trimBtn.type = "button";
        trimBtn.className = "ariadne-tile-trim";
        trimBtn.textContent = "✂";
        trimBtn.title = "节点内裁剪（省钱：参考视频比输出长的部分全是白付的输入时长）";
        trimBtn.addEventListener("click", () => openTrimDialog(node, widget, tile));
        chip.append(mark, name, edit, trimBtn, remove);
        grid.appendChild(chip);
    }
    const videoTiles = tiles.filter((tile) => tile.kind === "video");
    if (summary) {
        summary.textContent = tiles.length
            ? `${tiles.length} 个素材${videoTiles.some((tile) => tile.trimmed) ? " · 已裁" + videoTiles.filter((tile) => tile.trimmed).length + "段" : ""}`
            : "拖入或点击＋添加参考素材";
    }
    syncTilesWidth(node);
}

function syncTilesWidth(node) {
    const widget = node.widgets?.find((w) => w.name === "ariadne_assets");
    if (!widget?.element) return;
    widget.element.style.width = `${Math.max(240, Number(node.size?.[0] || 0) - 22)}px`;
}

function makeTilesWidget(node) {
    const old = node.widgets?.find((w) => w.name === "ariadne_assets");
    if (!old || old.type === "ariadne_assets") return;
    const wrap = document.createElement("div");
    wrap.className = "ariadne-tiles-wrap";
    const toolbar = document.createElement("div");
    toolbar.className = "ariadne-tiles-toolbar";
    const add = document.createElement("button");
    add.type = "button";
    add.className = "ariadne-btn";
    add.textContent = "＋ 素材";
    add.title = "添加图片/视频/音频参考素材（存入 ComfyUI input/ariadne/）";
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.multiple = true;
    fileInput.accept = "image/*,video/*,audio/*";
    fileInput.style.display = "none";
    fileInput.addEventListener("change", async () => {
        for (const file of fileInput.files || []) {
            await uploadTile(node, old, file);
        }
        fileInput.value = "";
    });
    add.addEventListener("click", () => fileInput.click());
    const summary = document.createElement("span");
    summary.className = "ariadne-tiles-summary";
    toolbar.append(add, fileInput, summary);
    const grid = document.createElement("div");
    grid.className = "ariadne-tiles";
    wrap.append(toolbar, grid);

    const widget = node.addDOMWidget("ariadne_assets", "ariadne_assets", wrap, {
        hideOnZoom: true, serialize: true, getValue: () => old.value || "[]",
        setValue: (value) => { old.value = String(value || "[]"); },
    });
    widget.serialize = true;
    widget.serializeValue = () => old.value || "[]";
    widget.computeLayoutSize = () => ({ minHeight: 64, maxHeight: 1200 });
    widget.element = wrap;
    // 保留原位置：替换原生 STRING widget。
    const index = node.widgets.indexOf(old);
    old.onRemove?.();
    node.widgets.splice(index, 1);
    const appended = node.widgets.indexOf(widget);
    if (appended >= 0) node.widgets.splice(appended, 1);
    node.widgets.splice(index, 0, widget);
    const originalResize = node.onResize;
    node.onResize = function (...args) {
        syncTilesWidth(node);
        return originalResize?.apply(this, args);
    };
    refreshTilesWidget(node);
}

async function uploadTile(node, widget, file) {
    const kind = file.type.startsWith("video/") ? "video" : file.type.startsWith("audio/") ? "audio" : "image";
    const defaultRole = kind === "video" ? "motion" : kind === "audio" ? "audio" : "character";
    addStatus(node, `上传 ${file.name} …`);
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`/ariadne/upload?kind=${kind}&role=${defaultRole}`, { method: "POST", body: form });
    const data = await response.json();
    if (data.error) { addStatus(node, `上传失败：${data.error}`); return; }
    const tiles = JSON.parse(widget.value || "[]");
    tiles.push({
        kind: data.kind, name: data.name, subfolder: data.subfolder, role: data.role || defaultRole,
        seconds: data.seconds || 0, width: data.width || 0, height: data.height || 0,
        pixelsOk: data.pixelsOk, probeError: data.probeError,
    });
    widget.value = JSON.stringify(tiles);
    refreshTilesWidget(node);
    refreshLabels(node);
    if (kind === "video" && data.pixelsOk === false) {
        addStatus(node, `${file.name} 像素 ${data.width}×${data.height} 低于官方 407696 下限，提交会被方舟拒绝（请放大后重导）`);
    } else {
        addStatus(node, `${file.name} 已添加`);
    }
}

function addStatus(node, text) {
    const widget = node.widgets?.find((w) => w.name === "ariadne_assets");
    const summary = widget?.element?.querySelector(".ariadne-tiles-summary");
    if (summary) summary.textContent = text;
}

// ---- 胶囊提示词编辑器：@ 唤出素材选单，@标签原子化 ----
function makeCapsulePrompt(node) {
    const old = node.widgets?.find((w) => w.name === "prompt");
    if (!old || old.type === "ariadne_prompt") return;
    const editor = document.createElement("div");
    editor.className = "ariadne-prompt";
    editor.contentEditable = "true";
    editor.spellcheck = false;
    editor.dataset.placeholder = "描述画面；@ 唤出素材选单，或把下方瓦片拖进来";

    const widget = node.addDOMWidget("prompt", "ariadne_prompt", editor, {
        hideOnZoom: true, serialize: true,
        getValue: () => editor.innerText.replace(/\u00a0/g, " "),
        setValue: (value) => { renderPrompt(editor, String(value || "")); },
    });
    widget.serialize = true;
    widget.serializeValue = () => editor.innerText.replace(/\u00a0/g, " ");
    widget.computeLayoutSize = () => ({ minHeight: 96, maxHeight: 4000 });
    const originalCallback = old.callback;
    widget.callback = originalCallback;
    editor.addEventListener("input", () => {
        widget.callback?.(widget.getValue());
        node.setDirtyCanvas(true, true);
    });
    editor.addEventListener("keydown", (event) => {
        if (event.key === "@") setTimeout(() => openAssetMenu(node, editor), 0);
        event.stopPropagation();
    });
    editor.addEventListener("blur", () => {
        // 空读保护（画布版 0.1.1 提示词丢失事故教训）：编辑器空而元数据有内容时不回写空串。
        const stored = old.value || "";
        const current = widget.getValue();
        if (!current.trim() && stored.trim()) renderPrompt(editor, stored);
    });

    const index = node.widgets.indexOf(old);
    old.onRemove?.();
    node.widgets.splice(index, 1);
    const appended = node.widgets.indexOf(widget);
    if (appended >= 0) node.widgets.splice(appended, 1);
    node.widgets.splice(index, 0, widget);
    renderPrompt(editor, String(old.value || ""));
}

function renderPrompt(editor, text) {
    // 已知标签优先（长标签在前，图片1 不抢 图片10 —— 画布版 prompt-tokens.ts 教训）。
    const tiles = currentTiles();
    const labels = tiles.map((tile) => tile.label).filter(Boolean).sort((a, b) => b.length - a.length);
    const known = labels.map((label) => label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
    const pattern = new RegExp(`(@(?:${known ? known + "|" : ""}[^\\s@，。！？；：、]+))`, "g");
    editor.innerHTML = "";
    for (const part of String(text || "").split(pattern)) {
        if (!part) continue;
        if (part.startsWith("@")) {
            const chip = document.createElement("span");
            chip.className = "ariadne-chip";
            chip.contentEditable = "false";
            chip.textContent = part;
            chip.style.background = part.startsWith("@图") ? "#5b3fa8" : part.startsWith("@视") ? "#1f5c8b" : "#1f7a4d";
            editor.appendChild(chip);
        } else {
            editor.appendChild(document.createTextNode(part));
        }
    }
}

let currentTilesRef = { tiles: [] };
function currentTiles() {
    return currentTilesRef.tiles;
}

function refreshLabels(node) {
    const widget = node.widgets?.find((w) => w.name === "ariadne_assets");
    if (!widget) return;
    const tiles = JSON.parse(widget.value || "[]");
    const counters = { image: 0, video: 0, audio: 0 };
    for (const tile of tiles) {
        counters[tile.kind] += 1;
        tile.label = `@${KIND_LABEL[tile.kind]}${counters[tile.kind]}`;
    }
    widget.value = JSON.stringify(tiles);
    currentTilesRef.tiles = tiles;
}

function openAssetMenu(node, editor) {
    const tiles = currentTiles();
    const existing = editor.innerText;
    const menu = document.createElement("div");
    menu.className = "ariadne-menu";
    if (!tiles.length) {
        menu.textContent = "还没有素材：先在「素材」区添加图片/视频/音频";
    }
    for (const tile of tiles) {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "ariadne-menu-item";
        item.textContent = `${tile.label}（${ROLE_LABEL[tile.role] || tile.role} · ${tile.name}）`;
        item.addEventListener("click", () => {
            insertAtCursor(editor, tile.label);
            menu.remove();
        });
        menu.appendChild(item);
    }
    positionMenu(editor, menu);
    const dismiss = (event) => {
        if (!menu.contains(event.target)) {
            menu.remove();
            document.removeEventListener("mousedown", dismiss);
        }
    };
    setTimeout(() => document.addEventListener("mousedown", dismiss), 0);
}

function insertAtCursor(editor, text) {
    editor.focus();
    const selection = window.getSelection();
    if (!selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    range.deleteContents();
    range.insertNode(document.createTextNode(text));
    range.collapse(false);
    editor.dispatchEvent(new Event("input", { bubbles: true }));
}

function positionMenu(anchor, menu) {
    document.body.appendChild(menu);
    const rect = anchor.getBoundingClientRect();
    menu.style.left = `${Math.min(rect.left, window.innerWidth - 320)}px`;
    menu.style.top = `${Math.min(rect.bottom + 4, window.innerHeight - 200)}px`;
}

// ---- 节点内裁剪浮层（三模式：对齐输出 / 分镜均摊 / 手动区间） ----
function openTrimDialog(node, widget, tile) {
    if (tile.kind !== "video") { addStatus(node, "裁剪只对视频素材可用"); return; }
    const overlay = document.createElement("div");
    overlay.className = "ariadne-overlay";
    const url = `/view?filename=${encodeURIComponent(tile.name)}&subfolder=${encodeURIComponent(tile.subfolder)}&type=input`;
    const seconds = Number(tile.seconds || 0);
    overlay.innerHTML = `
        <div class="ariadne-dialog">
            <div class="ariadne-dialog-title">✂ 裁剪 · ${tile.name}（源 ${seconds.toFixed(1)}s）</div>
            <video src="${url}" class="ariadne-trim-video" muted loop autoplay></video>
            <div class="ariadne-trim-timeline"><div class="ariadne-trim-keep"></div>
                <div class="ariadne-trim-handle ariadne-trim-start"></div>
                <div class="ariadne-trim-handle ariadne-trim-end"></div></div>
            <div class="ariadne-trim-row">
                <select class="ariadne-trim-mode">
                    <option value="manual">手动区间</option>
                    <option value="align">对齐输出（保留开头 = 输出时长）</option>
                    <option value="story">分镜均摊（自动切点，每镜保留开头）</option>
                </select>
                <span class="ariadne-trim-range">0.0s – ${seconds.toFixed(1)}s</span>
                <button type="button" class="ariadne-btn ariadne-trim-apply">应用裁剪</button>
                <button type="button" class="ariadne-btn ariadne-trim-cancel">取消</button>
            </div>
            <div class="ariadne-trim-hint">计费提示：两渠道均按（输入+输出）时长计费，参考视频比输出长的部分全是白付的输入时长。</div>
        </div>`;
    document.body.appendChild(overlay);
    const dialog = overlay.querySelector(".ariadne-dialog");
    const timeline = overlay.querySelector(".ariadne-trim-timeline");
    const keep = overlay.querySelector(".ariadne-trim-keep");
    const startHandle = overlay.querySelector(".ariadne-trim-handle.ariadne-trim-start");
    const endHandle = overlay.querySelector(".ariadne-trim-handle.ariadne-trim-end");
    const rangeLabel = overlay.querySelector(".ariadne-trim-range");
    let start = 0;
    let end = seconds;
    const render = () => {
        const left = seconds ? (start / seconds) * 100 : 0;
        const width = seconds ? ((end - start) / seconds) * 100 : 100;
        keep.style.left = `${left}%`;
        keep.style.width = `${width}%`;
        startHandle.style.left = `${left}%`;
        endHandle.style.left = `${left + width}%`;
        rangeLabel.textContent = `${start.toFixed(1)}s – ${end.toFixed(1)}s（保留 ${(end - start).toFixed(1)}s）`;
    };
    const drag = (isStart) => (event) => {
        event.preventDefault();
        const move = (moveEvent) => {
            const rect = timeline.getBoundingClientRect();
            const value = Math.max(0, Math.min(seconds, ((moveEvent.clientX - rect.left) / rect.width) * seconds));
            if (isStart) start = Math.min(value, end - 0.5);
            else end = Math.max(value, start + 0.5);
            render();
        };
        const up = () => {
            document.removeEventListener("mousemove", move);
            document.removeEventListener("mouseup", up);
        };
        document.addEventListener("mousemove", move);
        document.addEventListener("mouseup", up);
    };
    startHandle.addEventListener("mousedown", drag(true));
    endHandle.addEventListener("mousedown", drag(false));
    render();

    overlay.querySelector(".ariadne-trim-cancel").addEventListener("click", () => overlay.remove());
    const modeSelect = overlay.querySelector(".ariadne-trim-mode");
    modeSelect.addEventListener("change", async () => {
        const mode = modeSelect.value;
        if (mode === "align") { start = 0; end = Math.min(seconds, Number(node.widgets.find((w) => w.name === "duration")?.value || 10)); render(); return; }
        if (mode === "story") {
            rangeLabel.textContent = "检测切点中…";
            const response = await fetch("/ariadne/trim", {
                method: "POST", headers: { "content-type": "application/json" },
                body: JSON.stringify({ name: tile.name, subfolder: tile.subfolder, detect: true }),
            });
            const data = await response.json();
            const points = (data.cutPoints || []).filter((point) => point < seconds);
            if (!points.length) { render(); return; }
            // 水位法：总保留摊到输出时长，每镜保留开头一段。
            const durationWidget = node.widgets.find((w) => w.name === "duration");
            const target = Math.min(seconds, Number(durationWidget?.value || 10));
            const bounds = [0, ...points, seconds];
            const segments = bounds.slice(0, -1).map((bound, index) => [bound, bounds[index + 1]]);
            const keepRanges = [];
            let remaining = target;
            for (const [segStart, segEnd] of segments) {
                const length = segEnd - segStart;
                const take = Math.min(length, Math.max(0.5, remaining / Math.max(1, segments.length - keepRanges.length)));
                if (remaining <= 0) break;
                keepRanges.push([segStart, segStart + Math.min(take, length)]);
                remaining -= take;
            }
            start = keepRanges[0]?.[0] ?? 0;
            end = keepRanges.reduce((sum, [, segEnd]) => sum + segEnd - 0, 0) > 0 ? Math.min(seconds, target) : end;
            rangeLabel.textContent = `分镜均摊：检测到 ${points.length} 个切点，保留段 ${keepRanges.length} 个（应用后按区间拼接）`;
            timeline.__keepRanges = keepRanges;
            render();
        }
    });
    overlay.querySelector(".ariadne-trim-apply").addEventListener("click", async () => {
        const ranges = timeline.__keepRanges || [[start, end]];
        rangeLabel.textContent = "裁剪中（ffmpeg 转码，秒级）…";
        const response = await fetch("/ariadne/trim", {
            method: "POST", headers: { "content-type": "application/json" },
            body: JSON.stringify({ name: tile.name, subfolder: tile.subfolder, ranges, role: tile.role }),
        });
        const data = await response.json();
        if (data.error) { rangeLabel.textContent = `裁剪失败：${data.error}`; return; }
        const tiles = JSON.parse(widget.value || "[]").filter((item) => item !== tile);
        tiles.push({
            kind: "video", name: data.name, subfolder: data.subfolder, role: data.role || tile.role,
            seconds: data.seconds, width: data.width, height: data.height, pixelsOk: data.pixelsOk, trimmed: true,
        });
        widget.value = JSON.stringify(tiles);
        refreshTilesWidget(node);
        refreshLabels(node);
        overlay.remove();
        addStatus(node, `已裁 1 段：${(ranges.reduce((sum, [s, e]) => sum + (e - s), 0)).toFixed(1)}s → ${data.seconds}s`);
    });
}

// ---- 费用预估行（Seedance 节点） ----
function makeEstimateWidget(node) {
    if (nodeType(node) !== SEEDANCE_TYPE) return null;
    if (node.widgets?.some((w) => w.type === "ariadne_estimate")) return null;
    const note = document.createElement("div");
    note.className = "ariadne-estimate";
    note.textContent = "费用预估: …";
    const widget = node.addDOMWidget("费用预估", "ariadne_estimate", note, { hideOnZoom: true, serialize: false });
    widget.computeSize = () => [0, 22];
    widget.computeLayoutSize = undefined;
    widget.__ariadneRefresh = () => refreshEstimate(node, note);
    for (const name of ["duration", "resolution", "channel", "task_type"]) {
        const target = node.widgets?.find((w) => w.name === name);
        if (!target) continue;
        const original = target.callback;
        target.callback = function (...args) {
            const result = original?.apply(this, args);
            widget.__ariadneRefresh?.();
            return result;
        };
    }
    const originalConnections = node.onConnectionsChange;
    node.onConnectionsChange = function (...args) {
        const result = originalConnections?.apply(this, args);
        widget.__ariadneRefresh?.();
        return result;
    };
    widget.__ariadneRefresh();
    return widget;
}

async function refreshEstimate(node, note) {
    const value = (name) => node.widgets?.find((w) => w.name === name)?.value;
    const channel = String(value("channel") || "ark").startsWith("kie") ? "kie" : "ark";
    const includesVideo = !!(node.getInputNode("motion_video")) || currentTiles().some((tile) => tile.kind === "video");
    let inputSeconds = currentTiles().filter((tile) => tile.kind === "video").reduce((sum, tile) => sum + Number(tile.seconds || 0), 0);
    try {
        const response = await fetch("/ariadne/estimate", {
            method: "POST", headers: { "content-type": "application/json" },
            body: JSON.stringify({
                channel, resolution: value("resolution"), duration: Number(value("duration") ?? 0),
                includesVideoInput: includesVideo, inputVideoSeconds: inputSeconds,
            }),
        });
        const data = await response.json();
        const estimate = data.estimate;
        if (!estimate) { note.textContent = "费用预估: --（该档位/自适应时长无法估算，以账单为准）"; return; }
        note.textContent = estimate.unit === "credits"
            ? `费用预估: ≈${estimate.credits} credits ≈ ¥${estimate.cny}（Kie，输入时长未计全时偏低；以账单为准）`
            : `费用预估: ≈¥${estimate.cny}（方舟刊例；以账单为准）`;
    } catch {
        note.textContent = "费用预估: 不可用";
    }
}

// ---- 升级入口 ----
function upgradeNode(node) {
    const type = nodeType(node);
    if (!NODE_TYPES.has(type)) return;
    if (node.__ariadneUpgraded) return;
    node.__ariadneUpgraded = true;
    const safe = (label, fn) => { try { fn(); } catch (error) { console.error(`Ariadne ${label}`, error); } };
    safe("标签", () => applyChineseLabels(node));
    safe("序列化", () => installCompactSerialization(node));
    if (type === SEEDANCE_TYPE) {
        safe("标签刷新", () => refreshLabels(node));
        safe("瓦片", () => makeTilesWidget(node));
        safe("胶囊提示词", () => makeCapsulePrompt(node));
        safe("估价", () => makeEstimateWidget(node));
    }
    requestAnimationFrame(() => {
        try { node.setSize(node.computeSize()); } catch { /* 新前端布局自适应 */ }
        node.setDirtyCanvas(true, true);
    });
}

// ---- 侧栏工作台：配置 + 用法 ----
function registerSidebarTab() {
    if (!app.extensionManager?.registerSidebarTab) return;
    app.extensionManager.registerSidebarTab({
        id: "ariadne-workbench",
        icon: "pi pi-video",
        title: "Ariadne 工作台",
        tooltip: "Ariadne 密钥/对象存储/提示词优化配置",
        type: "custom",
        render: (el) => {
            el.innerHTML = `
                <div class="ariadne-workbench">
                    <h3>密钥与对象存储</h3>
                    <label>火山方舟 Key（Seedance 方舟渠道）<input name="ark_api_key" type="password" placeholder="留空不修改"></label>
                    <label>Kie Key（Veo/可灵/图生图/Seedance Kie 渠道）<input name="kie_api_key" type="password" placeholder="留空不修改"></label>
                    <h4>对象存储 TOS（方舟参考视频必需）</h4>
                    <label>AccessKey<input name="tos_accessKey" type="password" placeholder="留空不修改"></label>
                    <label>SecretKey<input name="tos_secretKey" type="password" placeholder="留空不修改"></label>
                    <label>桶名<input name="tos_bucket"></label>
                    <label>Region<input name="tos_region"></label>
                    <label>Endpoint<input name="tos_endpoint"></label>
                    <h4>提示词优化器（OpenAI 兼容）</h4>
                    <label>站点<input name="opt_base_url" placeholder="https://api.deepseek.com"></label>
                    <label>模型<input name="opt_model" placeholder="先拉取列表选"></label>
                    <label>Key<input name="opt_api_key" type="password" placeholder="留空不修改"></label>
                    <div class="ariadne-workbench-actions">
                        <button type="button" class="ariadne-btn" id="ariadne-save">保存配置</button>
                        <button type="button" class="ariadne-btn" id="ariadne-tos-test">TOS 试传验证</button>
                    </div>
                    <pre class="ariadne-workbench-log" id="ariadne-log"></pre>
                    <h3>用法速记</h3>
                    <p>① Seedance 节点「＋素材」上传参考图/视频/音频 → ② 提示词 @ 唤出素材编号 → ③ 视频瓦片 ✂ 裁剪省钱 → ④ Queue 出片，成片自动落 output/ariadne/。</p>
                    <p>Omni 走 ComfyUI 自带 Gemini Video Omni 节点或 ComfyUI-Kie 包，本包不重复。</p>
                </div>`;
            const form = el.querySelector(".ariadne-workbench");
            const log = el.querySelector("#ariadne-log");
            const say = (text) => { log.textContent = text; };
            fetch("/ariadne/config").then((response) => response.json()).then((data) => {
                form.querySelector("[name=ark_api_key]").placeholder = data.ark_api_key || "未配置";
                form.querySelector("[name=kie_api_key]").placeholder = data.kie_api_key || "未配置";
                form.querySelector("[name=tos_accessKey]").placeholder = data.tos?.accessKey || "未配置";
                form.querySelector("[name=tos_bucket]").value = data.tos?.bucket || "";
                form.querySelector("[name=tos_region]").value = data.tos?.region || "";
                form.querySelector("[name=tos_endpoint]").value = data.tos?.endpoint || "";
                form.querySelector("[name=opt_base_url]").value = data.optimizer?.base_url || "";
                form.querySelector("[name=opt_model]").value = data.optimizer?.model || "";
                form.querySelector("[name=opt_api_key]").placeholder = data.optimizer?.api_key || "未配置";
            }).catch(() => {});
            el.querySelector("#ariadne-save").addEventListener("click", async () => {
                const payload = {
                    tos: {
                        accessKey: form.querySelector("[name=tos_accessKey]").value,
                        secretKey: form.querySelector("[name=tos_secretKey]").value,
                        bucket: form.querySelector("[name=tos_bucket]").value,
                        region: form.querySelector("[name=tos_region]").value,
                        endpoint: form.querySelector("[name=tos_endpoint]").value,
                    },
                    optimizer: {
                        base_url: form.querySelector("[name=opt_base_url]").value,
                        model: form.querySelector("[name=opt_model]").value,
                        api_key: form.querySelector("[name=opt_api_key]").value,
                    },
                };
                const arkKey = form.querySelector("[name=ark_api_key]").value;
                const kieKey = form.querySelector("[name=kie_api_key]").value;
                if (arkKey) payload.ark_api_key = arkKey;
                if (kieKey) payload.kie_api_key = kieKey;
                const response = await fetch("/ariadne/config", {
                    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
                });
                const data = await response.json();
                say(data.error ? `保存失败：${data.error}` : "配置已保存（config.local.json，不入 Git）");
            });
            el.querySelector("#ariadne-tos-test").addEventListener("click", async () => {
                say("TOS 试传中…");
                const response = await fetch("/ariadne/tos_test", { method: "POST" });
                const data = await response.json();
                say(data.ok ? `试传成功：${data.urlHead}…` : `试传失败：${data.error}`);
            });
        },
    });
}

app.registerExtension({
    name: "ComfyUI-Ariadne.Workbench",
    setup() {
        injectCss();
        registerSidebarTab();
    },
    nodeCreated(node) {
        if (!NODE_TYPES.has(nodeType(node))) return;
        if (app.configuringGraph) return;  // 加载工作流期间不升级，交给 loadedGraphNode
        requestAnimationFrame(() => upgradeNode(node));
    },
    loadedGraphNode(node) {
        if (!NODE_TYPES.has(nodeType(node))) return;
        requestAnimationFrame(() => upgradeNode(node));
    },
});
