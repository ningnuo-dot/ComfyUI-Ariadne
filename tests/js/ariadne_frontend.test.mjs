// 前端纯模块单测（node --test tests/js/）：适配器 + 优化客户端契约。
// 覆盖：模式切换不丢值、素材职责/编号、五段式优化输入、历史去重与上限、过期草稿保护、
// 瓦片编号前移（提示词标签改写）、SSE 半包与停止语义。
import { test } from "node:test";
import assert from "node:assert/strict";

import {
    MODES, buildOptimizerUserContent, cachedTiles, collectAssets, draftIsStale, expandImageLeaves, humanizeExecutionResult, modeOf,
    modeRules, normalizeAspectLock, normalizeHistory, promptFingerprint, pushHistory, prop, setMode,
    splitPromptChips, setWidgetValue, setProp, syncTiles, tileKey, tilesOf, widgetValue, writeTiles,
} from "../../web/js/ariadne_adapter.js";
import { feedStreamEvent, newStreamState } from "../../web/js/ariadne_optimizer_client.js";
import { readFileSync } from "node:fs";

const adapterPath = new URL("../../web/js/ariadne_adapter.js", import.meta.url);
const workbenchPath = new URL("../../web/js/ariadne_workbench.js", import.meta.url);

function makeNode(widgets = {}, inputs = [], connections = {}) {
    return {
        properties: {},
        widgets: Object.entries(widgets).map(([name, value]) => ({ name, value })),
        inputs,
        getInputNode(index) {
            const input = inputs[index];
            return input && connections[input.name] ? connections[input.name] : null;
        },
    };
}

function widgetOf(node, name) {
    return node.widgets.find((w) => w.name === name);
}

test("模式映射：六种模式写回 Python 端 widget 取值", () => {
    const node = makeNode({ task_type: "auto(全能参考)" });
    for (const mode of MODES) {
        setMode(node, mode.key);
        assert.equal(widgetOf(node, "task_type").value, mode.widget);
        assert.equal(modeOf(node), mode.key);
    }
});

test("reference(多模态参考) 归入全能参考展示", () => {
    const node = makeNode({ task_type: "reference(多模态参考)" });
    assert.equal(modeOf(node), "auto");
});

test("setWidgetValue 接力原 callback（参数联动不失效）", () => {
    const node = makeNode({ duration: 10 });
    let seen = null;
    widgetOf(node, "duration").callback = (v) => { seen = v; };
    assert.equal(setWidgetValue(node, "duration", 12), true);
    assert.equal(seen, 12);
    assert.equal(setWidgetValue(node, "missing", 1), false);
});

test("模式切换只改显示与锁定规则，不抹掉既有参数值", () => {
    const node = makeNode({
        task_type: "auto(全能参考)", duration: 8, resolution: "1080p", aspect_ratio: "16:9",
    });
    setMode(node, "edit");
    assert.equal(modeOf(node), "edit");
    assert.equal(widgetValue(node, "duration"), 8);       // 值保持
    assert.equal(widgetValue(node, "resolution"), "1080p");
    assert.equal(widgetValue(node, "aspect_ratio"), "16:9");
    assert.equal(modeRules("edit").lockDuration, true);   // 只有锁定规则变化
    assert.equal(modeRules("edit").lockAspect, true);
    assert.deepEqual(modeRules("edit").sockets, ["motion_video"]);
});

test("素材聚合：瓦片在前插座接着编，编号规则与 Python _assign_labels 一致", () => {
    const node = makeNode({
        ariadne_assets: JSON.stringify([
            { kind: "image", name: "a.png", subfolder: "ariadne/image", role: "character" },
            { kind: "video", name: "b.mp4", subfolder: "ariadne/video", role: "motion" },
            { kind: "image", name: "c.png", subfolder: "ariadne/image", role: "scene" },
        ]),
    }, [{ name: "first_frame" }, { name: "last_frame" }, { name: "character_images" }], { character_images: { id: 1 } });
    const assets = collectAssets(node);
    assert.deepEqual(assets.map((a) => a.label), ["图片1", "视频1", "图片2", "图片3"]);
    assert.equal(assets[3].source, "socket");
    assert.equal(assets[3].role, "character");
    assert.equal(assets[3].connected, true);
});

