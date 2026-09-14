// Ariadne 前端扩展：中文标签 + 素材瓦片 + @胶囊提示词 + 裁剪浮层 + 费用预估 + 侧栏工作台 + 底部创作台。
// 避坑清单（D:\GitHub\ComfyUI\本地开发手册\避坑经验.md）落地：
// - widgets_values 双序列化（onSerialize 同时写 named 字段）
// - nodeCreated 加 app.configuringGraph 守卫 + loadedGraphNode 补挂 + requestAnimationFrame
// - DOM widget 用 computeLayoutSize 控高；宽度在 onResize 手动同步
// - 替换原生 widget 保持原位置并接住原 callback；升级动作幂等守卫
// - 每块独立 try/catch，任何前端失败都不影响节点本身
// v0.3 创作台重构：节点本体紧凑化（原生 widget 仍是唯一参数源，低频字段折叠），
// 素材/提示词/参数编辑移入底部创作台（ariadne_workbench.js），widget 操作统一走 ariadne_adapter.js。

import { app } from "../../scripts/app.js";
import {
    SEEDANCE_TYPE, SEEDANCE_FREE_TYPE, VIDEO_PANEL_TYPES, cachedTiles, collectAssets, normalizeAspectLock, syncTiles, tileKey, tilesOf, widgetValue, setProp, prop, isInputConnected,
} from "./ariadne_adapter.js";
import { commitTiles, nextRole, openTrimDialog, refreshTilesDom, renderPromptChips, uploadAsset, upstreamPreview } from "./ariadne_media.js";
import { mountPanel, unmountPanel, isPanelMounted, refreshPanel } from "./ariadne_workbench.js";

const NODE_TYPES = new Set([...VIDEO_PANEL_TYPES, "AriadneKieImage", "AriadneTopazUpscale"]);

const KIND_LABEL = { image: "图片", video: "视频", audio: "音频" };
const ROLE_LABEL = {
    "first-frame": "首帧", "last-frame": "尾帧", character: "人物", wardrobe: "服装",
    scene: "场景", motion: "动作", audio: "音频", annotation: "标注帧",
};

// 节点本体折叠的低频字段：widget 保留在 node.widgets（序列化与 callback 完整），
// 仅收起高度；创作台随时改回。prompt / ariadne_assets / 预估行 / 创作台按钮不折叠。
const COLLAPSIBLE_WIDGETS = [
    "task_type", "duration", "resolution", "aspect_ratio", "generate_audio", "output_format",
    "channel", "download_folder", "return_last_frame", "poll_interval_seconds", "timeout_seconds",
];

// 插座 → 角色标签（创作台/瓦片区共用）。
const SOCKET_META = [
    ["first_frame", "first-frame", "image", "首帧"],
    ["last_frame", "last-frame", "image", "尾帧"],
    ["character_images", "character", "image", "人物"],
    ["wardrobe_images", "wardrobe", "image", "服装"],
    ["scene_images", "scene", "image", "场景"],
    ["motion_video", "motion", "video", "动作"],
    ["image_1", "free", "image", "图像1"],
    ["image_2", "free", "image", "图像2"],
    ["image_3", "free", "image", "图像3"],
    ["reference_audio", "audio", "audio", "音频"],
];

function nodeType(node) {
    return node.comfyClass || node.constructor?.comfyClass || node.type;
}

// ---- CSS 注入（WEB_DIRECTORY 只自动加载 .js，其余动态注入；CSS 与本 js 同目录） ----
function injectCss() {
    if (document.getElementById("ariadne-css")) return;
    const link = document.createElement("link");
    link.id = "ariadne-css";
    link.rel = "stylesheet";
    link.href = new URL("./ariadne.css", import.meta.url).href;
    document.head.appendChild(link);
}

