// Ariadne 共享媒体辅助：素材上传/预览地址/视频裁剪浮层/瓦片 DOM 刷新。
// ui.js（节点瓦片区）与 ariadne_workbench.js（创作台）共用，避免双向依赖。
// 依赖：../../scripts/app.js 不在此导入；DOM 均挂在 document.body 级浮层。

import {
    cachedTiles, setWidgetValue, splitPromptChips, syncTiles, tileKey, widgetValue, ROLE_OPTIONS, KIND_LABEL,
} from "./ariadne_adapter.js";

export function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

export function kindOfFile(file) {
    const byType = file.type?.startsWith("video/") ? "video" : file.type?.startsWith("audio/") ? "audio" : file.type?.startsWith("image/") ? "image" : "";
    if (byType) return byType;
    // 浏览器对 .mkv/.flac 等可能给空 type：按扩展名兜底，避免误判成图片跳过视频预检。
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (["mp4", "mov", "webm", "mkv", "m4v", "avi"].includes(ext)) return "video";
    if (["mp3", "wav", "m4a", "aac", "flac", "ogg"].includes(ext)) return "audio";
    return "image";
}

export function defaultRoleOf(kind) {
    return kind === "video" ? "motion" : kind === "audio" ? "audio" : "character";
}

// 上传到 /ariadne/upload（沿用既有契约：kind/role 查询参数，返回 name/subfolder/kind/role/seconds…）。
export async function uploadAsset(file, defaultRole) {
    const kind = kindOfFile(file);
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`/ariadne/upload?kind=${kind}&role=${defaultRole || defaultRoleOf(kind)}`, { method: "POST", body: form });
    const data = await response.json();
    if (data.error) throw new Error(data.error);
    return data;
}

export function viewUrl(tile) {
    // subfolder 为空串 = 文件在 input 根目录（LoadVideo/LoadImage 上游的常见情况），
    // 不能强拼默认值，否则 /view 404（裁剪浮层黑屏的根因）。
    const subfolder = tile.subfolder || "";
    return `/view?filename=${encodeURIComponent(tile.name)}${subfolder ? `&subfolder=${encodeURIComponent(subfolder)}` : ""}&type=input`;
}

// 插座上游是 LoadImage 类节点时，取其源图文件名做预览地址（/view 只认 input 目录）；
// 上游是其他节点的输出（无落盘文件）时返回空串，调用方退回图标占位。
// 插座上游是 LoadVideo/LoadImage 类节点时，取其源媒体文件名做预览地址（/view 只认 input 目录）；
// 上游是其他节点的输出（无落盘文件）时返回 { url:"", isVideo:false }，调用方退回图标占位。
export function upstreamPreview(node, inputName) {
    const index = (node.inputs || []).findIndex((i) => i.name === inputName);
    if (index < 0) return { url: "", isVideo: false };
    let upstream = null;
    try {
        upstream = node.getInputNode(index);
    } catch {
        return { url: "", isVideo: false };
    }
    return previewFromUpstream(upstream);
}

// 从上游节点本体提取预览（批量展开的叶子芯片用：每张叶子各自回源到自己的 LoadImage）。
export function previewFromUpstream(upstream) {
    if (!upstream?.widgets) return { url: "", isVideo: false };
    for (const w of upstream.widgets) {
        const value = typeof w.value === "string" ? w.value : "";
        if (/\.(mp4|mov|webm|mkv|m4v|avi)$/i.test(value)) {
            return { url: `/view?filename=${encodeURIComponent(value)}&type=input`, isVideo: true };
        }
        if (/\.(png|jpe?g|webp|gif|bmp)$/i.test(value)) {
            return { url: `/view?filename=${encodeURIComponent(value)}&type=input`, isVideo: false };
        }
    }
    return { url: "", isVideo: false };
}

// 职责轮换（瓦片卡上的职责按钮）。
export function nextRole(role) {
    const index = ROLE_OPTIONS.findIndex(([value]) => value === role);
    return ROLE_OPTIONS[(index + 1) % ROLE_OPTIONS.length][0];
}

// 行内 @引用胶囊渲染（原画布版精髓）：切分规则在 adapter 的 splitPromptChips（纯函数可单测），
// 这里只负责把切分结果画成原子胶囊。refs 可传瓦片/素材对象（取 .label，插座素材同用）或纯标签字符串。
export function renderPromptChips(editor, text, refs = []) {
    const labels = (refs || [])
        .map((ref) => (ref && typeof ref === "object" ? ref.label : ref))
        .filter(Boolean);
    editor.innerHTML = "";
    for (const part of splitPromptChips(text, labels)) {
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

// contentEditable 光标偏移量（按纯文本字符计），用于重渲染后恢复光标位置。
export function caretOffsetIn(editor) {
    const selection = window.getSelection();
    if (!selection.rangeCount || !editor.contains(selection.getRangeAt(0).startContainer)) return null;
    const range = selection.getRangeAt(0);
    const pre = range.cloneRange();
    pre.selectNodeContents(editor);
    pre.setEnd(range.endContainer, range.endOffset);
    return pre.toString().length;
}

export function placeCaretOffset(editor, offset) {
    const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
    let remaining = offset;
    let lastNode = null;
    while (walker.nextNode()) {
        const node = walker.currentNode;
        if (node.length >= remaining) {
            const range = document.createRange();
            range.setStart(node, remaining);
            range.collapse(true);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return;
        }
        remaining -= node.length;
        lastNode = node;
    }
    if (lastNode) {
        const range = document.createRange();
        range.setStart(lastNode, lastNode.length);
        range.collapse(true);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
    }
}

// 瓦片 DOM 刷新句柄：ui.js 建 ariadne_assets DOM widget 时挂到 widget 上，此处统一触发。
export function refreshTilesDom(node) {
    const widget = node.widgets?.find((w) => w.name === "ariadne_assets");
    widget?.__ariadneRefreshTiles?.();
}

// 瓦片状态一并推进（编号前移 + 提示词标签改写 + 写回）并刷新节点 DOM。
export function commitTiles(node, tiles) {
    setWidgetValue(node, "ariadne_assets", JSON.stringify(tiles));
    syncTiles(node);
    refreshTilesDom(node);
}

// 裁剪浮层重构为原版布局（左预览+顶时间轴+控制列），实现在 ariadne_trim_dialog.js；
// 此处转发保持既有调用点不变。
import { openTrimDialog as _openTrimDialog } from "./ariadne_trim_dialog.js";
export const openTrimDialog = _openTrimDialog;
