// Ariadne 创作台面板：作为 DOM widget 挂在 Seedance 节点本体上（长在节点下方），
// 定位由画布前端负责——节点拖动、画布平移缩放时面板天然跟随，与 Daedalus 画布的面板一致。
// 三个一级页面：创作 / 提示词工作台 / 输出参数。所有数据只经 ariadne_adapter 读写
// 同一节点的原生 widget / properties——面板不维护第二套数据源，节点本体始终是唯一生成参数源。
// 视觉密度对齐无限画布原版设计（seedance-2.5/src/index.tsx）：素材 52px 缩略条、
// 行内 @胶囊提示词、单行底栏（参数摘要｜✧优化｜状态▾历史｜有声/尾帧/裁剪｜价格+生成）。

import {
    MODES, KIND_LABEL, ROLE_LABEL, SEEDANCE_TYPE, SEEDANCE_FREE_TYPE, VIDEO_PANEL_TYPES, buildOptimizerUserContent,
    collectAssets, humanizeExecutionResult, isInputConnected, modeOf, modeRules, normalizeAspectLock, prop,
    setMode, setProp, setWidgetValue, skillForNode, tileKey,
    tilesOf, widgetValue,
} from "./ariadne_adapter.js";
import {
    commitTiles, caretOffsetIn, nextRole, openTrimDialog, placeCaretOffset,
    previewFromUpstream, renderPromptChips, upstreamPreview, viewUrl,
} from "./ariadne_media.js";
import { runOptimizer } from "./ariadne_optimizer_client.js";

const SOCKET_META = [
    ["first_frame", "first-frame", "image", "首帧"],
    ["last_frame", "last-frame", "image", "尾帧"],
    ["character_images", "character", "image", "人物"],
    ["wardrobe_images", "wardrobe", "image", "服装"],
    ["scene_images", "scene", "image", "场景"],
    ["motion_video", "motion", "video", "动作"],
    ["reference_audio", "audio", "audio", "音频"],
];

const MODE_LIMITS = {
    auto: "支持图片、视频、音频自由组合（至多 30 图 / 10 视频 / 10 音频）",
    edit: "支持 1 段视频作为编辑母版；画幅与时长锁定为原视频（时长=自适应）",
    text: "无需素材，直接输入提示词",
    "first-frame": "支持首帧插座连接 1 张图片；输出画幅锁定为首帧画幅",
    "first-last": "支持首帧 + 尾帧各 1 张图片；两帧画幅应一致",
    extend: "支持 1 段原视频，追加生成内容",
};

const state = {
    node: null,
    page: "create",
    abort: null,
    running: false,
    streamText: "",
    syncTimer: null,
    note: "",
    optimizerConfigured: undefined,
    dragTileKey: "",
    onLayout: null,
};

// 打开状态由 ui.js 的面板 widget 持有（container 显示/隐藏 + 高度计入节点尺寸）；
// 本模块只负责往容器里渲染内容与读写节点数据。
let root = null;
let els = {};

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

// ---------------------------------------------------------------------------
// 装配：面板挂进 ui.js 传进来的容器（节点身上的 DOM widget 槽位）
// ---------------------------------------------------------------------------

function buildPanel(container, node) {
    container.innerHTML = "";
    // 内层面板（绝对定位悬挂在锚点下方，居中于节点；样式见 .ariadne-workbench-panel）
    root = el("div", "ariadne-dock ariadne-workbench-panel");
    container.appendChild(root);
    root.setAttribute("role", "region");
    root.setAttribute("aria-label", "Seedance 创作台");
    els = {};

    const body = el("div", "ariadne-dock-body");
    body.tabIndex = -1;
    root.append(body);

    // 面板内键盘事件不上抛（防 Delete/空格触发画布快捷键）；Ctrl/Meta 组合放行（Ctrl+Enter 队列等）。
    root.addEventListener("keydown", (event) => {
        if (!event.ctrlKey && !event.metaKey) event.stopPropagation();
    });
    // 拖入文件回归 ComfyUI 原生处理（生成 LoadImage/LoadVideo 节点后连线接入）——面板不拦截。
    root.title = "";
    els = { body };

    // 节点侧提示词可能被节点本体编辑：低频轮询保持面板同步（不抢输入焦点）；
    // 同时按画布缩放同步锚点宽度，让 CSS left:50% 居中始终对准节点中心。
    state.syncTimer = setInterval(() => {
        // 卸载时 unmountPanel 会置 root=null 并自行清除本 timer；此处兜底防泄漏。
        if (!state.node || root === null) { clearInterval(state.syncTimer); return; }
        try {
            const scale = app.canvas?.ds?.scale || 1;
            container.style.width = `${Math.round(node.size?.[0] * scale)}px`;
        } catch { /* 画布未就绪时跳过本轮 */ }
        const active = document.activeElement;
        if (active && root.contains(active) && (active.tagName === "TEXTAREA" || active.tagName === "INPUT" || active.isContentEditable)) return;
        const prompt = String(widgetValue(state.node, "prompt") || "");
        if (els.promptEditor && els.promptEditor.getValue() !== prompt) els.promptEditor.setValue(prompt);
        if (els.optimizePrompt && els.optimizePrompt.value !== prompt) els.optimizePrompt.value = prompt;
    }, 600);
}

// 挂载：把面板渲染进容器并绑定节点。onLayout 在每次渲染后回调（ui.js 用于把面板高度计入节点尺寸）。
export function mountPanel(container, node, onLayout) {
    unmountPanel();
    state.node = node;
    state.onLayout = onLayout || null;
    state.note = "";
    buildPanel(container, node);
    syncOptimizerConfigured();
    render();
}

export function unmountPanel() {
    if (state.syncTimer) { clearInterval(state.syncTimer); state.syncTimer = null; }
    root = null;
    els = {};
    state.onLayout = null;
}

export function isPanelMounted(node) {
    return root !== null && state.node === node;
}

// 连线变化等画布侧事件 → 打开中的面板整体重渲染（素材条新增连线预览瓦片、模式锁定态同步）。
// 面板未挂载或不属于该节点时是安全的 no-op。
export function refreshPanel(node) {
    if (!isPanelMounted(node)) return;
    render();
}

async function syncOptimizerConfigured() {
    try {
        const response = await fetch("/ariadne/config");
        const data = await response.json();
        const opt = data.optimizer || {};
        state.optimizerConfigured = Boolean(opt.base_url && opt.model && opt.api_key);
    } catch {
        state.optimizerConfigured = undefined;
    }
    if (root && state.page === "create") render();
}

// ---------------------------------------------------------------------------
// 渲染
// ---------------------------------------------------------------------------