// ---- 中文标签 ----
function applyChineseLabels(node) {
    const type = nodeType(node);
    const widgetLabels = type === SEEDANCE_TYPE || type === SEEDANCE_FREE_TYPE ? {
        prompt: "提示词", task_type: "任务模式", duration: "时长（秒）", resolution: "分辨率",
        aspect_ratio: "画幅", generate_audio: "生成音频", output_format: "输出格式",
        channel: "生成渠道", download_folder: "保存文件夹", ariadne_assets: "素材",
        image_1: "图像 1", image_2: "图像 2", image_3: "图像 3",
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
    } : type === "AriadneTopazUpscale" ? {
        upscale_factor: "放大倍数", nsfw_checker: "内容审核", download_folder: "保存文件夹",
        poll_interval_seconds: "轮询间隔（秒）", timeout_seconds: "超时（秒）",
    } : {
        platform: "服务商", prompt: "提示词", aspect_ratio: "画幅", resolution: "分辨率",
        download_folder: "保存文件夹",
    };
    const inputLabels = {
        first_frame: "首帧", last_frame: "尾帧", character_images: "人物参考图",
        wardrobe_images: "服装参考图", scene_images: "场景参考图", motion_video: "动作参考视频",
        reference_audio: "参考音频", reference_images: "参考图", source_video: "源视频",
        image_1: "图像1", image_2: "图像2", image_3: "图像3",
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
// 紧凑态被 stash 的低频 widget 不在 node.widgets 里：按定义序索引合并回完整序列，
// 保证 widgets_values 位置顺序与未升级时完全一致（新前端按位恢复时旧工作流不串位）。
// 索引来源：upgradeNode 开头 installDefinitionIndexes 对 configure 后的定义序全量登记；
// 替换型 DOM widget（提示词/素材）沿用被替换者的索引；后加的预估/按钮行无索引，排最后
// 且 serialize:false，不进入两个数组。
function installDefinitionIndexes(node) {
    for (let i = 0; i < (node.widgets || []).length; i++) {
        if (node.widgets[i].__ariadneIndex === undefined) node.widgets[i].__ariadneIndex = i;
    }
}

function installCompactSerialization(node) {
    if (node.__ariadneCompact) return;
    node.__ariadneCompact = true;
    const original = node.onSerialize;
    node.onSerialize = function (info) {
        original?.call(this, info);
        const ordered = [...(this.widgets || []), ...(this.__ariadneStashed || [])]
            .map((w, liveIndex) => ({ w, key: w.__ariadneIndex ?? 1000000 + liveIndex }))
            .sort((a, b) => a.key - b.key)
            .map(({ w }) => w);
        const serialWidgets = ordered.filter((w) => w.serialize !== false);
        info.widgets_values = serialWidgets.map((w) => w.value ?? null);
        info.widgets_values_named = Object.fromEntries(serialWidgets.map((w) => [w.name, w.value ?? null]));
    };
}

// 提示词编辑与素材编排已全部移入创作台：紧凑态下提示词胶囊与「＋素材」素材行也一并摘出
// （数据载体藏进 stash，序列化/创作台读写不变），节点本体只留插座、插座已连标识条（独立）、
// 费用预估与创作台按钮行；创作台内可随时编辑。
const ALWAYS_STASHED_IN_COMPACT = ["prompt", "ariadne_assets"];

function stashWidgets(node) {
    if (!Array.isArray(node.__ariadneStashed)) node.__ariadneStashed = [];
    const stash = node.__ariadneStashed;
    for (let i = node.widgets.length - 1; i >= 0; i--) {
        const w = node.widgets[i];
        if (!COLLAPSIBLE_WIDGETS.includes(w.name) && !ALWAYS_STASHED_IN_COMPACT.includes(w.name)) continue;
        if (w.__ariadneIndex === undefined) w.__ariadneIndex = i; // 兜底：未经 installDefinitionIndexes 的旧节点
        node.widgets.splice(i, 1);
        stash.push(w);
    }
    stash.sort((a, b) => (a.__ariadneIndex || 0) - (b.__ariadneIndex || 0));
}

function unstashWidgets(node) {
    const stash = node.__ariadneStashed || [];
    for (const w of stash) {
        const index = Math.min(w.__ariadneIndex ?? node.widgets.length, node.widgets.length);
        node.widgets.splice(index, 0, w);
    }
    node.__ariadneStashed = [];
}

function applyCompactBody(node) {
    if (prop(node, "collapsed", true)) stashWidgets(node);
    else unstashWidgets(node);
    refreshSocketStrip(node);
}

// ---- Queue 提交兼容（新前端 1.51.x 实测）：graphToPrompt 用 ExecutableNodeDTO 从活
//      node.widgets 收值构建 /prompt 输入，不走 onSerialize 合并——stash 摘出的参数会整体
//      缺席，服务端报 Required input is missing。包装 app.graphToPrompt（queuePrompt 内部
//      正是 this.graphToPrompt 调用）：构建期间临时归还 stash，结束按原折叠态收回；存档
//      路径（onSerialize 双序列化）不受影响，未 stash 的节点零感知。
function installPromptCompat() {
    const original = app.graphToPrompt;
    if (typeof original !== "function") {
        console.warn("Ariadne: app.graphToPrompt 不可用，紧凑节点提交参数可能缺失（前端结构变化？）");
        return;
    }
    app.graphToPrompt = async function (...args) {
        const restored = [];
        for (const node of this.graph?._nodes || []) {
            if (node.__ariadneStashed?.length) {
                unstashWidgets(node);
                restored.push(node);
            }
        }
        try {
            return await original.apply(this, args);
        } finally {
            for (const node of restored) applyCompactBody(node);
        }
    };
}

// ---- 插座已连标识条：紧凑节点本体按插座显示「人物 · 已连接」卡（素材行撤出后的宿主）。
function connectedSocketNames(node) {
    return SOCKET_META.filter(([input]) => isInputConnected(node, input));
}

function refreshSocketStrip(node) {
    node.__ariadneRefreshSockets?.();
}

function makeSocketStripWidget(node) {
    if (node.widgets?.some((w) => w.type === "ariadne_sockets")) return;
    const wrap = document.createElement("div");
    wrap.className = "ariadne-sockets-strip";
    wrap.title = "画布连线素材的插座标识；素材编排与上传在创作台";
    const widget = node.addDOMWidget("插座状态", "ariadne_sockets", wrap, { hideOnZoom: false, serialize: false });
    widget.serialize = false;
    widget.element = wrap;
    widget.computeSize = () => [0, connectedSocketNames(node).length ? 24 : 0];
    widget.computeLayoutSize = undefined;
    widget.__ariadneRefreshSockets = () => {
        const sockets = connectedSocketNames(node);
        wrap.innerHTML = "";
        for (const [, role, kind, roleLabel] of sockets) {
            const chip = document.createElement("div");
            chip.className = "ariadne-tile ariadne-tile-socket";
            const mark = document.createElement("span");
            mark.className = "ariadne-tile-mark";
            mark.textContent = kind === "video" ? "▶" : kind === "audio" ? "♫" : "▧";
            const name = document.createElement("span");
            name.className = "ariadne-tile-name";
            name.textContent = `${roleLabel} · 已连接`;
            name.title = `插座已连接，职责固定为「${ROLE_LABEL[role]}」；素材编排见创作台`;
            chip.append(mark, name);
            wrap.appendChild(chip);
        }
        wrap.style.display = sockets.length ? "flex" : "none";
        setTimeout(() => {
            try {
                node.setSize([Math.max(node.size[0], 380), node.computeSize()[1]]);
                node.setDirtyCanvas(true, true);
            } catch { /* 新前端布局自适应 */ }
        }, 30);
    };
    widget.__ariadneRefreshSockets();
    node.__ariadneRefreshSockets = () => widget.__ariadneRefreshSockets();
    syncDomWidths(node);
}

// ---- 创作台：按钮行 + 面板锚点（锚点必须是最后一个 widget，面板才能悬挂在节点最底部） ----
function makeDockButtonWidget(node) {
    if (node.widgets?.some((w) => w.type === "ariadne_dock_btn")) return;

    const row = document.createElement("div");
    row.className = "ariadne-dockbtnrow";
    const open = document.createElement("button");
    open.type = "button";
    open.className = "ariadne-btn ariadne-btn-accent";
    open.textContent = "✦ 打开创作台";
    open.title = "打开创作台面板（创作 / 提示词工作台 / 输出参数），面板悬挂在本节点下方，随节点移动";
    open.setAttribute("aria-label", "打开创作台");
    open.addEventListener("click", () => node.__ariadnePanelApi.toggle());
    row.append(open);
    // 费用预估挂在按钮行右侧（同一行，不再独占一行；元素由 makeEstimateWidget 先行创建）
    if (node.__ariadneEstimateEl) row.append(node.__ariadneEstimateEl);
    const widget = node.addDOMWidget("创作台", "ariadne_dock_btn", row, { hideOnZoom: false, serialize: false });
    widget.serialize = false;  // 显式：避免旧前端忽略 options.serialize 进入 widgets_values
    widget.computeSize = () => [0, 34];
    widget.computeLayoutSize = undefined;
    widget.element = row;

    // 面板锚点：最后一个 widget = 紧贴节点底边；面板绝对定位悬挂其下（top 预留徽标高度）
    const anchor = document.createElement("div");
    anchor.className = "ariadne-workbench-anchor";
    anchor.style.display = "none";
    const panelWidget = node.addDOMWidget("创作台面板", "ariadne_workbench_panel", anchor, { hideOnZoom: false, serialize: false });
    panelWidget.serialize = false;
    panelWidget.element = anchor;
    panelWidget.computeSize = () => [0, anchor.style.display === "none" ? 0 : 1];
    panelWidget.computeLayoutSize = undefined;

    const scheduleResize = () => setTimeout(() => {
        try {
            node.setDirtyCanvas(true, true);
        } catch { /* 新前端布局自适应 */ }
    }, 30);

    // 面板开关挂到节点上：创作台「收起」按钮与节点按钮共用同一入口
    node.__ariadnePanelApi = {
        show() {
            anchor.style.display = "block";
            mountPanel(anchor, node, scheduleResize);
            scheduleResize();
        },
        hide() {
            unmountPanel();
            anchor.style.display = "none";
        },
        toggle() {
            if (anchor.style.display === "none") node.__ariadnePanelApi.show();
            else node.__ariadnePanelApi.hide();
        },
    };

    syncDomWidths(node);
}

// ---- 素材瓦片（Seedance 节点专属）：瓦片卡 + 插座已连卡 ----
function refreshTilesWidget(node) {
    const widget = node.widgets?.find((w) => w.name === "ariadne_assets");
    if (!widget?.element) return;
    const tiles = tilesOf(node);
    const grid = widget.element.querySelector(".ariadne-tiles");
    const summary = widget.element.querySelector(".ariadne-tiles-summary");
    if (!grid) return;
    grid.innerHTML = "";
    // 插座素材卡：连线后自动出现，职责由插座固定，带「已连接」标识。
    for (const [input, role, kind, roleLabel] of SOCKET_META) {
        if (!isInputConnected(node, input)) continue;
        const chip = document.createElement("div");
        chip.className = "ariadne-tile ariadne-tile-socket";
        const mark = document.createElement("span");
        mark.className = "ariadne-tile-mark";
        mark.textContent = kind === "video" ? "▶" : kind === "audio" ? "♫" : "▧";
        const name = document.createElement("span");
        name.className = "ariadne-tile-name";
        name.textContent = `${roleLabel} · 已连接`;
        name.title = `插座 ${input}（${ROLE_LABEL[role]}）：职责由插座固定，编号在瓦片之后`;
        chip.append(mark, name);
        grid.appendChild(chip);
    }
    for (const tile of tiles) {
        const chip = document.createElement("div");
        chip.className = "ariadne-tile" + (tile.trimmed ? " ariadne-tile-trimmed" : "") + (tile.locked ? " ariadne-tile-locked" : "");
        const mark = document.createElement("span");
        mark.className = "ariadne-tile-mark";
        mark.textContent = (tile.locked ? "🔒" : "") + (tile.trimmed ? `✂ ${Math.round(tile.seconds || 0)}s` : KIND_LABEL[tile.kind]);
        const name = document.createElement("span");
        name.className = "ariadne-tile-name";
        name.textContent = tile.label || tile.name;
        name.title = `${tile.name}（${ROLE_LABEL[tile.role] || tile.role}${tile.trimmed ? `，已裁 ${Math.round(tile.seconds || 0)}s` : ""}${tile.locked ? "，身份锁定" : ""}）`;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "ariadne-tile-remove";
        remove.textContent = "×";
        remove.title = "移除素材";
        remove.setAttribute("aria-label", `移除素材 ${tile.label || tile.name}`);
        remove.addEventListener("click", () => {
            commitTiles(node, tilesOf(node).filter((item) => tileKey(item) !== tileKey(tile)));
            node.setDirtyCanvas(true, true);
        });
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "ariadne-tile-role";
        edit.textContent = ROLE_LABEL[tile.role] || tile.role;
        edit.title = "切换素材职责";
        edit.setAttribute("aria-label", `切换素材 ${tile.label || tile.name} 职责`);
        edit.addEventListener("click", () => {
            const current = tilesOf(node);
            const target = current.find((item) => tileKey(item) === tileKey(tile));
            if (target) target.role = nextRole(target.role);
            commitTiles(node, current);
        });
        const trimBtn = document.createElement("button");
        trimBtn.type = "button";
        trimBtn.className = "ariadne-tile-trim";
        trimBtn.textContent = "✂";
        trimBtn.title = "节点内裁剪（省钱：参考视频比输出长的部分全是白付的输入时长）";
        trimBtn.setAttribute("aria-label", `裁剪视频素材 ${tile.label || tile.name}`);
        trimBtn.addEventListener("click", () => openTrimDialog(node, tile));
        chip.append(mark, name, edit, trimBtn, remove);
        grid.appendChild(chip);
    }
    const videoTiles = tiles.filter((tile) => tile.kind === "video");
    if (summary) {
        summary.textContent = tiles.length
            ? `${tiles.length} 个素材${videoTiles.some((tile) => tile.trimmed) ? " · 已裁" + videoTiles.filter((tile) => tile.trimmed).length + "段" : ""}`
            : "在创作台拖入/上传素材，或连接左侧插座";
    }
    syncDomWidths(node);
}

function syncDomWidths(node) {
    // DOM widget 元素必须显式定宽：默认 width:100% 会继承到全画布宽（溢出 1300px——实机复现）。
    const width = `${Math.max(100, Number(node.size?.[0] || 0) - 22)}px`;
    for (const type of ["ariadne_assets", "ariadne_prompt", "ariadne_estimate", "ariadne_dock_btn", "ariadne_sockets"]) {
        const widget = node.widgets?.find((w) => w.type === type);
        if (widget?.element) widget.element.style.width = width;
    }
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
        add.disabled = true;
        try {
            for (const file of fileInput.files || []) await uploadTile(node, file);
        } finally {
            add.disabled = false;
            fileInput.value = "";
        }
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
    widget.__ariadneIndex = old.__ariadneIndex;  // 沿用被替换者的定义序索引（序列化合并用）
    // 保留原位置：替换原生 STRING widget。
    const index = node.widgets.indexOf(old);
    old.onRemove?.();
    node.widgets.splice(index, 1);
    const appended = node.widgets.indexOf(widget);
    if (appended >= 0) node.widgets.splice(appended, 1);
    node.widgets.splice(index, 0, widget);
    const originalResize = node.onResize;
    node.onResize = function (...args) {
        syncDomWidths(node);
        return originalResize?.apply(this, args);
    };
    syncDomWidths(node);
    refreshTilesWidget(node);
    // 暴露刷新句柄：创作台等外部模块改动瓦片后统一触发重渲染。
    widget.__ariadneRefreshTiles = () => refreshTilesWidget(node);
}

async function uploadTile(node, file) {
    addStatus(node, `上传 ${file.name} …`);
    try {
        const data = await uploadAsset(file);
        const tiles = tilesOf(node);
        tiles.push({
            kind: data.kind, name: data.name, subfolder: data.subfolder, role: data.role,
            seconds: data.seconds || 0, width: data.width || 0, height: data.height || 0,
            pixelsOk: data.pixelsOk, probeError: data.probeError,
        });
        commitTiles(node, tiles);
        if (data.kind === "video" && data.pixelsOk === false) {
            addStatus(node, `${file.name} 像素 ${data.width}×${data.height} 低于官方 407696 下限，提交会被方舟拒绝（请放大后重导）`);
        } else {
            addStatus(node, `${file.name} 已添加`);
        }
    } catch (error) {
        addStatus(node, `上传失败：${error?.message || error}`);
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
    editor.dataset.placeholder = "描述画面；@ 唤出素材选单，或在创作台编辑";

    let lastValue = String(old.value || "");  // blur 空读保护的对照值（old 已移除，读不到新值）
    // 胶囊标签用 collectAssets（瓦片+插座素材并集），与创作台同一契约
    const render = (text) => renderPromptChips(editor, String(text ?? ""), collectAssets(node));

    const widget = node.addDOMWidget("prompt", "ariadne_prompt", editor, {
        hideOnZoom: true, serialize: true,
        getValue: () => editor.innerText.replace(/\u00a0/g, " "),
        setValue: (value) => {
            lastValue = String(value || "");
            render(lastValue);
        },
    });
    widget.serialize = true;
    widget.serializeValue = () => editor.innerText.replace(/\u00a0/g, " ");
    widget.computeLayoutSize = () => ({ minHeight: 96, maxHeight: 4000 });
    widget.element = editor;
    widget.__ariadneIndex = old.__ariadneIndex;  // 沿用被替换者的定义序索引（序列化合并用）
    const originalCallback = old.callback;
    widget.callback = originalCallback;
    editor.addEventListener("input", () => {
        lastValue = widget.getValue();
        widget.callback?.(lastValue);
        node.setDirtyCanvas(true, true);
    });
    editor.addEventListener("keydown", (event) => {
        if (event.ctrlKey || event.metaKey || event.altKey) return;  // 放行全局快捷键（Ctrl+Enter 队列等）
        if (event.key === "@") setTimeout(() => openAssetMenu(node, editor), 0);
        event.stopPropagation();
    });
    editor.addEventListener("blur", () => {
        // 空读保护（画布版 0.1.1 提示词丢失事故教训）：编辑器空而最近值非空时回滚重绘，不写空串。
        const current = widget.getValue();
        if (!current.trim() && lastValue.trim()) render(lastValue);
    });

    const index = node.widgets.indexOf(old);
    old.onRemove?.();
    node.widgets.splice(index, 1);
    const appended = node.widgets.indexOf(widget);
    if (appended >= 0) node.widgets.splice(appended, 1);
    node.widgets.splice(index, 0, widget);
    syncDomWidths(node);
    render(lastValue);
}

function openAssetMenu(node, editor) {
    const tiles = cachedTiles(node);
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
            dismissNow();
        });
        menu.appendChild(item);
    }
    positionMenu(editor, menu);
    const dismiss = (event) => {
        if (!menu.contains(event.target)) dismissNow();
    };
    const dismissNow = () => {
        menu.remove();
        document.removeEventListener("mousedown", dismiss);
    };
    setTimeout(() => document.addEventListener("mousedown", dismiss), 0);
}