test("syncTiles：删除首个瓦片后编号前移并改写提示词旧标签", () => {
    const node = makeNode({
        ariadne_assets: JSON.stringify([
            { kind: "image", name: "a.png", subfolder: "ariadne/image", role: "character", label: "图片1" },
            { kind: "image", name: "c.png", subfolder: "ariadne/image", role: "scene", label: "图片2" },
        ]),
        prompt: "人物见@图片1，场景见@图片2",
    });
    widgetOf(node, "prompt").getValue = () => widgetOf(node, "prompt").value;
    widgetOf(node, "prompt").setValue = (v) => { widgetOf(node, "prompt").value = v; };
    syncTiles(node);  // 首次同步建立缓存（真实应用在节点升级时已做）
    const remaining = tilesOf(node).filter((t) => t.name !== "a.png");
    writeTiles(node, remaining);
    syncTiles(node);
    assert.equal(widgetValue(node, "prompt"), "人物见@图片1，场景见@图片1");
    assert.deepEqual(collectAssets(node).map((a) => a.label), ["图片1"]);
    assert.equal(cachedTiles(node)[0].label, "图片1");
});

test("syncTiles：交换两个瓦片顺序，提示词 @引用正确互换（不塌缩）", () => {
    const node = makeNode({
        ariadne_assets: JSON.stringify([
            { kind: "image", name: "a.png", subfolder: "ariadne/image", role: "character", label: "图片1" },
            { kind: "image", name: "b.png", subfolder: "ariadne/image", role: "scene", label: "图片2" },
        ]),
        prompt: "参考 @图片1 和 @图片2 的构图",
    });
    widgetOf(node, "prompt").getValue = () => widgetOf(node, "prompt").value;
    widgetOf(node, "prompt").setValue = (v) => { widgetOf(node, "prompt").value = v; };
    syncTiles(node);  // 首次同步建立缓存（真实应用在节点升级时已做）
    // 交换 a/b 顺序（拖动排序的落点）
    const tiles = tilesOf(node);
    [tiles[0], tiles[1]] = [tiles[1], tiles[0]];
    writeTiles(node, tiles);
    syncTiles(node);
    assert.equal(widgetValue(node, "prompt"), "参考 @图片2 和 @图片1 的构图");
});

test("syncTiles：未知 kind 的标签有兜底，不产出 undefined", () => {
    const node = makeNode({
        ariadne_assets: JSON.stringify([{ kind: "model3d", name: "m.glb", subfolder: "ariadne/3d", role: "annotation" }]),
        prompt: "x",
    });
    const tiles = syncTiles(node);
    assert.equal(tiles[0].label, "model3d1");
});

test("widgetMap：同名 widget 时 live 优先于 stash", () => {
    const node = makeNode({ task_type: "live-value" });
    node.__ariadneStashed = [{ name: "task_type", value: "stashed-value" }];
    assert.equal(widgetValue(node, "task_type"), "live-value");
    // stash 中存在而 live 没有的仍可读写
    node.__ariadneStashed.push({ name: "duration", value: 8 });
    assert.equal(widgetValue(node, "duration"), 8);
});

test("历史：按文本去重、最新在前、上限 20 条", () => {
    let history = [];
    for (let i = 0; i < 25; i++) history = pushHistory(history, `文本${i % 30}`);
    assert.equal(history.length, 20);
    assert.equal(history[0].text, "文本24");
    const deduped = pushHistory(history, "文本24");  // 重复文本不加新条目
    assert.equal(deduped.length, 20);
    assert.equal(deduped[0].text, "文本24");
    assert.equal(deduped.filter((item) => item.text === "文本24").length, 1);
    assert.equal(pushHistory(history, "   ").length, 20);  // 空白不入历史
    assert.deepEqual(normalizeHistory([{ text: " 保留 " }, null, { text: "" }, { id: "x", text: "y" }]).length, 2);
});