function render() {
    if (!root) return;
    els.body.innerHTML = "";
    els.promptEditor = null;
    els.optimizePrompt = null;
    els.resultPane = null;
    if (!state.node) {
        els.body.appendChild(el("div", "ariadne-dock-empty", "未绑定节点。"));
        return;
    }
    if (state.page === "create") renderCreatePage();
    else renderParamsPage();
    // 内容高度变化（切页/流式换行等）后通知 ui.js 重算节点尺寸
    if (state.onLayout) state.onLayout();
}

// ---------- 创作页（原版密度：模式页签 / 素材缩略条 / 行内胶囊提示词） ----------

// ---------- 轻量创作台（Veo/可灵/Omni/一瞬入画）：素材条 + 提示词 + 生成；参数仍在节点本体 ----------
function renderGenericCreatePage(node) {
    const page = el("div", "ariadne-dock-page");
    const scroll = el("div", "ariadne-dock-scroll");

    // @引用编辑只在有真 prompt 契约的节点启用；一瞬入画没有自由提示词，改编辑「追加约束」
    const hasPrompt = typeof widgetValue(node, "prompt") === "string";
    const noteMode = !hasPrompt && typeof widgetValue(node, "extra_note") === "string";
    const textField = hasPrompt ? "prompt" : noteMode ? "extra_note" : null;

    const assets = collectAssets(node);
    const strip = el("div", "ariadne-dock-strip");
    strip.title = textField === "prompt"
        ? "素材全走连线：批量图像按张数展开；一个瓦片 = 一张引用，点击把 @引用 写进提示词"
        : "素材全走连线：批量图像按张数展开；一个瓦片 = 一张参考";
    for (const asset of assets) {
        const chip = el("button", "ariadne-dock-chip socket", `@${asset.label}`);
        chip.type = "button";
        chip.title = `连线素材：${KIND_LABEL[asset.kind]}·${ROLE_LABEL[asset.role] || ""}` +
            (textField === "prompt" ? `；点击把 @${asset.label} 写进提示词` : "（预览）");
        if (textField === "prompt") {
            chip.addEventListener("click", () => {
                const text = String(widgetValue(node, "prompt") || "");
                setWidgetValue(node, "prompt", `${text}${text && !text.endsWith(" ") ? " " : ""}@${asset.label} `);
                state.note = `已写入 @${asset.label}；该素材的身份/职责请在提示词中说明`;
                render();
            });
        }
        strip.appendChild(chip);
    }
    if (!assets.length) strip.appendChild(el("span", "ariadne-dock-status", "把图片/视频连线到节点插座即可在此看到引用"));
    scroll.appendChild(strip);

    if (textField) {
        const promptBox = el("textarea", "ariadne-dock-input");
        promptBox.rows = 4;
        promptBox.placeholder = noteMode ? "追加约束（会拼进保真提示词，可留空）…" : "描述你想生成的画面…";
        promptBox.value = String(widgetValue(node, textField) || "");
        promptBox.addEventListener("change", () => setWidgetValue(node, textField, promptBox.value));
        scroll.appendChild(promptBox);
        scroll.appendChild(el("div", "ariadne-dock-note", noteMode ? "提示词由保真模板生成，这里只追加约束；模式/画幅/质量在节点本体调整" : ""));
    } else {
        scroll.appendChild(el("div", "ariadne-dock-note", "参数在节点本体调整"));
    }

    if (state.note) scroll.appendChild(el("div", "ariadne-dock-note", state.note));

    // 底栏：状态 + 生成（只跑本节点，与 Seedance 版同款部分执行）
    const bar = el("div", "ariadne-dock-bar");
    const generate = el("button", "ariadne-dock-generate", "生成 ▲");
    generate.type = "button";
    generate.title = "只提交当前节点（含上游依赖）到 ComfyUI 队列；按量计费，弹确认后才会提交";
    generate.addEventListener("click", () => {
        const ok = window.confirm("只提交当前这个节点（含上游依赖）到 ComfyUI 队列，图里其他节点不会运行。\n按量计费的真实生成。确认提交？");
        if (!ok) return;
        trackQueueResult(node, app.queuePrompt(0, 1, { queueNodeIds: [node.id] }));
    });
    bar.appendChild(generate);
    page.append(scroll, bar);
    els.body.appendChild(page);
}

