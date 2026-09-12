"""一瞬入画（instant painting）契约层：多帧参考 → 高保真场景图（gpt-image-2，Kie 渠道）。

移植自画布插件 tools/instant-painting（与本地 CLI 技能同一套已验证流程）：
模型 gpt-image-2-image-to-image，input = {input_urls, prompt, aspect_ratio, quality}。
保真提示词模板为实测原版（英文，逐句保留）。
"""
from __future__ import annotations

MODEL = "gpt-image-2-image-to-image"
ASPECTS = ("9:16", "16:9")
QUALITIES = ("1K", "2K", "4K")
MODES = ("scene", "keep_people")

# 费用提示（providers 注册表口径，实际以账单为准）：2K≈5 / 4K≈8 credits；1K 未实测不标数。
CREDITS_HINT = {"1K": "credits --（未实测）", "2K": "≈5 credits", "4K": "≈8 credits"}


def build_fidelity_prompt(orientation: str, mode: str, note: str, ref_count: int) -> str:
    """一瞬入画保真提示词：参考图权威、人口构成锁死、画幅强制、无水印文字（原版逐句）。"""
    if orientation not in ASPECTS:
        raise RuntimeError(f"画幅需为 {'/'.join(ASPECTS)}")
    if mode not in MODES:
        raise RuntimeError(f"模式需为 {'/'.join(MODES)}")
    if ref_count < 1:
        raise RuntimeError("至少需要 1 张参考图（视频抽帧或参考图片输入）。")
    parts = [
        f"Faithful photorealistic scene reference image reconstructed strictly from the {ref_count} labeled reference image(s).",
        "The references are authoritative: reuse the real scene, environment, structures, camera perspective and composition; do not invent a new scene.",
    ]
    if mode == "scene":
        parts.append("No people or human figures in the final image.")
    else:
        parts.append(
            "Preserve population composition exactly as shown: do not add, remove, substitute, or change the ethnicity, appearance, clothing or pose of any person."
        )
        parts.append(
            "Keep people naturally in midground/background as atmosphere; never let them block the camera or dominate the composition."
        )
    parts.append("Output aspect ratio 9:16 portrait." if orientation == "9:16" else "Output aspect ratio 16:9 landscape.")
    parts.append("no watermark, no logo, no text, single fixed scene.")
    if str(note or "").strip():
        parts.append(f"Extra user constraints: {note.strip()}")
    return " ".join(parts)


def compile_input(input_urls: list[str], prompt: str, orientation: str, quality: str) -> dict:
    """组装 Kie createTask 的 input（quality 直传 1K/2K/4K，与画布版一致）。"""
    if orientation not in ASPECTS:
        raise RuntimeError(f"画幅需为 {'/'.join(ASPECTS)}")
    if quality not in QUALITIES:
        raise RuntimeError(f"画质需为 {'/'.join(QUALITIES)}")
    if not input_urls:
        raise RuntimeError("至少需要 1 张参考图。")
    return {"input_urls": input_urls, "prompt": prompt, "aspect_ratio": orientation, "quality": quality}