test("过期草稿保护：提示词变化后草稿标记为基于旧版本", () => {
    const node = makeNode({ prompt: "原始提示词 v1" });
    assert.equal(draftIsStale(node), false);  // 无指纹（旧数据）不误报
    setProp(node, "optimizerSourceFp", promptFingerprint("原始提示词 v1"));
    assert.equal(draftIsStale(node), false);  // 提示词未变
    widgetOf(node, "prompt").value = "原始提示词 v2";
    assert.equal(draftIsStale(node), true);   // 提示词已变 → 过期
    assert.notEqual(promptFingerprint("v1"), promptFingerprint("v2"));
    assert.equal(promptFingerprint("同一文本"), promptFingerprint("同一文本"));
});

test("五段式优化输入：任务模式/素材清单/参数/原始提示词/执行要求", () => {
    const content = buildOptimizerUserContent({
        taskType: "first-last", prompt: "跳舞",
        assets: [{ kind: "image", role: "first-frame", label: "图片1" }, { kind: "image", role: "last-frame", label: "图片2" }],
        duration: 10, resolution: "720p", aspectRatio: "adaptive", generateAudio: false,
    });
    const sections = ["【本次优化任务】", "参考素材清单", "页面生成参数", "【原始提示词】", "【执行要求】"];
    for (const section of sections) assert.ok(content.includes(section), section);
    assert.ok(content.includes("首尾帧"));
    assert.ok(content.includes("@图片1：图片（首帧）"));
    assert.ok(content.includes("@图片2：图片（尾帧）"));
    assert.ok(content.includes("自适应"));
    assert.ok(content.includes("无声"));
    assert.ok(content.includes("跳舞"));
});

test("tileKey 与瓦片读写往返", () => {
    const node = makeNode({ ariadne_assets: "[]" });
    const tiles = [{ kind: "audio", name: "x.wav", subfolder: "ariadne/audio", role: "audio", seconds: 3 }];
    writeTiles(node, tiles);
    assert.deepEqual(tilesOf(node), tiles);
    assert.equal(tileKey(tiles[0]), "ariadne/audio/x.wav");
});

test("SSE 客户端：半包拼接、error/done 事件、噪声忽略", () => {
    const state = newStreamState();
    feedStreamEvent(state, 'data: {"delta":"你"}\n\ndata: {"del');
    assert.equal(state.text, "你");
    feedStreamEvent(state, 'ta":"好"}\n\ndata: {"error":"配额不足"}\n\ndata: {"done":true}\n\n');
    assert.equal(state.text, "你好");
    assert.equal(state.error, "配额不足");
    assert.equal(state.done, true);
    const noise = newStreamState();
    feedStreamEvent(noise, ": heartbeat\n\nevent: ping\n\ndata: not-json\n\n");
    assert.equal(noise.text, "");
    assert.equal(noise.error, "");
});

test("splitPromptChips：已知标签精确截断，标签后的中文正文不被包进胶囊", () => {
    const labels = ["图片1", "图片2"];
    assert.deepEqual(splitPromptChips("以@图片1为准。", labels), ["以", "@图片1", "为准。"]);
    assert.deepEqual(
        splitPromptChips("从@图片1定义的首帧连续运动到@图片2定义的尾帧，全程一镜到底。", labels),
        ["从", "@图片1", "定义的首帧连续运动到", "@图片2", "定义的尾帧，全程一镜到底。"],
    );
});

test("splitPromptChips：长标签优先（图片10 不被 图片1 抢占）", () => {
    // split 带捕获组：末尾命中胶囊时会多出一个尾随空串（渲染端跳过空段）
    assert.deepEqual(splitPromptChips("见@图片10和@图片1", ["图片1", "图片10"]), ["见", "@图片10", "和", "@图片1", ""]);
});

test("splitPromptChips：悬空编号引用按「种类词+编号」形状兜底，普通 @词 不吞正文", () => {
    // 标签清单为空（纯插座会话漏传/模型幻觉编号）也不得回到「吞到标点」的旧行为
    assert.deepEqual(splitPromptChips("引用@图片3为准。", []), ["引用", "@图片3", "为准。"]);
    assert.deepEqual(splitPromptChips("写@主角走进房间", []), ["写@主角走进房间"]);
});

