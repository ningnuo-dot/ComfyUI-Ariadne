// Ariadne 节点状态适配器（纯函数，无宿主依赖，可被 node --test 直接导入）。
// 集中处理：按名读写 widget（含 DOM widget 特例与 callback 接力）、节点 properties 存储、
// 任务模式映射、素材聚合（瓦片 + 插座）、五段式优化输入、历史去重、草稿指纹。
// 创作台/节点本体的组件层一律经此模块操作 widget 数组，禁止各处直接下标摆弄。

export const SEEDANCE_TYPE = "AriadneSeedance25Video";
export const SEEDANCE_FREE_TYPE = "AriadneSeedance25Free";

export const KIND_LABEL = { image: "图片", video: "视频", audio: "音频" };
export const ROLE_LABEL = {
    "first-frame": "首帧", "last-frame": "尾帧", character: "人物", wardrobe: "服装",
    scene: "场景", motion: "动作", audio: "音频", annotation: "标注帧", free: "自由引用",
    reference: "参考图",
};
export const ROLE_OPTIONS = Object.entries(ROLE_LABEL);

// 六种任务模式 → Python 端 task_type widget 的实际取值（标签带括号后缀）。
export const MODES = [
    { key: "auto", label: "全能参考", widget: "auto(全能参考)" },
    { key: "edit", label: "视频编辑", widget: "edit(视频编辑)" },
    { key: "text", label: "文生视频", widget: "text(文生视频)" },
    { key: "first-frame", label: "首帧", widget: "first-frame(首帧)" },
    { key: "first-last", label: "首尾帧", widget: "first-last(首尾帧)" },
    { key: "extend", label: "视频延长", widget: "extend(视频延长)" },
];

// 每种模式需要展示的插座与参数锁定规则（只控制显示/锁定，绝不改写既有值）。
export const MODE_RULES = {
    auto: { sockets: ["character_images", "wardrobe_images", "scene_images", "motion_video", "reference_audio"], lockAspect: false, lockDuration: false },
    edit: { sockets: ["motion_video"], lockAspect: true, lockDuration: true },
    text: { sockets: [], lockAspect: false, lockDuration: false },
    "first-frame": { sockets: ["first_frame"], lockAspect: true, lockDuration: false },
    "first-last": { sockets: ["first_frame", "last_frame"], lockAspect: true, lockDuration: false },
    extend: { sockets: ["motion_video"], lockAspect: true, lockDuration: true },
};

export const SOCKET_ROLE = {
    first_frame: "first-frame", last_frame: "last-frame", character_images: "character",
    wardrobe_images: "wardrobe", scene_images: "scene", motion_video: "motion", reference_audio: "audio",
    image_1: "free", image_2: "free", image_3: "free",
    reference_images: "reference", reference_image: "reference",
    scene_reference_image: "scene", reference_video: "motion",
};

export const SOCKET_KIND = {
    first_frame: "image", last_frame: "image", character_images: "image", wardrobe_images: "image",
    scene_images: "image", motion_video: "video", reference_audio: "audio",
    image_1: "image", image_2: "image", image_3: "image",
    reference_images: "image", reference_image: "image", scene_reference_image: "image",
    reference_video: "video",
};

// 允许按批量展开的插座：Python 侧 images_to_files 会把批次展开成多张分别编号。
// 首帧/尾帧语义是单张（Python 只取批次第一张），不展开——显示必须与实际提交一致。
export const SOCKET_BATCH = new Set([
    "character_images", "wardrobe_images", "scene_images", "image_1", "image_2", "image_3",
    "reference_images", "scene_reference_image",
]);

// 视频家族（创作台轻量面板 + 自动接保存节点覆盖范围）。
export const VIDEO_PANEL_TYPES = new Set([
    SEEDANCE_TYPE, SEEDANCE_FREE_TYPE, "AriadneVeo31Video", "AriadneKlingVideo",
    "AriadneOmniVideo", "AriadneOmniFirstLastFrame", "AriadneInstantPainting",
]);

function widgetMap(node) {
    const map = {};
    // 先 stash 后 widgets：同名时以 live widget 为准（stash 只是摘出的副本）。
    for (const w of node.__ariadneStashed || []) if (w.name) map[w.name] = w;
    for (const w of node.widgets || []) if (w.name) map[w.name] = w;
    return map;
}

