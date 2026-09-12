"""编号编译与请求体组装（画布插件 compile.ts 的 Python 版，逐行对齐行为）。"""
from __future__ import annotations

from .contract import KIND_PREFIX_ARK, MODEL, ENDPOINT, SeedanceAsset, SeedanceJobSpec

# 素材职责句：方舟（@图像N）与 Kie（@ImageN）两套编译共用。
ROLE_DUTY = {
    "character": "人物外观与服装",
    "wardrobe": "服装款式与面料细节",
    "scene": "场景结构、光线与构图",
    "motion": "动作、运镜与节奏",
    "audio": "音色、台词或音乐",
}

_ARK_ROLE = {"image": ("image_url", "reference_image"), "video": ("video_url", "reference_video"), "audio": ("audio_url", "reference_audio")}


def compile_references(assets: list[SeedanceAsset]) -> list[dict]:
    """给素材编号（官方前缀），返回 {**asset, reference} 字典列表；first/last 帧不编号。"""
    counters = {"image": 0, "video": 0, "audio": 0}
    out = []
    for asset in assets:
        if asset.role in ("first-frame", "last-frame"):
            continue
        counters[asset.kind] += 1
        out.append(
            {
                "kind": asset.kind,
                "role": asset.role,
                "url": asset.url,
                "label": asset.label,
                "timestamp_seconds": asset.timestamp_seconds,
                "reference": f"@{KIND_PREFIX_ARK[asset.kind]}{counters[asset.kind]}",
            }
        )
    return out


def compile_prompt(prompt: str, references: list[dict]) -> str:
    """面板标签（@图片N）替换为官方编号（编号一致，仅前缀翻译）+ 追加素材职责句。"""
    text = prompt.strip()
    for asset in references:
        label = asset["label"]
        if not label:
            continue
        local = label if label.startswith("@") else f"@{label}"
        text = text.replace(local, asset["reference"])
    duties = [
        f"{asset['reference']}提供{ROLE_DUTY[asset['role']]}"
        for asset in references
        if asset["role"] in ROLE_DUTY
    ]
    return f"{text}\n素材职责：{'；'.join(duties)}。" if duties else text


def compile_annotation_block(task_type: str, references: list[dict]) -> str:
    """标注帧职责：框选/笔迹是编辑指示而非画面内容，并绑定官方时间戳写法。"""
    if task_type != "edit":
        return ""
    annotations = [asset for asset in references if asset["role"] == "annotation"]
    if not annotations:
        return ""
    videos = [asset for asset in references if asset["kind"] == "video"]
    parts = []
    for asset in annotations:
        seconds = asset["timestamp_seconds"] or 0
        moment = "开头" if seconds < 0.5 else f"第{round(seconds)}秒"
        source = videos[0]["reference"] if videos else "@视频1"
        parts.append(f"{asset['reference']} 是 {source} {moment}的标注帧")
    return (
        f"标注帧说明：{'；'.join(parts)}。标注帧中的矩形、画笔笔迹、箭头、文字与编号定位点均为编辑指示，"
        "不是画面内容，成片中不得出现任何标注笔迹；请按标注位置与编号执行上述编辑。"
    )


def compile_request(spec: SeedanceJobSpec) -> dict:
    """组装方舟请求体（未做ark_media归一化的原始 spec；首尾帧角色在 ark.py 发送前收敛）。"""
    references = compile_references(spec.assets)
    text = compile_prompt(spec.prompt, references)
    annotation_block = compile_annotation_block(spec.task_type, references)
    if annotation_block:
        text += f"\n{annotation_block}"

    content: list[dict] = [{"type": "text", "text": text}]
    first = next((asset for asset in spec.assets if asset.role == "first-frame"), None)
    last = next((asset for asset in spec.assets if asset.role == "last-frame"), None)
    if first:
        content.append({"type": "image_url", "image_url": {"url": first.url}, "role": "first_frame"})
    if last:
        content.append({"type": "image_url", "image_url": {"url": last.url}, "role": "last_frame"})
    for asset in references:
        kind_type, role = _ARK_ROLE[asset["kind"]]
        content.append({"type": kind_type, kind_type: {"url": asset["url"]}, "role": role})

    omni_map = {"auto": "auto", "reference": "reference", "edit": "edit", "extend": "extend"}
    body: dict = {
        "model": MODEL,
        "content": content,
        "ratio": spec.aspect_ratio,
        "duration": spec.duration,
        "generate_audio": spec.generate_audio,
        "watermark": False,
    }
    if spec.task_type in omni_map:
        body["omni_reference_task_type"] = omni_map[spec.task_type]
    return {"model": MODEL, "endpoint": ENDPOINT, "body": body, "references": references}