test("splitPromptChips：空文本、空标签与非编号素材标签均安全", () => {
    assert.deepEqual(splitPromptChips("", ["图片1"]), [""]);
    assert.deepEqual(splitPromptChips("纯文本", []), ["纯文本"]);
    assert.deepEqual(splitPromptChips("纯文本", null), ["纯文本"]);
    // 非编号自定义标签走已知标签分支（种类词形状匹配不到时仍可成胶囊）
    assert.deepEqual(splitPromptChips("主角见@主角A特写", ["主角A"]), ["主角见", "@主角A", "特写"]);
});

test("画幅锁定：进入首帧类模式自动写 adaptive 并记住原选择，解锁还原", () => {
    const node = makeNode({ task_type: "auto(全能参考)", aspect_ratio: "9:16" });
    setMode(node, "first-frame");
    normalizeAspectLock(node);
    assert.equal(widgetValue(node, "aspect_ratio"), "adaptive");
    assert.equal(prop(node, "lastAspect"), "9:16");          // 原选择已记忆
    setMode(node, "text");
    normalizeAspectLock(node);
    assert.equal(widgetValue(node, "aspect_ratio"), "9:16"); // 解锁还原，不静默丢弃
});

test("画幅锁定：锁定时已是 adaptive 不覆盖记忆；无记忆解锁保持 adaptive", () => {
    const node = makeNode({ task_type: "auto(全能参考)", aspect_ratio: "adaptive" });
    setMode(node, "edit");
    normalizeAspectLock(node);
    assert.equal(widgetValue(node, "aspect_ratio"), "adaptive");
    assert.equal(prop(node, "lastAspect", ""), "");          // 不把 adaptive 记成「原选择」
    setMode(node, "text");
    normalizeAspectLock(node);
    assert.equal(widgetValue(node, "aspect_ratio"), "adaptive");
});

test("画幅锁定：解锁还原取最近一次手选（lastAspect 随 properties 走工作流保存）", () => {
    const node = makeNode({ task_type: "text(文生视频)", aspect_ratio: "9:16" });
    setProp(node, "lastAspect", "16:9");
    setMode(node, "extend");
    normalizeAspectLock(node);
    assert.equal(widgetValue(node, "aspect_ratio"), "adaptive");
    setMode(node, "auto");
    normalizeAspectLock(node);
    assert.equal(widgetValue(node, "aspect_ratio"), "16:9");
});

test("批量图像展开：3 张 LoadImage 合批出 3 个引用，编号与 Python 批维展开一致", () => {
    const leafA = Object.assign(makeNode({ image: "a.png" }), { type: "LoadImage", id: 101 });
    const leafB = Object.assign(makeNode({ image: "b.png" }), { type: "LoadImage", id: 102 });
    const leafC = Object.assign(makeNode({ image: "c.png" }), { type: "LoadImage", id: 103 });
    const batch = makeNode({}, [
        { name: "image0", type: "IMAGE", link: 1 },
        { name: "image1", type: "IMAGE", link: 2 },
        { name: "image2", type: "IMAGE", link: 3 },
        { name: "image3", type: "IMAGE", link: null },
    ], { image0: leafA, image1: leafB, image2: leafC });
    Object.assign(batch, { type: "ImageBatch", id: 200 });
    const node = makeNode({ ariadne_assets: "[]" }, [{ name: "image_1", type: "IMAGE", link: 9 }], { image_1: batch });

    const socketAssets = collectAssets(node).filter((asset) => asset.source === "socket");
    assert.equal(socketAssets.length, 3);
    assert.deepEqual(socketAssets.map((asset) => asset.label), ["图片1", "图片2", "图片3"]);
    assert.equal(socketAssets[0].leaf.node.widgets[0].value, "a.png");
    assert.equal(socketAssets[2].leaf.node.widgets[0].value, "c.png");
    // 直接展开函数与 collectAssets 口径一致
    assert.equal(expandImageLeaves(node, "image_1").length, 3);
});

test("批量图像展开兜底：非加载类上游且无图像输入时按 1 张计", () => {
    const mystery = Object.assign(makeNode({ foo: "x" }), { type: "MysteryNode", id: 300 });
    const node = makeNode({ ariadne_assets: "[]" }, [{ name: "image_1", type: "IMAGE", link: 7 }], { image_1: mystery });
    const socketAssets = collectAssets(node).filter((asset) => asset.source === "socket");
    assert.equal(socketAssets.length, 1);
    assert.equal(socketAssets[0].label, "图片1");
});