export function widgetValue(node, name) {
    const w = widgetMap(node)[name];
    return w ? w.value : undefined;
}

// 写回 widget：直接走 value 赋值——DOM widget（提示词/素材）的 value 是带 getValue/setValue
// 的访问器，赋值即同步重绘；原生 widget 就是普通字段。callback 按新前端签名 (value, canvas, node)
// 接力，保持参数联动（费用预估等）不失效。
// 防御：若某版前端未把 options.getValue/setValue 桥接为 value 访问器（赋值后 DOM 未同步），
// 对 ariadne_prompt 显式补调 setValue（补齐 node/canvas 上下文，旧版签名需要）。
export function setWidgetValue(node, name, value) {
    const w = widgetMap(node)[name];
    if (!w) return false;
    const canvas = node.graph?.list_of_graphcanvas?.[0];
    w.value = value;
    if (w.type === "ariadne_prompt" && typeof w.getValue === "function"
        && w.getValue() !== String(value ?? "") && typeof w.setValue === "function") {
        try { w.setValue(value, { node, canvas: canvas ?? undefined }); } catch { /* 旧签名容器再试一次 */ }
    }
    if (typeof w.callback === "function") w.callback(w.value, canvas, node);
    return true;
}

// ---- 节点 properties（随工作流 JSON 序列化，Python 不感知这些键） ----
export function prop(node, key, fallback) {
    const value = node.properties?.[`ariadne.${key}`];
    return value === undefined || value === null ? fallback : value;
}

export function setProp(node, key, value) {
    if (!node.properties) node.properties = {};
    node.properties[`ariadne.${key}`] = value;
}

