"""Google Omni 1.1（Kie 渠道）契约层：媒体角色标注、输入编译、估价。

移植自本机实测基线 ComfyUI-Kie omni_node.py（真实出片验证）与 kie_pricing.py（2026-09-09
全表 20 行截图）。提示词占位符是 Kie Omni 专属语法：<IMAGE_REF_N>/<VIDEO_REF_0>/
<FIRST_FRAME>/<LAST_FRAME>/<CHARACTER_ID_0>，与 Seedance 的 @引用 体系互不通用。
编号规则（与基线一致）：人物参考 = IMAGE_REF_0，场景参考从 IMAGE_REF_1 顺延。
"""
from __future__ import annotations

MODEL = "google/gemini-omni-flash-1-1"
ASPECTS = ("9:16", "16:9")
RESOLUTIONS = ("360p", "720p", "1080p", "4k")
DURATIONS = ("4", "6", "8", "10")

# 带视频/图片输入：按次计费（Kie 忽略 duration）。
WITH_VIDEO_INPUT = {"360p": 120, "720p": 120, "1080p": 120, "4k": 180}
# 无视频输入：时长 × 分辨率，只有 4/6/8/10 秒有价（2026-09-09 全表 20 行）。
NO_VIDEO_INPUT = {
    4: {"360p": 45, "720p": 45, "1080p": 45, "4k": 105},
    6: {"360p": 60, "720p": 60, "1080p": 60, "4k": 120},
    8: {"360p": 75, "720p": 75, "1080p": 75, "4k": 135},
    10: {"360p": 90, "720p": 90, "1080p": 90, "4k": 150},
}
USD_PER_CREDIT = 0.005
USD_TO_CNY = 6.71
_PRICED_DURATIONS = sorted(NO_VIDEO_INPUT)


def estimate_omni(duration_seconds: int, resolution: str, has_video_input: bool, has_image_input: bool) -> dict | None:
    """按已验证价格表预估；查不到的组合返回 None（显示积分 --，不外推）。

    未闭环口径按「取贵」：①时长无档位（5/7/9 秒）取上一档；②仅连图片参考按带视频档上界。
    """
    if has_video_input or has_image_input:
        credits = WITH_VIDEO_INPUT.get(resolution)
        if credits is None:
            return None
        return _money(credits) | {"rounded_up_duration": None, "upper_bound": not has_video_input}
    duration = next((value for value in _PRICED_DURATIONS if duration_seconds <= value), None)
    if duration is None:
        return None
    credits = NO_VIDEO_INPUT[duration].get(resolution)
    if credits is None:
        return None
    return _money(credits) | {"rounded_up_duration": None if duration == duration_seconds else duration, "upper_bound": False}


def _money(credits: int) -> dict:
    return {"credits": credits, "usd": round(credits * USD_PER_CREDIT, 3), "cny": round(credits * USD_PER_CREDIT * USD_TO_CNY, 2)}


def build_media_roles(
    has_character: bool,
    scene_count: int,
    has_video: bool,
    has_character_id: bool,
    has_first: bool = False,
    has_last: bool = False,
) -> list[str]:
    """按输入构成生成前置角色标注（与实测基线 omni_node.py 逐句对齐）。"""
    roles: list[str] = []
    if has_first:
        roles.append("<FIRST_FRAME> is the starting frame. Preserve its composition at the start of the video.")
        if has_last:
            roles.append("<LAST_FRAME> is the ending frame. Create a smooth transition from the first frame to the last frame.")
        return roles
    index = 0
    if has_character:
        roles.append("<IMAGE_REF_0> is the character and outfit reference. Keep the character and clothing consistent.")
        index = 1
    for scene_index in range(max(scene_count, 0)):
        roles.append(
            f"<IMAGE_REF_{index + scene_index}> is scene reference {scene_index + 1}. "
            "Use only its environment, composition, lighting, and atmosphere for the matching planned shot."
        )
    if has_video:
        roles.append("<VIDEO_REF_0> is the motion, camera, and timing reference. Follow its movement and shot rhythm.")
    if has_character_id:
        roles.append("<CHARACTER_ID_0> is the fixed identity. Keep this exact character's face and appearance throughout the video.")
    return roles


def compile_input(
    prompt: str,
    aspect_ratio: str,
    resolution: str,
    duration: str,
    *,
    has_character: bool = False,
    scene_count: int = 0,
    has_video: bool = False,
    has_character_id: bool = False,
    image_urls: list[str] | None = None,
    character_ids: list[str] | None = None,
    video_list: list[dict] | None = None,
    first_frame_url: str = "",
    last_frame_url: str = "",
    seed: int = 0,
) -> dict:
    """组装 Kie createTask 的 input（字段清单与实测基线一致，多余字段不发）。"""
    if aspect_ratio not in ASPECTS:
        raise RuntimeError(f"画幅需为 {'/'.join(ASPECTS)}")
    if resolution not in RESOLUTIONS:
        raise RuntimeError(f"分辨率需为 {'/'.join(RESOLUTIONS)}")
    if duration not in DURATIONS:
        raise RuntimeError(f"输出时长需为 {'/'.join(DURATIONS)} 秒")
    if first_frame_url and (image_urls or video_list or character_ids):
        raise RuntimeError("首尾帧模式不能与人物/场景/视频参考同时使用。")
    roles = build_media_roles(
        has_character=has_character,
        scene_count=scene_count,
        has_video=has_video,
        has_character_id=has_character_id,
        has_first=bool(first_frame_url),
        has_last=bool(last_frame_url),
    )
    input_data: dict = {
        "prompt": "\n".join(roles + [prompt.strip()]),
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "duration": duration,  # Kie 要求字符串；有参考视频时也要求显式时长
    }
    if image_urls:
        input_data["image_urls"] = image_urls
    if character_ids:
        input_data["character_ids"] = character_ids
    if video_list:
        input_data["video_list"] = video_list
    if first_frame_url:
        input_data["first_frame_url"] = first_frame_url
    if last_frame_url:
        input_data["last_frame_url"] = last_frame_url
    if seed > 0:
        input_data["seed"] = seed
    return input_data