test("批量展开按插座区分：标准版人物/服装/场景展开，首帧/尾帧保持单张", () => {
    const leafA = Object.assign(makeNode({ image: "a.png" }), { type: "LoadImage", id: 401 });
    const leafB = Object.assign(makeNode({ image: "b.png" }), { type: "LoadImage", id: 402 });
    const batch = makeNode({}, [
        { name: "image0", type: "IMAGE", link: 1 },
        { name: "image1", type: "IMAGE", link: 2 },
    ], { image0: leafA, image1: leafB });
    Object.assign(batch, { type: "ImageBatch", id: 400 });
    const node = makeNode({ ariadne_assets: "[]" }, [
        { name: "character_images", type: "IMAGE", link: 11 },
        { name: "first_frame", type: "IMAGE", link: 12 },
    ], { character_images: batch, first_frame: batch });

    const socketAssets = collectAssets(node).filter((asset) => asset.source === "socket");
    assert.equal(socketAssets.length, 3);  // 人物批量展开 2 + 首帧单张 1
    assert.equal(socketAssets.filter((asset) => asset.input === "character_images").length, 2);
    assert.equal(socketAssets.filter((asset) => asset.input === "first_frame").length, 1);
    assert.deepEqual(socketAssets.map((asset) => asset.label), ["图片1", "图片2", "图片3"]);
});

test("人话摘要：成功出片取成片文件名", () => {
    assert.equal(
        humanizeExecutionResult({
            status: { completed: true },
            outputs: { "9": { text: ["https://x/cgt.mp4?sig=1", "D:/out/Seedance版_cgt.mp4"] } },
        }),
        "✅ 出片完成：Seedance版_cgt.mp4",
    );
    assert.equal(
        humanizeExecutionResult({ status: { completed: true }, outputs: { "1": { images: [{ filename: "abc.png" }] } } }),
        "✅ 出片完成：abc.png",
    );
});

test("人话摘要：失败按原因归类（积分/合规/参数缺失/兜底截断）", () => {
    const entry = (msg) => ({ status: { status_str: "error", completed: false, messages: [["execution_error", { exception_message: msg }]] } });
    assert.equal(
        humanizeExecutionResult(entry("Kie 创建任务失败（code=402）（HTTP 200）：Credits insufficient : balance")),
        "❌ Kie 积分不足：请先充值再试",
    );
    assert.equal(
        humanizeExecutionResult(entry("Your account has exhausted its free trial quota for the model")),
        "❌ 方舟免费额度已用完：请开通按量付费后重试",
    );
    assert.equal(
        humanizeExecutionResult(entry("OutputVideoSensitiveContentDetected.PolicyViolation")),
        "❌ 内容合规拦截：素材或成片触发了平台审核，换素材再试",
    );
    assert.equal(
        humanizeExecutionResult(entry("Required input is missing: prompt")),
        "❌ 参数缺失：节点必填参数没有提交成功",
    );
    assert.equal(humanizeExecutionResult(entry("某奇怪错误 ABCDEF")), "❌ 失败：某奇怪错误 ABCDEF");
});


test("workbench 引用的 adapter 导出必须已导入（防 SEEDANCE_TYPE is not defined 复发）", () => {
    const adapterSrc = readFileSync(adapterPath, "utf8");
    const wbSrc = readFileSync(workbenchPath, "utf8");
    const exported = [...adapterSrc.matchAll(/export (?:const|function|class) ([A-Za-z_$][\w$]*)/g)].map((m) => m[1]);
    const importBlock = wbSrc.match(/import \{([\s\S]*?)\} from "\.\/ariadne_adapter\.js"/);
    assert.ok(importBlock, "workbench 缺少 adapter 导入块");
    const imported = new Set(importBlock[1].split(",").map((s) => s.trim()).filter(Boolean));
    const missing = exported.filter((name) => {
        const used = new RegExp(`\b${name}\b`).test(wbSrc);
        const locallyDeclared = new RegExp(`(?:function|const|let|var|class)\s+${name}\b`).test(wbSrc);
        return used && !locallyDeclared && !imported.has(name);
    });
    assert.deepEqual(missing, [], `workbench 使用了未导入的 adapter 导出：${missing.join(", ")}`);
});