function insertAtCursor(editor, text) {
    editor.focus();
    const selection = window.getSelection();
    if (!selection.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!editor.contains(range.startContainer)) return;  // 焦点漂移时不插进无关节点
    // 菜单由输入 @ 唤出：光标前已是 @ 时先删掉，避免产生 @@视频1 双前缀。
    if (range.startContainer.nodeType === Node.TEXT_NODE && range.startOffset > 0) {
        const before = range.startContainer.textContent[range.startOffset - 1];
        if (before === "@") {
            range.setStart(range.startContainer, range.startOffset - 1);
            range.deleteContents();
        }
    }
    range.collapse(true);
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

// ---- 费用预估（Seedance 节点）：不再单独占一行，元素挂到创作台按钮行右侧 ----
function makeEstimateWidget(node) {
    if (nodeType(node) !== SEEDANCE_TYPE) return null;
    if (node.__ariadneEstimateEl) return node.__ariadneEstimateEl;
    // 移除历史节点升级残留的旧版独立费用行 widget
    const legacy = node.widgets?.find((w) => w.type === "ariadne_estimate");
    if (legacy) {
        legacy.onRemove?.();
        const legacyIndex = node.widgets.indexOf(legacy);
        if (legacyIndex >= 0) node.widgets.splice(legacyIndex, 1);
    }
    const note = document.createElement("div");
    note.className = "ariadne-estimate";
    note.textContent = "费用预估: …";
    node.__ariadneEstimateEl = note;
    const refresh = () => refreshEstimate(node, note);
    for (const name of ["duration", "resolution", "channel", "task_type"]) {
        const target = node.widgets?.find((w) => w.name === name);
        if (!target) continue;
        const original = target.callback;
        target.callback = function (...args) {
            const result = original?.apply(this, args);
            refresh();
            return result;
        };
    }
    const originalConnections = node.onConnectionsChange;
    node.onConnectionsChange = function (...args) {
        const result = originalConnections?.apply(this, args);
        refresh();
        // 插座连线变化 → 紧凑态插座标识条与素材区（展开态）同步刷新。
        node.__ariadneRefreshSockets?.();
        refreshTilesWidget(node);
        // 打开中的创作台面板同步重渲染：连线素材预览瓦片即时出现（此前要开关一次面板）
        refreshPanel(node);
        return result;
    };
    syncDomWidths(node);
    refresh();
    return note;
}

let estimateSeq = 0;

async function refreshEstimate(node, note) {
    // 经适配器按名读值：紧凑态下这些 widget 在 stash 里，不在 node.widgets。
    const value = (name) => widgetValue(node, name);
    const channel = String(value("channel") || "ark").startsWith("kie") ? "kie" : "ark";
    const tiles = tilesOf(node);  // 用本节点的瓦片（WeakMap 隔离，不再用全局单例）
    const includesVideo = isInputConnected(node, "motion_video") || tiles.some((tile) => tile.kind === "video");
    const inputSeconds = tiles.filter((tile) => tile.kind === "video").reduce((sum, tile) => sum + Number(tile.seconds || 0), 0);
    const seq = ++estimateSeq;
    try {
        const response = await fetch("/ariadne/estimate", {
            method: "POST", headers: { "content-type": "application/json" },
            body: JSON.stringify({
                channel, resolution: value("resolution"), duration: Number(value("duration") ?? 0),
                includesVideoInput: includesVideo, inputVideoSeconds: inputSeconds,
            }),
        });
        const data = await response.json();
        if (seq !== estimateSeq) return;  // 快速改参数时丢弃过期响应
        const estimate = data.estimate;
        if (!estimate) { note.textContent = "费用预估: --"; return; }
        note.textContent = `费用预估 ≈¥${estimate.cny}`;
    } catch {
        if (seq === estimateSeq) note.textContent = "费用预估: 不可用";
    }
}

// ---- 费用预估（Topaz 节点）：按上游源视频时长 × 放大倍数估价。
//      Topaz 无提示词/素材/生成，不挂创作台按钮——预估独立成行（widget 类型沿用 ariadne_estimate，宽度同步已覆盖）。
function makeTopazEstimateWidget(node) {
    if (node.__ariadneEstimateEl) return node.__ariadneEstimateEl;
    const note = document.createElement("div");
    note.className = "ariadne-estimate";
    note.textContent = "费用预估: …";
    node.__ariadneEstimateEl = note;
    const row = document.createElement("div");
    row.append(note);
    const widget = node.addDOMWidget("费用预估", "ariadne_estimate", row, { hideOnZoom: false, serialize: false });
    widget.serialize = false;
    widget.element = row;
    widget.computeSize = () => [0, 24];
    widget.computeLayoutSize = undefined;
    const refresh = () => refreshTopazEstimate(node, note);
    const factorWidget = node.widgets?.find((w) => w.name === "upscale_factor");
    if (factorWidget) {
        const original = factorWidget.callback;
        factorWidget.callback = function (...args) {
            const result = original?.apply(this, args);
            refresh();
            return result;
        };
    }
    const originalConnections = node.onConnectionsChange;
    node.onConnectionsChange = function (...args) {
        node.__ariadneTopazDuration = undefined;  // 换源后重探时长
        const result = originalConnections?.apply(this, args);
        refresh();
        return result;
    };
    syncDomWidths(node);
    refresh();
    return note;
}

function probeVideoDuration(url) {
    return new Promise((resolve, reject) => {
        const video = document.createElement("video");
        video.preload = "metadata";
        const finish = (value, error) => {
            video.onloadedmetadata = null;
            video.onerror = null;
            if (value > 0) resolve(value);
            else reject(error || new Error("视频时长未知"));
        };
        video.onloadedmetadata = () => finish(Number(video.duration) || 0);
        video.onerror = () => finish(0, new Error("视频读取失败"));
        window.setTimeout(() => finish(0, new Error("视频时长探测超时")), 8000);
        video.src = url;
    });
}

async function refreshTopazEstimate(node, note) {
    const factor = String(widgetValue(node, "upscale_factor") || "2").split("(")[0].trim();
    let duration = Number(node.__ariadneTopazDuration || 0);
    if (!(duration > 0)) {
        // 时长从 source_video 上游（LoadVideo 类，取其源文件 /view 地址）探：生成类上游无落盘文件则显示 --
        const preview = upstreamPreview(node, "source_video");
        if (preview.url && preview.isVideo) {
            try {
                duration = await probeVideoDuration(preview.url);
                node.__ariadneTopazDuration = duration;
            } catch {
                duration = 0;
            }
        }
    }
    const seq = ++estimateSeq;
    if (!(duration > 0)) { note.textContent = "费用预估: --"; return; }
    try {
        const response = await fetch("/ariadne/estimate", {
            method: "POST", headers: { "content-type": "application/json" },
            body: JSON.stringify({ kind: "topaz", factor, durationSeconds: duration }),
        });
        const data = await response.json();
        if (seq !== estimateSeq) return;  // 快速改参数时丢弃过期响应
        const estimate = data.estimate;
        note.textContent = estimate ? `费用预估 ≈¥${estimate.cny}` : "费用预估: --";
    } catch {
        if (seq === estimateSeq) note.textContent = "费用预估: 不可用";
    }
}

// ---- 升级入口 ----
function upgradeNode(node) {
    const type = nodeType(node);
    if (!NODE_TYPES.has(type)) return;
    if (node.__ariadneUpgraded) return;
    node.__ariadneUpgraded = true;
    const safe = (label, fn) => { try { fn(); } catch (error) { console.error(`Ariadne ${label}`, error); } };
    safe("定义序索引", () => installDefinitionIndexes(node));  // 必须先于一切 widget 替换/摘出
    safe("标签", () => applyChineseLabels(node));
    safe("序列化", () => installCompactSerialization(node));
    if (type === SEEDANCE_TYPE || type === SEEDANCE_FREE_TYPE) {
        safe("瓦片", () => makeTilesWidget(node));
        safe("标签刷新", () => { syncTiles(node); refreshTilesDom(node); });  // 瓦片 widget 建好后重算编号（不依赖闭包机制）
        safe("胶囊提示词", () => makeCapsulePrompt(node));
        safe("插座标识条", () => makeSocketStripWidget(node));
        safe("估价", () => makeEstimateWidget(node));
        safe("创作台按钮", () => makeDockButtonWidget(node));
        safe("紧凑化", () => applyCompactBody(node));
        safe("画幅锁定", () => normalizeAspectLock(node));  // 载入即锁定模式时自愈为自适应（幂等）
    } else if (type === "AriadneTopazUpscale") {
        // Topaz 无提示词/素材/生成：不挂创作台按钮与面板，只挂费用预估行
        safe("估价", () => makeTopazEstimateWidget(node));
    } else {
        // 视频家族其他节点：轻量创作台（素材条/提示词/生成），参数仍在节点本体
        safe("创作台按钮", () => makeDockButtonWidget(node));
    }
    // 高度重算必须在 DOM widget 挂载后（挂载前 offsetHeight=0，同步 setSize 会压扁高度把
    // 底部 widget 挤出节点边界——实机复现）。rAF 在后台标签会被节流到永不执行，用 setTimeout 兜底。
    // 宽度下限 380 与高度一起在重算后钳制（computeSize 会返回窄宽度覆盖先前的加宽——实机复现）。
    setTimeout(() => {
        try {
            const size = node.computeSize();
            node.setSize([Math.max(size[0], 380), size[1]]);
            node.setDirtyCanvas(true, true);
        } catch { /* 新前端布局自适应 */ }
    }, 60);
    node.setDirtyCanvas(true, true);
}

// ---- 侧栏工作台：配置 + 用法（全局配置；单节点创作状态在底部创作台） ----
function registerSidebarTab() {
    if (!app.extensionManager?.registerSidebarTab) return;
    app.extensionManager.registerSidebarTab({
        id: "ariadne-workbench",
        icon: "pi pi-video",
        title: "Ariadne 设置",
        tooltip: "Ariadne 全部节点 API 设置：密钥/对象存储/提示词优化器",
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
                    <label>模型<span class="ariadne-workbench-modelrow"><input name="opt_model" placeholder="填写或从拉取列表选择" list="ariadne-sidebar-models"><button type="button" class="ariadne-btn" id="ariadne-opt-pull">拉取</button></span><datalist id="ariadne-sidebar-models"></datalist></label>
                    <label>Key<input name="opt_api_key" type="password" placeholder="留空不修改"></label>
                    <div class="ariadne-workbench-actions">
                        <button type="button" class="ariadne-btn" id="ariadne-save">保存配置</button>
                        <button type="button" class="ariadne-btn" id="ariadne-tos-test">TOS 试传验证</button>
                    </div>
                    <pre class="ariadne-workbench-log" id="ariadne-log"></pre>
                    <h3>用法速记</h3>
                    <p>双击 Seedance 节点打开底部创作台 → ①「创作」页连线/上传素材、切模式、写提示词 → ②「提示词工作台」按 sd25-pe 技能流式优化、确认后应用 → ③「输出参数」调分辨率/画幅/时长 → ④ Queue 出片，成片自动落 output/ariadne/。</p>
                    <p>所有节点的 API 设置都在本页填写（存 config.local.json，不入 Git）；单节点创作状态都在底部创作台。</p>
                </div>`;
            const form = el.querySelector(".ariadne-workbench");
            const log = el.querySelector("#ariadne-log");
            const say = (text) => { log.textContent = text; };
            (async () => {
                try {
                    const response = await fetch("/ariadne/config");
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    const data = await response.json();
                    // 已配置的密钥只显示状态不回显字符（脱敏边界）。
                    form.querySelector("[name=ark_api_key]").placeholder = data.ark_api_key ? "已配置（留空不修改）" : "未配置";
                    form.querySelector("[name=kie_api_key]").placeholder = data.kie_api_key ? "已配置（留空不修改）" : "未配置";
                    form.querySelector("[name=tos_accessKey]").placeholder = data.tos?.accessKey ? "已配置（留空不修改）" : "未配置";
                    form.querySelector("[name=tos_bucket]").value = data.tos?.bucket || "";
                    form.querySelector("[name=tos_region]").value = data.tos?.region || "";
                    form.querySelector("[name=tos_endpoint]").value = data.tos?.endpoint || "";
                    form.querySelector("[name=opt_base_url]").value = data.optimizer?.base_url || "";
                    form.querySelector("[name=opt_model]").value = data.optimizer?.model || "";
                    form.querySelector("[name=opt_api_key]").placeholder = data.optimizer?.api_key ? "已配置（留空不修改）" : "未配置";
                } catch (error) {
                    say(`读取配置失败（节点包路由未加载？）：${error?.message || error}`);
                }
            })();
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
                try {
                    const response = await fetch("/ariadne/config", {
                        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
                    });
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    const data = await response.json();
                    say(data.error ? `保存失败：${data.error}` : "配置已保存（config.local.json，不入 Git）");
                } catch (error) {
                    say(`保存失败：${error?.message || error}`);
                }
            });
            el.querySelector("#ariadne-tos-test").addEventListener("click", async () => {
                say("TOS 试传中…");
                try {
                    const response = await fetch("/ariadne/tos_test", { method: "POST" });
                    const data = await response.json();
                    say(data.ok ? `试传成功：${data.urlHead}…` : `试传失败：${data.error}`);
                } catch (error) {
                    say(`试传失败：${error?.message || error}`);
                }
            });
            // 拉取优化器模型列表：与创作台输出参数页同一路由；Key 留空时服务端用已存配置
            el.querySelector("#ariadne-opt-pull").addEventListener("click", async () => {
                say("拉取模型列表中…");
                try {
                    const response = await fetch("/ariadne/optimize_models", {
                        method: "POST", headers: { "content-type": "application/json" },
                        body: JSON.stringify({
                            base_url: form.querySelector("[name=opt_base_url]").value.trim(),
                            api_key: form.querySelector("[name=opt_api_key]").value.trim(),
                        }),
                    });
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
                    const models = data.models || [];
                    const dataList = el.querySelector("#ariadne-sidebar-models");
                    dataList.innerHTML = "";
                    for (const id of models) {
                        const option = document.createElement("option");
                        option.value = id;
                        dataList.appendChild(option);
                    }
                    say(models.length ? `已拉取 ${models.length} 个模型：点模型输入框从列表选择` : "站点未返回模型列表，可手动填写");
                } catch (error) {
                    say(`拉取失败：${error?.message || error}`);
                }
            });
        },
    });
}

// ---- 新建节点时自动补一个保存节点并接线（用户经常忘记接保存，2026-09-14 要求）。
//      只在拖入新建时执行：载入工作流走 loadedGraphNode 不进来；复制粘贴/已接线的输出已有连线也不动作。
//      视频输出接 SaveVideo；图像输出（一瞬入画）接 SaveImage。
function autoConnectSaveVideo(node) {
    try {
        if (node.outputs?.[0]?.links?.length) return;
        const isImageOut = String(node.outputs?.[0]?.type || "") === "IMAGE";
        const saveType = isImageOut ? "SaveImage" : "SaveVideo";
        const LG = window.LiteGraph || globalThis.LiteGraph;
        const saveNode = LG?.createNode?.(saveType);
        if (!saveNode) return;
        saveNode.pos = [node.pos[0] + (node.size?.[0] || 320) + 60, node.pos[1]];
        app.graph.add(saveNode);
        node.connect(0, saveNode, 0);
    } catch (error) {
        console.warn("Ariadne 自动接保存节点失败：", error);
    }
}

app.registerExtension({
    name: "ComfyUI-Ariadne.Workbench",
    setup() {
        injectCss();
        registerSidebarTab();
        installPromptCompat();
    },

    nodeCreated(node) {
        if (!NODE_TYPES.has(nodeType(node))) return;
        if (app.configuringGraph) return;  // 加载工作流期间不升级，交给 loadedGraphNode
        upgradeNode(node);
        if (VIDEO_PANEL_TYPES.has(nodeType(node))) autoConnectSaveVideo(node);
    },
    loadedGraphNode(node) {
        if (!NODE_TYPES.has(nodeType(node))) return;
        upgradeNode(node);
    },
});