function renderCreatePage() {
    const node = state.node;
    // 视频家族其他节点（Veo/可灵/Omni/一瞬入画）：轻量创作台，参数仍在节点本体。
    // 此分发不可删——否则他们会打开 Seedance 富面板，模式页签会把 Seedance 取值写进别家 task_type。
    if (String(node.type) !== SEEDANCE_TYPE && String(node.type) !== SEEDANCE_FREE_TYPE) {
        return renderGenericCreatePage(node);
    }
    const page = el("div", "ariadne-dock-page");
    const scroll = el("div", "ariadne-dock-scroll ariadne-dock-create");

    // 模式页签（胶囊容器；约束说明在悬停；素材不满足时禁用并给原因——原版同款拦截）
    const mode = modeOf(node);
    const assets = collectAssets(node);
    const modeWrap = el("div", "ariadne-pills ariadne-pills-modes");
    modeWrap.title = "切换只改变显示与锁定规则，不抹掉已填参数";
    // 自由引用版没有首帧/尾帧/动作插座，保留 全能参考/文生视频/多模态参考 三类模式
    const freeNode = String(node.type) === SEEDANCE_FREE_TYPE;
    const modes = freeNode
        ? [...MODES.filter((item) => item.key === "auto" || item.key === "text"),
           { key: "reference", label: "多模态参考", widget: "reference(多模态参考)" }]
        : MODES;
    // 多模态参考在 modeOf 里归入全能参考展示，需按 task_type 原值判定选中态
    const isReference = String(widgetValue(node, "task_type") || "").startsWith("reference");
    for (const item of modes) {
        const reason = modeDisabledReason(item.key, node, assets);
        const pill = el("button", "ariadne-pill ariadne-pill-mode", item.label);
        pill.type = "button";
        const active = freeNode && item.key === "reference" ? isReference : item.key === mode && !isReference;
        pill.classList.toggle("active", active);
        pill.setAttribute("aria-pressed", String(active));
        pill.title = reason || MODE_LIMITS[item.key] || "";
        if (reason) {
            pill.disabled = true;
            pill.classList.add("blocked");
        }
        pill.addEventListener("click", () => {
            setWidgetValue(node, "task_type", item.widget);
            normalizeAspectLock(node);  // 锁定模式自动写自适应（解锁时在渲染处还原）
            render();
        });
        modeWrap.appendChild(pill);
    }
    scroll.appendChild(modeWrap);

    // 素材条：上传芯片在前、连线芯片接后（= 提交时的编号顺序）；芯片悬停出大预览+操作。
    // 组文字标签按用户要求移除（2026-09-14），编号契约说明保留在容器悬停提示里。
    const tileAssets = assets.filter((asset) => asset.source === "tile");
    const socketAssets = assets.filter((asset) => asset.source === "socket");
    const strip = el("div", "ariadne-dock-strip");
    // 素材全走管道化（2026-09-14 用户要求）：上传入口（＋）已移除，图片/视频/音频一律从画布连线接入
    strip.title = "素材全走连线：LoadImage/LoadVideo/LoadAudio 连到对应插座即可；提交时连线素材先编号（上传裁剪产物排后），提示词引用以芯片 @编号为准";
    for (const asset of tileAssets) strip.appendChild(assetChip(node, asset));
    for (const asset of socketAssets) strip.appendChild(assetChip(node, asset));
    scroll.appendChild(strip);

    // 提示词：行内胶囊编辑（无边框；@ 唤出选单；输入即渲染胶囊）
    scroll.appendChild(makePromptEditor(node));

    if (state.note) scroll.appendChild(el("div", "ariadne-dock-note", state.note));

    // 单行底栏（常驻）：参数摘要｜✧｜状态▾历史｜有声/尾帧/裁剪｜价格+生成
    const bar = el("div", "ariadne-dock-bar");
    const paramsCol = el("div", "ariadne-dock-paramscol");
    const summary = el("button", "ariadne-dock-plainbtn ariadne-dock-params");
    summary.type = "button";
    summary.setAttribute("aria-label", "打开参数设置");
    summary.title = "分辨率 / 时长 / 有声 / 画幅——点按进入参数设置";
    summary.addEventListener("click", () => { state.page = "params"; render(); });
    const channelLine = el("span", "ariadne-dock-channel", String(widgetValue(node, "channel") || "").startsWith("kie") ? "Kie" : "火山方舟");
    paramsCol.append(summary, channelLine);
    bar.appendChild(paramsCol);
    // ✧优化 + 状态 归拢一组（原版同款：✧ 紧贴状态文字，与摘要首行对齐）
    const statusCluster = el("div", "ariadne-dock-statuscluster");
    const optimizeIcon = el("button", "ariadne-dock-plainbtn ariadne-dock-opticon", state.running ? "✦" : "✧");
    optimizeIcon.type = "button";
    optimizeIcon.setAttribute("aria-label", "AI 优化提示词");
    optimizeIcon.title = state.running ? "优化中，点击停止（保留已生成部分）" : "AI 优化：按节点技能直接生成优化后文案（流式写入提示词）";
    optimizeIcon.classList.toggle("pending", state.running);
    optimizeIcon.addEventListener("click", () => {
        if (state.running) stopDirectOptimize();
        else runDirectOptimize();
    });
    statusCluster.appendChild(optimizeIcon);
    const statusSpan = el("span", "ariadne-dock-status", state.note || prop(node, "statusText", "") || "未开始");
    els.statusSpan = statusSpan;
    statusCluster.appendChild(statusSpan);
    bar.appendChild(statusCluster);

    const right = el("div", "ariadne-dock-barright");
    right.appendChild(makeToggle(node, "generate_audio", "有声", "生成视频音频（有声/无声）"));
    right.appendChild(makeToggle(node, "return_last_frame", "尾帧", "额外返回尾帧图（仅 Kie 渠道支持）"));
    // 裁剪入口已收进素材芯片的悬停预览浮层（2026-09-14 用户要求：底栏不再放 ✂）

    bar.appendChild(right);


    // 价格 + 生成（圆钮）
    const generate = el("button", "ariadne-dock-generate");
    generate.type = "button";
    generate.setAttribute("aria-label", "提交生成队列（付费，需确认）");
    generate.title = "只提交当前节点（含上游依赖）到 ComfyUI 队列——图里其他节点不运行；方舟/Kie 按量计费，弹确认后才会提交；估价以账单为准";
    const price = el("span", "ariadne-dock-price", "¥ --");
    generate.appendChild(price);
    const knob = el("span", "ariadne-dock-priceknob");
    knob.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.6" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"/></svg>`;
    generate.appendChild(knob);
    generate.addEventListener("click", () => {
        const ok = window.confirm("只提交当前这个节点（含上游依赖）到 ComfyUI 队列，图里其他节点不会运行。\n方舟/Kie 为按量计费的真实生成。确认提交？");
        if (!ok) return;
        // 整图队列会把工作流里所有 Seedance 节点一起跑一起计费（实测）；新前端支持按节点部分执行。
        trackQueueResult(node, app.queuePrompt(0, 1, { queueNodeIds: [node.id] }));
    });
    bar.appendChild(generate);

    updateParamsSummary(summary, node);
    updateEstimate(price, generate, node);

    page.append(scroll, bar);
    els.body.appendChild(page);
}

function persistStatus(node, text) {
    setProp(node, "statusText", text);
    if (state.node === node) state.note = text;  // 只刷新当前打开面板的节点，避免串台
}

// 提交后盯结果：用户只看结论（✅出片文件名 / ❌人话失败原因），不看堆栈。
function trackQueueResult(node, submitted) {
    persistStatus(node, "已提交，生成中…");
    render();
    Promise.resolve(submitted)
        .then((res) => {
            const pid = res?.prompt_id ?? res?.data?.prompt_id ?? null;
            if (!pid) {
                persistStatus(node, "已提交队列（未能取回任务号，结果看队列面板）");
                render();
                return;
            }
            pollHistory(node, pid);
        })
        .catch(() => {
            persistStatus(node, "提交失败（详情看队列面板）");
            render();
        });
}

// 只刷新状态行文本并按节点记忆，不做整面板重绘——整面板 render 会打断输入法组词与焦点。
// textContent 单行写入开销可忽略；状态行不存在（如参数页）时静默跳过，回创作页随 render 带出。
function updateNoteText(node, text) {
    persistStatus(node, text);
    if (isPanelMounted(node) && state.node === node && state.page === "create") {
        const noteEl = els.body.querySelector(".ariadne-dock-note");
        if (noteEl) noteEl.textContent = text;
    }
}

async function pollHistory(node, pid, timeoutMs = 45 * 60000) {
    const deadline = Date.now() + timeoutMs;
    let tick = 0;
    while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        tick += 1;
        let entry = null;
        try {
            entry = (await (await fetch(`/history/${pid}`)).json())[pid] || null;
        } catch { /* 网络抖动继续等 */ }
        if (entry) {
            updateNoteText(node, humanizeExecutionResult(entry));
            return;
        }
        // Kie 渠道大文件上传可能要几分钟：有进度就显示「上传素材中 X%」，不再干等黑箱
        if (tick % 3 === 0) {
            try {
                const progress = (await (await fetch("/ariadne/kie_upload_progress")).json()).progress || {};
                const info = progress[String(node.id)];
                if (info && info.total) {
                    const pct = Math.min(100, Math.round((info.sent / info.total) * 100));
                    const sent = (info.sent / 1048576).toFixed(1);
                    const total = (info.total / 1048576).toFixed(1);
                    updateNoteText(node, `上传素材中 ${pct}%（${sent}/${total}MB）…`);
                }
            } catch { /* 进度查询失败不影响结果轮询 */ }
        }
    }
    updateNoteText(node, "生成时间较长（已监控 45 分钟），结果以队列面板为准");
}

// 裁剪目标解析：优先上传的视频瓦片；否则取连线动作视频上游的源文件名
// （LoadVideo 类节点把文件名放在 widget 里，/view 可直接读 input 目录）。
function resolveTrimTarget(node) {
    const videoTiles = tilesOf(node).filter((tile) => tile.kind === "video");
    if (videoTiles.length) return videoTiles[0];
    const index = (node.inputs || []).findIndex((input) => input.name === "motion_video");
    if (index >= 0 && isInputConnected(node, "motion_video")) {
        let upstream = null;
        try {
            upstream = node.getInputNode(index);
        } catch {
            return null;
        }
        for (const w of upstream?.widgets || []) {
            const value = typeof w.value === "string" ? w.value : "";
            if (/\.(mp4|mov|webm|mkv|m4v|avi)$/i.test(value)) {
                return { name: value, subfolder: "", kind: "video", role: "motion", seconds: 0, __fromSocket: true };
            }
        }
    }
    return null;
}

// 模式拦截（原版同款）：素材条件不满足时禁用页签并给原因。
function modeDisabledReason(mode, node, assets) {
    const hasVideo = assets.some((asset) => asset.kind === "video");
    const images = assets.filter((asset) => asset.kind === "image").length;
    const tileRole = (role) => assets.some((asset) => asset.source === "tile" && asset.role === role);
    const socketLinked = (input) => isInputConnected(node, input);
    const kieChannel = String(widgetValue(node, "channel") || "").startsWith("kie");
    switch (mode) {
        case "text":
            return assets.length ? "文生视频不带参考素材；当前已有素材，请先移除或断开" : null;
        case "edit":
            if (kieChannel) return "Kie 渠道暂不支持视频编辑，请切回火山方舟";
            return hasVideo ? null : "视频编辑需要 1 段视频素材（上传或连接动作参考视频）";
        case "extend":
            if (kieChannel) return "Kie 渠道暂不支持视频延长，请切回火山方舟";
            return hasVideo ? null : "视频延长需要 1 段视频素材（上传或连接原视频）";
        case "first-frame":
            return (socketLinked("first_frame") || tileRole("first-frame") || images >= 1)
                ? null
                : "首帧（图生视频）需要 1 张图片作首帧：连接首帧插座或上传图片";
        case "first-last":
            return ((socketLinked("first_frame") || tileRole("first-frame") || images >= 1)
                && (socketLinked("last_frame") || tileRole("last-frame") || images >= 2))
                ? null
                : "首尾帧需要首帧 + 尾帧共 2 张图片";
        default:
            return null;
    }
}

function makeToggle(node, widgetName, label, title) {
    const on = Boolean(widgetValue(node, widgetName));
    const pill = el("button", "ariadne-pill ariadne-dock-minitoggle", `● ${label}`);
    pill.type = "button";
    pill.classList.toggle("active", on);
    pill.setAttribute("aria-pressed", String(on));
    pill.setAttribute("aria-label", title);
    pill.title = title;
    pill.addEventListener("click", () => {
        setWidgetValue(node, widgetName, !widgetValue(node, widgetName));
        render();
    });
    return pill;
}

function updateParamsSummary(target, node) {
    const duration = Number(widgetValue(node, "duration"));
    target.textContent = `${widgetValue(node, "resolution")} / ${duration === -1 ? "自适应" : `${duration}秒`} / ${widgetValue(node, "generate_audio") ? "有声" : "无声"} / ${widgetValue(node, "aspect_ratio") === "adaptive" ? "自适应" : widgetValue(node, "aspect_ratio")}`;
}

async function updateEstimate(priceEl, generateEl, node) {
    const tiles = tilesOf(node);
    const channel = String(widgetValue(node, "channel") || "ark").startsWith("kie") ? "kie" : "ark";
    const includesVideo = Boolean(node.getInputNode?.(node.inputs?.findIndex?.((i) => i.name === "motion_video") ?? -1)) || tiles.some((tile) => tile.kind === "video");
    const inputSeconds = tiles.filter((tile) => tile.kind === "video").reduce((sum, tile) => sum + Number(tile.seconds || 0), 0);
    try {
        const response = await fetch("/ariadne/estimate", {
            method: "POST", headers: { "content-type": "application/json" },
            body: JSON.stringify({
                channel, resolution: widgetValue(node, "resolution"),
                duration: Number(widgetValue(node, "duration") ?? 0),
                includesVideoInput: includesVideo, inputVideoSeconds: inputSeconds,
            }),
        });
        const data = await response.json();
        if (state.node !== node) return;
        state.estimate = data.estimate || null;
        const estimateValue = data.estimate;
        priceEl.textContent = !estimateValue
            ? "¥ --"
            : `¥${(estimateValue.cny ?? 0).toFixed(3)}`;
        generateEl.title = !estimateValue
            ? "该档位/自适应时长无法估算，以账单为准；提交前会再次确认"
            : estimateValue.unit === "credits"
                ? `Kie 预估 ≈${estimateValue.credits} credits ≈ ¥${estimateValue.cny}；输入时长未计全时偏低，以账单为准`
                : `方舟刊例预估 ≈¥${estimateValue.cny}；以账单为准`;
    } catch {
        priceEl.textContent = "¥ --";
    }
}

// ---------- 素材芯片（52px 缩略 + @标签；悬停出大预览+操作浮层） ----------

function assetChip(node, asset) {
    const chip = el("button", "ariadne-dock-chip");
    chip.type = "button";
    const label = `@${asset.label}`;
    chip.title = asset.source === "socket"
        ? `连线素材：${KIND_LABEL[asset.kind]}·${ROLE_LABEL[asset.role]}；点击插入 ${label}，悬停看大图与操作`
        : `点击插入 ${label}；悬停看大图与操作（职责/锁定/裁剪/移除）`;
    if (asset.source === "tile") {
        const tile = asset.tile;
        const thumb = el("span", "ariadne-dock-chipthumb");
        if (asset.kind === "image") {
            const img = el("img");
            img.src = viewUrl(tile);
            img.alt = "";
            img.draggable = false;
            thumb.appendChild(img);
        } else if (asset.kind === "video") {
            const video = el("video");
            video.src = viewUrl(tile);
            video.muted = true;
            video.preload = "metadata";
            thumb.appendChild(video);
        } else {
            thumb.appendChild(el("span", "ariadne-dock-chipicon", "♫"));
        }
        chip.appendChild(thumb);
        if (tile.trimmed) chip.classList.add("trimmed");
        if (tile.locked) chip.classList.add("locked");
        // 拖动排序：拖到目标瓦片上放下 = 排到它前面（顺序即提交时的编号顺序）。
        chip.addEventListener("dragover", (event) => {
            if (!state.dragTileKey || state.dragTileKey === tileKey(tile)) return;
            event.preventDefault();
            event.stopPropagation();
            event.dataTransfer.dropEffect = "move";
            chip.classList.add("drop-target");
        });
        chip.addEventListener("dragleave", () => chip.classList.remove("drop-target"));
        chip.addEventListener("drop", (event) => {
            event.preventDefault();
            event.stopPropagation();
            chip.classList.remove("drop-target");
            const from = state.dragTileKey;
            state.dragTileKey = "";
            if (!from || from === tileKey(tile)) return;
            const tiles = tilesOf(node);
            const fromIndex = tiles.findIndex((item) => tileKey(item) === from);
            const toIndex = tiles.findIndex((item) => tileKey(item) === tileKey(tile));
            if (fromIndex < 0 || toIndex < 0) return;
            const [moved] = tiles.splice(fromIndex, 1);
            tiles.splice(toIndex, 0, moved);
            commitTiles(node, tiles);
            render();
        });
    } else {
        chip.classList.add("socket");
        const preview = asset.leaf?.node ? previewFromUpstream(asset.leaf.node) : upstreamPreview(node, asset.input);
        if (preview.url) {
            let mediaEl;
            if (preview.isVideo) {
                mediaEl = el("video");
                mediaEl.muted = true;
                mediaEl.preload = "metadata";
            } else {
                mediaEl = el("img");
                mediaEl.alt = "";
                mediaEl.draggable = false;
            }
            mediaEl.src = preview.url;
            const thumb = el("span", "ariadne-dock-chipthumb");
            thumb.appendChild(mediaEl);
            chip.appendChild(thumb);
        } else {
            chip.appendChild(el("span", "ariadne-dock-chipicon", asset.kind === "video" ? "▶" : asset.kind === "audio" ? "♫" : "▧"));
        }
    }
    const tag = el("span", "ariadne-dock-chiptag", label);
    chip.appendChild(tag);

    // 所有芯片都可拖动：拖进提示词 = 插入 @引用；瓦片之间互拖 = 排序（见上方 tile 分支）。
    chip.draggable = true;
    chip.addEventListener("dragstart", (event) => {
        if (asset.source === "tile") state.dragTileKey = tileKey(asset.tile);
        event.dataTransfer.effectAllowed = "copyMove";
        event.dataTransfer.setData("text/plain", `@${asset.label} `);
        chip.classList.add("dragging");
    });
    chip.addEventListener("dragend", () => {
        state.dragTileKey = "";
        chip.classList.remove("dragging");
    });

    chip.addEventListener("click", () => {
        insertAtCursor(els.promptEditor, `${label} `);
    });
    attachChipPopover(chip, node, asset);
    return chip;
}

// 悬停大预览浮层：大图/视频 + 底部操作行（插入/职责/锁定/裁剪/断开/移除）。
function attachChipPopover(chip, node, asset) {
    let pop = null;
    let hideTimer = null;
    const close = () => {
        if (pop) { pop.remove(); pop = null; }
    };
    const scheduleClose = () => {
        if (hideTimer) clearTimeout(hideTimer);
        hideTimer = setTimeout(close, 200);
    };
    const cancelClose = () => {
        if (hideTimer) clearTimeout(hideTimer);
        hideTimer = null;
    };
    const open = () => {
        if (pop) return;
        pop = el("div", "ariadne-dock-preview");
        const mediaBox = el("div", "ariadne-dock-preview-media");
        if (asset.source === "tile") {
            const tile = asset.tile;
            if (asset.kind === "image") {
                const img = el("img");
                img.src = viewUrl(tile);
                mediaBox.appendChild(img);
            } else if (asset.kind === "video") {
                const video = el("video");
                video.src = viewUrl(tile);
                video.muted = true;
                video.playsInline = true;
                video.autoplay = true;
                video.loop = true;
                mediaBox.appendChild(video);
            } else {
                mediaBox.appendChild(el("span", "ariadne-dock-chipicon", "♫"));
            }
        } else {
            const preview = asset.leaf?.node ? previewFromUpstream(asset.leaf.node) : upstreamPreview(node, asset.input);
            if (preview.url && preview.isVideo) {
                const video = el("video");
                video.src = preview.url;
                video.muted = true;
                video.playsInline = true;
                video.autoplay = true;
                video.loop = true;
                mediaBox.appendChild(video);
            } else if (preview.url) {
                const img = el("img");
                img.src = preview.url;
                mediaBox.appendChild(img);
            } else {
                mediaBox.appendChild(el("span", "ariadne-dock-chipicon", asset.kind === "video" ? "▶" : asset.kind === "audio" ? "♫" : "▧"));
            }
        }
        pop.appendChild(mediaBox);
        // 媒体框跟随素材真实宽高比（在 360×276 内等比取最大，水平居中），元数据到达前保持默认框
        const media = mediaBox.querySelector("img,video");
        if (media) {
            const fit = (w, h) => {
                if (!w || !h) return;
                const scale = Math.min(360 / w, 276 / h);
                mediaBox.style.width = `${Math.max(1, Math.round(w * scale))}px`;
                mediaBox.style.height = `${Math.max(1, Math.round(h * scale))}px`;
                mediaBox.style.margin = "0 auto";
            };
            if (media.tagName === "VIDEO") {
                if (media.videoWidth && media.videoHeight) fit(media.videoWidth, media.videoHeight);
                else media.addEventListener("loadedmetadata", () => fit(media.videoWidth, media.videoHeight), { once: true });
            } else if (media.naturalWidth && media.naturalHeight) {
                fit(media.naturalWidth, media.naturalHeight);
            } else {
                media.addEventListener("load", () => fit(media.naturalWidth, media.naturalHeight), { once: true });
            }
        }
        const actions = el("div", "ariadne-dock-preview-actions");
        const addAction = (label, fn, extraTitle) => {
            const item = el("button", "ariadne-dock-mini", label);
            item.type = "button";
            if (extraTitle) item.title = extraTitle;
            item.addEventListener("click", () => { close(); fn(); });
            actions.appendChild(item);
        };
        addAction(`插入 @${asset.label}`, () => insertAtCursor(els.promptEditor, `@${asset.label} `));
        if (asset.source === "tile") {
            const tile = asset.tile;
            addAction(`职责→${nextLabel(tile.role)}`, () => {
                const tiles = tilesOf(node);
                const target = tiles.find((item) => tileKey(item) === tileKey(tile));
                if (target) target.role = nextRole(target.role);
                commitTiles(node, tiles);
                render();
            }, "切换素材职责（影响素材职责句编译）");
            if (["character", "wardrobe"].includes(tile.role)) {
                addAction(tile.locked ? "解锁" : "🔒锁定", () => {
                    const tiles = tilesOf(node);
                    const target = tiles.find((item) => tileKey(item) === tileKey(tile));
                    if (target) target.locked = !target.locked;
                    commitTiles(node, tiles);
                    render();
                }, "身份资产锁定：跨镜头复用标记（仅本节点创作状态，不影响后端契约）");
            }
            if (asset.kind === "video") {
                addAction("✂ 裁剪", () => openTrimDialog(node, tile, () => render()), "裁剪省钱：参考视频比输出长的部分全是白付的输入时长");
            }
            addAction("移除", () => {
                commitTiles(node, tilesOf(node).filter((item) => tileKey(item) !== tileKey(tile)));
                render();
            }, "从节点移除该素材");
        } else {
            // 连线视频 = 管道化的参考视频，裁剪入口在这里（视频已不走上传）
            if (asset.kind === "video") {
                const trimTarget = resolveTrimTarget(node);
                if (trimTarget) {
                    addAction("✂ 裁剪", () => openTrimDialog(node, trimTarget, () => render()), "裁剪省钱：参考视频比输出长的部分全是白付的输入时长");
                }
            }
            addAction("断开连线", () => {
                const inputIndex = (node.inputs || []).findIndex((input) => input.name === asset.input);
                if (inputIndex >= 0) node.disconnectInput(inputIndex);
                app.canvas?.setDirtyCanvas?.(true, true);
                render();
            }, "断开画布连线（卡片随之消失）");
        }
        pop.appendChild(actions);
        document.body.appendChild(pop);
        // 浮层自身可悬停保持：鼠标从芯片移向浮层时不关闭
        pop.addEventListener("mouseenter", cancelClose);
        pop.addEventListener("mouseleave", scheduleClose);
        const rect = chip.getBoundingClientRect();
        const popWidth = pop.offsetWidth || 260;
        const popHeight = pop.offsetHeight || 260;
        pop.style.left = `${Math.max(8, Math.min(rect.left + rect.width / 2 - popWidth / 2, window.innerWidth - popWidth - 8))}px`;
        pop.style.top = `${Math.max(8, rect.top - popHeight - 8)}px`;
    };
    chip.addEventListener("mouseenter", () => { cancelClose(); open(); });
    chip.addEventListener("mouseleave", scheduleClose);
}

function nextLabel(role) {
    return ROLE_LABEL[nextRole(role)] || nextRole(role);
}

// 行内插入（光标处；@紧邻时先吞掉防双前缀）。
function insertAtCursor(editor, text) {
    if (!editor) return;
    editor.focus();
    editor.insertAtCursorText(text);
}

// ---------- 行内胶囊提示词编辑器 ----------

function makePromptEditor(node) {
    const editor = el("div", "ariadne-dock-promptline");
    editor.contentEditable = "true";
    editor.spellcheck = false;
    editor.dataset.placeholder = "描述你想要生成的内容；@ 引用素材，素材职责按角色自动编译";
    editor.setAttribute("aria-label", "提示词");
    let lastValue = String(widgetValue(node, "prompt") || "");
    // 胶囊标签用 collectAssets（瓦片+插座素材并集）：纯插座会话（如首尾帧连 LoadImage）没有瓦片，
    // 只认 cachedTiles 会让优化文案的 @图片1 连带正文整段包进胶囊。
    const render = (text) => renderPromptChips(editor, String(text ?? ""), collectAssets(node));
    const getValue = () => editor.innerText.replace(/\u00a0/g, " ");
    editor.getValue = getValue;
    editor.setValue = (value) => {
        lastValue = String(value ?? "");
        render(lastValue);
    };
    editor.insertAtCursorText = (text) => {
        editor.focus();
        const selection = window.getSelection();
        if (!selection.rangeCount || !editor.contains(selection.getRangeAt(0).startContainer)) {
            editor.appendChild(document.createTextNode(text));
        } else {
            const range = selection.getRangeAt(0);
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
        }
        editor.dispatchEvent(new Event("input", { bubbles: true }));
    };
    // 组词守卫：拼音组词过程中的 input 事件只存值、不重渲染胶囊——重绘会打断输入法
    //（中文输入被打断的根因，2026-09-14）；compositionend 后再做一次完整渲染。
    let composing = false;
    const handleInput = () => {
        const text = getValue();
        lastValue = text;  // 同步对照值：否则 blur 空读保护会用旧值复活已删除的内容
        setWidgetValue(node, "prompt", text);
        if (composing) return;
        // 输入即渲染胶囊（@标签完成瞬间变胶囊）；保留光标位置防跳字
        const caret = caretOffsetIn(editor);
        render(text);
        if (caret !== null) placeCaretOffset(editor, Math.min(caret, text.length));
    };
    editor.addEventListener("compositionstart", () => { composing = true; });
    editor.addEventListener("compositionend", () => {
        composing = false;
        handleInput();
    });
    editor.addEventListener("input", handleInput);
    // 芯片可拖进提示词：drop 处按落点插入 @引用
    editor.addEventListener("dragover", (event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
    });
    editor.addEventListener("drop", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const text = event.dataTransfer?.getData("text/plain") || "";
        if (!text.startsWith("@")) return;
        const range = document.caretRangeFromPoint?.(event.clientX, event.clientY);
        if (range && editor.contains(range.startContainer)) {
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
        }
        editor.insertAtCursorText(`${text.trim()} `);
    });
    editor.addEventListener("keydown", (event) => {
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (event.key === "@") setTimeout(() => openAssetMenu(node, editor), 0);
        event.stopPropagation();
    });
    editor.addEventListener("blur", () => {
        const current = getValue();
        if (!current.trim() && lastValue.trim()) {
            // 空读保护：编辑器空而最近值非空 → 回滚显示并写回节点，避免序列化拿到空串
            render(lastValue);
            setWidgetValue(node, "prompt", lastValue);
        }
    });
    render(lastValue);
    els.promptEditor = editor;
    return editor;
}

function openAssetMenu(node, editor) {
    const assets = collectAssets(node);
    const menu = document.createElement("div");
    menu.className = "ariadne-menu";
    if (!assets.length) {
        menu.textContent = "还没有素材：先在素材条「＋」上传或连接插座";
    }
    for (const asset of assets) {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "ariadne-menu-item";
        item.textContent = `@${asset.label}（${ROLE_LABEL[asset.role] || asset.role}）`;
        item.addEventListener("click", () => {
            editor.insertAtCursorText(`@${asset.label} `);
            menu.remove();
            document.removeEventListener("mousedown", dismiss, true);
        });
        menu.appendChild(item);
    }
    document.body.appendChild(menu);
    const rect = editor.getBoundingClientRect();
    menu.style.left = `${Math.min(rect.left, window.innerWidth - 320)}px`;
    menu.style.top = `${Math.min(rect.bottom + 4, window.innerHeight - 200)}px`;
    const dismiss = (event) => {
        if (!menu.contains(event.target)) {
            menu.remove();
            document.removeEventListener("mousedown", dismiss, true);
        }
    };
    setTimeout(() => document.addEventListener("mousedown", dismiss, true), 0);
}

// ---------- 直接优化：✧ 一键生成，文案流式写进提示词 ----------

// 点击 ✧：空闲则开始优化（流式直接改写提示词）；生成中再点 = 停止（保留已生成部分）。
async function runDirectOptimize() {
    const node = state.node;
    if (!node || state.running) return;
    const promptText = String(widgetValue(node, "prompt") || "").trim();
    if (!promptText) { state.note = "请先填写原始提示词"; render(); return; }
    if (state.optimizerConfigured === false) {
        state.note = "优化器未配置：请在侧栏「Ariadne 设置」填写站点/模型/Key";
        render();
        return;
    }
    const assets = collectAssets(node);
    const userContent = buildOptimizerUserContent({
        taskType: modeOf(node), prompt: promptText,
        assets: assets.map((asset) => ({ kind: asset.kind, role: asset.role, label: asset.label })),
        duration: Number(widgetValue(node, "duration") ?? 10),
        resolution: String(widgetValue(node, "resolution") || "720p"),
        aspectRatio: String(widgetValue(node, "aspect_ratio") || "9:16"),
        generateAudio: Boolean(widgetValue(node, "generate_audio")),
    });
    const controller = new AbortController();
    state.abort = controller;
    state.running = true;
    state.streamText = "";
    persistStatus(node, "优化中…");
    updateStatusUI("优化中…");
    try {
        const finalText = await runOptimizer(userContent, {
            signal: controller.signal,
            skill: skillForNode(node),
            onDelta: (text) => {
                state.streamText = text;
                // 直接流式写进提示词：节点胶囊与面板编辑器即时刷新
                setWidgetValue(node, "prompt", text);
                if (els.promptEditor) els.promptEditor.setValue(text);
                updateStatusUI("优化中…");
            },
        });
        state.running = false;
        if (finalText.trim()) {
            persistStatus(node, "已生成优化文案");
            state.note = "";
        } else {
            persistStatus(node, "模型未返回内容");
            state.note = "模型未返回内容";
        }
    } catch (error) {
        state.running = false;
        const aborted = controller.signal.aborted;
        const message = String(error?.message || error).slice(0, 180);
        // 直接写模式下已生成部分本就在提示词里，中断即保留
        persistStatus(node, aborted ? "已停止优化" : `优化失败：${message}`);
        state.note = aborted ? "已停止优化" : `优化失败：${message}`;
    }
    render();
}

function stopDirectOptimize() {
    state.abort?.abort();
}

function updateStatusUI(text) {
    state.note = text;  // 底栏已精简无状态位：重进面板时经 render 的 state.note 显示
}

// ---------- 输出参数页 ----------

function pillGroup(options, current, onPick, disabledKey, disabledTitle) {
    const wrap = el("div", "ariadne-pills");
    for (const [key, label] of options) {
        const pill = el("button", "ariadne-pill", label);
        pill.type = "button";
        pill.dataset.value = key;
        pill.setAttribute("aria-pressed", String(key === current));
        pill.classList.toggle("active", key === current);
        if (disabledKey && disabledKey(key)) {
            pill.disabled = true;
            pill.title = disabledTitle || "当前任务模式自动锁定该参数（画幅/时长跟随素材）";
        }
        pill.addEventListener("click", () => {
            if (pill.disabled) return;
            onPick(key);
            render();
        });
        wrap.appendChild(pill);
    }
    return wrap;
}

function fieldLabel(text, note) {
    const label = el("div", "ariadne-dock-fieldlabel");
    label.append(el("span", "", text));
    if (note) {
        const hint = el("span", "ariadne-dock-fieldnote", note);
        label.appendChild(hint);
    }
    return label;
}

// ---------- 输出参数页（一级页面；左下角参数摘要点击进入） ----------
const RATIO_SHAPE = { "9:16": [17, 30], "1:1": [25, 25], "3:4": [22, 29], "16:9": [33, 19], "4:3": [27, 20], "21:9": [36, 15], adaptive: [28, 19] };

function renderParamsPage() {
    const node = state.node;
    const page = el("div", "ariadne-dock-page");
    const scroll = el("div", "ariadne-dock-scroll ariadne-dock-params-page");
    normalizeAspectLock(node);  // 幂等自愈：载入即锁定模式但画幅仍是具体值时，改写为自适应
    const rules = modeRules(modeOf(node));
    const aspectLocked = rules.lockAspect;
    const duration = Number(widgetValue(node, "duration"));

    // 三列均匀网格：分辨率+时长 ｜ 画幅 ｜ 渠道+格式+保存文件夹（列内控件拉伸铺满列宽）
    const grid = el("div", "ariadne-dock-pgrid");
    const colA = el("div", "ariadne-dock-pcol");
    colA.appendChild(fieldLabel("分辨率"));
    colA.appendChild(pillGroup([["480p", "480p"], ["720p", "720p"], ["1080p", "1080p"]], String(widgetValue(node, "resolution")), (key) => setWidgetValue(node, "resolution", key)));
    // 上下对称弹性空隙：生成时长落在列内居中偏下（贴底过深，回半程）
    colA.appendChild(el("div", "ariadne-dock-colspacer"));
    colA.appendChild(fieldLabel("生成时长", rules.lockDuration ? "编辑/延长自动锁定为自适应" : "4-30 秒"));
    const durationRow = el("div", "ariadne-dock-slider");
    const slider = el("input");
    slider.type = "range";
    slider.min = "4";
    slider.max = "30";
    slider.step = "1";
    slider.value = String(duration === -1 ? 10 : duration);
    slider.disabled = rules.lockDuration;
    const durationLabel = el("span", "ariadne-dock-slider-value", rules.lockDuration ? "自动" : `${slider.value}s`);
    slider.addEventListener("input", () => {
        durationLabel.textContent = `${slider.value}s`;
        setWidgetValue(node, "duration", Number(slider.value));
    });
    durationRow.append(slider, durationLabel);
    colA.appendChild(durationRow);
    colA.appendChild(el("div", "ariadne-dock-colspacer"));
    grid.appendChild(colA);

    const colB = el("div", "ariadne-dock-pcol");
    colB.appendChild(fieldLabel("画幅", aspectLocked ? "已自动切换自适应：跟随首帧/原视频画幅" : ""));
    colB.appendChild(aspectShapeGrid(node, aspectLocked));
    grid.appendChild(colB);

    const colC = el("div", "ariadne-dock-pcol");
    colC.appendChild(fieldLabel("渠道"));
    colC.appendChild(pillGroup([["ark(火山方舟直连)", "火山方舟"], ["kie(Kie积分)", "Kie"]], String(widgetValue(node, "channel")), (key) => setWidgetValue(node, "channel", key)));
    colC.appendChild(fieldLabel("格式"));
    colC.appendChild(pillGroup([["mp4", "mp4"], ["mov", "mov"]], String(widgetValue(node, "output_format")), (key) => setWidgetValue(node, "output_format", key)));

    // 保存文件夹挂在格式下方（填住列底空位）：点它弹系统选目录框；未选时自动落盘到默认目录
    const folderNow = String(widgetValue(node, "download_folder") || "默认 output/ariadne");
    colC.appendChild(fieldLabel("保存文件夹"));
    const folderBtn = el("button", "ariadne-dock-linebtn", "选择…");
    folderBtn.type = "button";
    folderBtn.title = `当前：${folderNow}\n点按打开系统文件夹选择对话框更换`;
    folderBtn.addEventListener("click", async () => {
        folderBtn.disabled = true;
        try {
            const response = await fetch("/kie/select_folder", { method: "POST" });
            const data = await response.json();
            if (data.folder) {
                setWidgetValue(node, "download_folder", data.folder);
                folderBtn.title = `当前：${data.folder}\n点按可再次更换`;
            }
        } catch {
            folderBtn.title = "本机未提供文件夹选择路由（需 ComfyUI-Kie），路径可在工作流 JSON 中修改";
        }
        folderBtn.disabled = false;
    });
    colC.appendChild(folderBtn);

    // 打开素材文件夹：上传的原始文件都在 input/ariadne/ 下，一键在资源管理器里打开（可手动清理）
    const openAssetsBtn = el("button", "ariadne-dock-linebtn", "打开素材文件夹");
    openAssetsBtn.type = "button";
    openAssetsBtn.title = "在资源管理器打开素材文件夹（input/ariadne/）——上传的原始文件都在这里，可手动清理";
    openAssetsBtn.addEventListener("click", async () => {
        openAssetsBtn.disabled = true;
        try {
            const response = await fetch("/ariadne/open_assets_folder", { method: "POST" });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || `HTTP ${response.status}`);
            }
        } catch (error) {
            openAssetsBtn.title = `打开失败：${error?.message || error}`;
        }
        openAssetsBtn.disabled = false;
    });
    colC.appendChild(openAssetsBtn);
    grid.appendChild(colC);
    scroll.appendChild(grid);

    // 底栏：只有左下角摘要（同一个位置 = 返回创作出口）
    const bar = el("div", "ariadne-dock-bar");
    const paramsCol = el("div", "ariadne-dock-paramscol");
    const summary = el("button", "ariadne-dock-plainbtn ariadne-dock-params");
    summary.type = "button";
    summary.setAttribute("aria-label", "返回创作页");
    summary.title = "点按返回创作页";
    summary.addEventListener("click", () => { state.page = "create"; render(); });
    const channelLine = el("span", "ariadne-dock-channel", String(widgetValue(node, "channel") || "").startsWith("kie") ? "Kie" : "火山方舟");
    paramsCol.append(summary, channelLine);
    bar.appendChild(paramsCol);

    updateParamsSummary(summary, node);
    page.append(scroll, bar);
    els.body.appendChild(page);
}

// 画幅形状格子（上形状下名称；竖屏行 9:16/3:4/1:1，横屏行 16:9/4:3/21:9，自适应独占第三行；锁定时整组禁用）
function aspectShapeGrid(node, locked) {
    const current = String(widgetValue(node, "aspect_ratio"));
    const rows = [
        ["9:16", "3:4", "1:1"],
        ["16:9", "4:3", "21:9"],
        ["adaptive"],
    ];
    const gridEl = el("div", "ariadne-dock-aspects");
    for (const row of rows) {
        const rowEl = el("div", "ariadne-dock-aspects-row");
        for (const key of row) {
            const selected = current === key;
            const [shapeW, shapeH] = RATIO_SHAPE[key] || [20, 15];
            const cell = el("button", "ariadne-dock-aspect");
            cell.type = "button";
            cell.classList.toggle("active", selected);
            cell.disabled = locked;
            if (locked) cell.title = "当前任务模式锁定画幅（跟随首帧/原视频）";
            cell.setAttribute("aria-label", `画幅 ${key === "adaptive" ? "自适应" : key}`);
            const shape = el("span", "ariadne-dock-aspect-shape");
            shape.style.width = `${shapeW}px`;
            shape.style.height = `${shapeH}px`;
            if (key === "adaptive") shape.style.borderStyle = "dashed";
            const label = el("span", "ariadne-dock-aspect-label", key === "adaptive" ? "自适应" : key);
            cell.append(shape, label);
            cell.addEventListener("click", () => {
                if (cell.disabled) return;
                if (key !== "adaptive") setProp(node, "lastAspect", key);  // 记住手选，供锁定还原
                setWidgetValue(node, "aspect_ratio", key);
                render();
            });
            rowEl.appendChild(cell);
        }
        gridEl.appendChild(rowEl);
    }
    return gridEl;
}