// ---- 素材聚合 ----
export function parseTiles(value) {
    try {
        const parsed = JSON.parse(value || "[]");
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

// 按名查插座连接状态（新前端 getInputNode 只收槽位索引，不能传名字）。
export function isInputConnected(node, inputName) {
    const index = (node.inputs || []).findIndex((input) => input.name === inputName);
    if (index < 0) return false;
    try {
        return Boolean(node.getInputNode?.(index));
    } catch {
        return false;
    }
}

export function tileKey(tile) {
    return `${tile.subfolder || ""}/${tile.name}`;
}

export function tilesOf(node) {
    return parseTiles(widgetValue(node, "ariadne_assets"));
}

export function writeTiles(node, tiles) {
    setWidgetValue(node, "ariadne_assets", JSON.stringify(tiles));
}

// 瓦片缓存：编号按 kind 计数，增删后标签会前移；对照旧缓存生成旧→新映射并改写提示词，
// 防止 @图片2 在删除 @图片1 后指向别的素材。WeakMap 按节点隔离（多 Seedance 节点不串）。
const TILES_BY_NODE = new WeakMap();

export function cachedTiles(node) {
    return TILES_BY_NODE.get(node) || [];
}

export function rewritePromptLabels(node, mapping) {
    const entries = Object.entries(mapping || {}).filter(([from, to]) => from && to && from !== to);
    if (!entries.length) return;
    const w = widgetMap(node).prompt;
    if (!w || typeof w.getValue !== "function") return;
    let text = w.getValue();
    // 两段式替换：旧标签先统一替换为占位符，再由占位符替换为新标签——
    // 交换顺序（图1↔图2）这类环映射如果直接链式 split/join 会塌缩成同一个标签。
    const placeholders = entries.map((_, i) => `\u0000ariadne${i}\u0000`);
    entries.forEach(([from], i) => { text = text.split(from).join(placeholders[i]); });
    entries.forEach(([, to], i) => { text = text.split(placeholders[i]).join(to); });
    w.value = text;
    const canvas = node.graph?.list_of_graphcanvas?.[0];
    if (typeof w.callback === "function") w.callback(text, canvas, node);
}

// 行内 @引用切分（胶囊渲染的纯逻辑核心，可被 node --test 直接测）：
// 悬空引用（未在素材清单里的编号，如模型幻觉出的 @图片3）只按「种类词+编号」形状兜底，
// 绝不吞标签后的中文正文——否则优化长句「@图片1作为首帧」会被整段包进胶囊；
// 已知标签长词在前（图片10 不被 图片1 抢占），兼容非编号的自定义标签。
export function splitPromptChips(text, labels = []) {
    const known = [...new Set((labels || []).filter(Boolean))]
        .sort((a, b) => b.length - a.length)
        .map((label) => label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
        .join("|");
    const pattern = new RegExp(`(@(?:(?:图片|视频|音频)?\\d{1,3}${known ? `|${known}` : ""}))`);
    return String(text ?? "").split(pattern);
}

// 读当前瓦片 → 重算 @标签 → 生成旧→新映射 → 改写提示词 → 写回并更新缓存。
// 调用方负责随后刷新 DOM（瓦片卡/胶囊）。
export function syncTiles(node) {
    const previous = TILES_BY_NODE.get(node) || [];
    const tiles = tilesOf(node);
    const counters = { image: 0, video: 0, audio: 0 };
    const mapping = {};
    for (const tile of tiles) {
        counters[tile.kind] = (counters[tile.kind] || 0) + 1;
        const label = `${KIND_LABEL[tile.kind] || tile.kind || "素材"}${counters[tile.kind]}`;
        const oldTile = previous.find((item) => tileKey(item) === tileKey(tile));
        if (oldTile?.label && oldTile.label !== label) mapping[oldTile.label] = label;
        tile.label = label;
    }
    writeTiles(node, tiles);
    TILES_BY_NODE.set(node, tiles);
    rewritePromptLabels(node, mapping);
    return tiles;
}

// 聚合全部素材：瓦片在前（保持面板顺序与编号契约），插座接着编；编号规则与 Python
// 端 _assign_labels 完全一致（图片/视频/音频各自独立计数）。
export function collectAssets(node) {
    const counters = { image: 0, video: 0, audio: 0 };
    const assets = [];
    for (const tile of tilesOf(node)) {
        if (!tile || !tile.name) continue;
        counters[tile.kind] = (counters[tile.kind] || 0) + 1;
        assets.push({
            source: "tile", kind: tile.kind, role: tile.role || "",
            name: tile.name, subfolder: tile.subfolder || "ariadne",
            seconds: Number(tile.seconds || 0), locked: !!tile.locked,
            label: `${KIND_LABEL[tile.kind] || tile.kind}${counters[tile.kind]}`,
            tile,
        });
    }
    for (const [input, kind] of Object.entries(SOCKET_KIND)) {
        if (!isInputConnected(node, input)) continue;
        // 批量图像（ImageBatch 等图像合成节点）按上游叶子图展开：3 张图的批量出 3 个引用，
        // 编号与 Python 张量按批维展开的顺序一致；视频/音频或无法解析的链路按 1 张计。
        const leaves = kind === "image" && SOCKET_BATCH.has(input) ? expandImageLeaves(node, input) : [null];
        for (const leaf of leaves) {
            counters[kind] = (counters[kind] || 0) + 1;
            assets.push({
                source: "socket", kind, role: SOCKET_ROLE[input], input,
                label: `${KIND_LABEL[kind]}${counters[kind]}`, connected: true, leaf,
            });
        }
    }
    return assets;
}

// 批量展开：顺着连线把图像输入下钻到叶子。LoadImage（或名字含 loadimage 的加载节点）= 1 张叶子图；
// 其他有已连接 IMAGE 输入的节点（批量/合成/缩放等）递归其输入槽；既不是加载节点也没有图像输入的按 1 张计。
export function expandImageLeaves(node, inputName, depth = 0, seen = new Set()) {
    const index = (node.inputs || []).findIndex((input) => input.name === inputName);
    if (index < 0) return [{ opaque: true }];
    let upstream = null;
    try {
        upstream = node.getInputNode?.(index);
    } catch {
        return [{ opaque: true }];
    }
    return upstreamLeaves(upstream, depth, seen);
}

function upstreamLeaves(upstream, depth, seen) {
    if (depth > 12) return [{ opaque: true }];  // 深递归保险丝（正常画布链路远达不到）
    if (!upstream) return [{ opaque: true }];
    const key = String(upstream.id ?? "");
    if (key && seen.has(key)) return [{ opaque: true }];  // 环路保护
    if (key) seen.add(key);
    if (/loadimage/i.test(String(upstream.type || upstream.comfyClass || ""))) return [{ node: upstream }];
    const imageSlots = [];
    (upstream.inputs || []).forEach((input, index) => {
        if (String(input.type || "").toUpperCase() === "IMAGE") imageSlots.push({ input, index });
    });
    if (imageSlots.length) {
        const leaves = [];
        for (const { input, index } of imageSlots) {
            if (input.link == null) continue;
            let source = null;
            try {
                source = upstream.getInputNode?.(index);
            } catch {
                continue;
            }
            if (!source) continue;
            leaves.push(...upstreamLeaves(source, depth + 1, seen));
        }
        if (leaves.length) return leaves;
    }
    return [{ opaque: true }];
}

export function modeOf(node) {
    const raw = String(widgetValue(node, "task_type") || "auto");
    const key = raw.split("(")[0].trim();
    // reference(多模态参考) 归入全能参考展示（原画布版同款），其他未知值原样透传。
    return key === "reference" ? "auto" : key;
}

export function setMode(node, key) {
    const mode = MODES.find((m) => m.key === key);
    if (mode) setWidgetValue(node, "task_type", mode.widget);
}

export function modeRules(mode) {
    return MODE_RULES[mode] || MODE_RULES.auto;
}

// ---- 画幅锁定自动写自适应：首帧/首尾帧/编辑/延长在方舟规格里硬性要求 adaptive
//      （跟随首帧图/原视频比例）。进入锁定态自动改写并记住原选择（lastAspect 存 properties，
//      随工作流保存）；解锁时还原，避免文生设的 9:16 既卡死规格校验、又被静默丢弃。
export function normalizeAspectLock(node) {
    const locked = modeRules(modeOf(node)).lockAspect;
    const current = String(widgetValue(node, "aspect_ratio") || "");
    if (locked) {
        if (current && current !== "adaptive") {
            if (!String(prop(node, "lastAspect", "") || "")) setProp(node, "lastAspect", current);
            setWidgetValue(node, "aspect_ratio", "adaptive");
        }
        return;
    }
    if (current === "adaptive") {
        const last = String(prop(node, "lastAspect", "") || "");
        if (last && last !== "adaptive") setWidgetValue(node, "aspect_ratio", last);
    }
}

// ---- 五段式优化输入（与 ariadne_core/seedance/optimizer.py 互为镜像） ----
const TASK_LABEL = {
    auto: "全能参考", reference: "全能参考", text: "文生视频", "first-frame": "首帧",
    "first-last": "首尾帧", edit: "视频编辑", extend: "视频延长",
};

export function buildOptimizerUserContent(input) {
    const lines = ["【本次优化任务】", `任务模式（用户已在页面选择）：${TASK_LABEL[input.taskType] || input.taskType}`];
    if (input.assets?.length) {
        lines.push("参考素材清单（仅编号清单，当前无法读取素材内容，不得假装已查看）：");
        for (const asset of input.assets) {
            const roleText = ROLE_LABEL[asset.role] ? `（${ROLE_LABEL[asset.role]}）` : "";
            lines.push(`@${asset.label || KIND_LABEL[asset.kind] || "素材"}：${KIND_LABEL[asset.kind] || asset.kind}${roleText}`);
        }
    }
    const params = [
        `总时长 ${input.duration === -1 ? "自动（跟随原视频）" : `${input.duration} 秒`}`,
        `分辨率 ${input.resolution}`,
        `画幅 ${input.aspectRatio === "adaptive" ? "自适应" : input.aspectRatio}`,
        input.generateAudio ? "有声" : "无声",
    ].join("、");
    lines.push(`页面生成参数（仅供规划，不得写入 Prompt）：${params}`);
    lines.push("【原始提示词】");
    lines.push(String(input.prompt || "").trim());
    lines.push("【执行要求】");
    lines.push("按系统提示词的工作流输出优化后的 Prompt。低置信度分歧按合理假设保守处理，不要向我提问。"
        + "只输出 Prompt 正文本身，不要附加参数提示、素材提示、补充说明等任何正文之外的行，不要使用代码围栏。");
    return lines.join("\n");
}

// ---- 草稿指纹（过期结果保护）与历史 ----
export function promptFingerprint(text) {
    const value = String(text ?? "");
    let h1 = 0x811c9dc5;
    let h2 = 0x01000193;
    for (let i = 0; i < value.length; i++) {
        const code = value.charCodeAt(i);
        h1 = ((h1 ^ code) * 0x01000193) >>> 0;
        h2 = ((h2 + code * 31) * 2654435761) >>> 0;
    }
    return `${h1.toString(36)}${h2.toString(36)}${value.length.toString(36)}`;
}

export function draftIsStale(node) {
    const fp = String(prop(node, "optimizerSourceFp", "") || "");
    if (!fp) return false; // 旧版数据无指纹：不误报
    return fp !== promptFingerprint(widgetValue(node, "prompt"));
}

// 历史按文本去重、最新在前、最多 20 条（原画布版同款契约）。
export function pushHistory(history, text, limit = 20) {
    const trimmed = String(text || "").trim();
    if (!trimmed) return Array.isArray(history) ? history : [];
    const entry = { id: `opt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`, text: trimmed, at: new Date().toISOString() };
    return [entry, ...(Array.isArray(history) ? history : []).filter((item) => item.text !== trimmed)].slice(0, limit);
}

export function normalizeHistory(history) {
    if (!Array.isArray(history)) return [];
    return history
        .filter((item) => item && typeof item.text === "string" && item.text.trim())
        .map((item) => ({ id: String(item.id || ""), text: item.text, at: String(item.at || "") }));
}

// ---- 优化技能按节点类型区分（服务端 resources/skills/<skill>.SKILL.md 白名单）。
//      新节点接入时在此登记自己的 skill；未登记的节点回退 Seedance 2.5 的 sd25-pe。
export const SKILL_BY_NODE_TYPE = {
    [SEEDANCE_TYPE]: "sd25-pe",
};

export function skillForNode(node) {
    return SKILL_BY_NODE_TYPE[node?.comfyClass || node?.constructor?.comfyClass || node?.type] || "sd25-pe";
}

// 队列执行结果的人话摘要：用户只看结论不看堆栈（2026-09-14 用户要求）。
// entry 为 /history/{id} 的条目；成功取成片文件名，失败按原因归类成一句话。
export function humanizeExecutionResult(entry) {
    if (!entry) return "任务状态未知";
    const status = entry.status || {};
    const messages = status.messages || [];
    let errorText = "";
    for (const [type, info] of messages) {
        if (type === "execution_error") {
            errorText = String(info?.exception_message || info?.error || "");
            break;
        }
    }
    if (status.completed && !errorText) {
        const names = [];
        for (const output of Object.values(entry.outputs || {})) {
            for (const value of Object.values(output || {})) {
                if (Array.isArray(value)) {
                    for (const item of value) {
                        if (item && typeof item === "object" && item.filename) names.push(item.filename);
                        else if (typeof item === "string" && !/^https?:\/\//i.test(item) && /\.(mp4|mov|png|jpe?g|webp)$/i.test(item.split("?")[0])) {
                            names.push(item.split("?")[0].split(/[\\/]/).pop());  // 跳过时效 URL，只报本地成片名
                        }
                    }
                } else if (value && typeof value === "object" && value.filename) names.push(value.filename);
            }
        }
        return names.length ? `✅ 出片完成：${names[0]}` : "✅ 生成完成";
    }
    if (errorText) {
        if (/credits? insufficient|(^|\D)402(\D|$)/i.test(errorText)) return "❌ Kie 积分不足：请先充值再试";
        if (/exhausted its free trial quota/i.test(errorText)) return "❌ 方舟免费额度已用完：请开通按量付费后重试";
        if (/policyviolation|sensitivecontent/i.test(errorText)) return "❌ 内容合规拦截：素材或成片触发了平台审核，换素材再试";
        if (/required input is missing/i.test(errorText)) return "❌ 参数缺失：节点必填参数没有提交成功";
        return `❌ 失败：${errorText.slice(0, 80)}`;
    }
    return status.status_str === "error" ? "❌ 执行失败（原因未捕获，详情看队列面板）" : "✅ 完成";
}
