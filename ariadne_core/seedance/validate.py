"""任务类型约束校验（画布插件 validate.ts 的 Python 版，逐条对齐）。"""
from __future__ import annotations

import re

from .contract import SeedanceJobSpec

# 官方提示词指南：编辑任务靠触发关键词识别任务类型，缺了会被当成普通参考生成。
EDIT_TRIGGERS = re.compile(r"(编辑|增加|加上|删除|去掉|修改|替换|改成|换成|变为)")


def validate_job(spec: SeedanceJobSpec) -> list[str]:
    errors: list[str] = []
    if not spec.prompt.strip():
        errors.append("提示词不能为空")
    if spec.duration != -1 and (not isinstance(spec.duration, int) or spec.duration < 4 or spec.duration > 30):
        errors.append("时长必须是 4-30 秒的整数或 -1")
    first = [asset for asset in spec.assets if asset.role == "first-frame"]
    last = [asset for asset in spec.assets if asset.role == "last-frame"]
    if last and not first:
        errors.append("尾帧必须和首帧一起提供")
    videos = [asset for asset in spec.assets if asset.kind == "video"]
    images = [asset for asset in spec.assets if asset.kind == "image"]
    annotations = [asset for asset in spec.assets if asset.role == "annotation"]
    if spec.task_type == "text" and spec.assets:
        errors.append("文生视频不能包含参考素材")
    if spec.task_type == "first-frame" and (not first or last):
        errors.append("首帧任务需要 1 张首帧，不能连接尾帧")
    if spec.task_type == "first-last" and (not first or not last):
        errors.append("首尾帧任务需要首帧和尾帧")
    if spec.task_type in ("first-frame", "first-last", "edit", "extend") and spec.aspect_ratio != "adaptive":
        errors.append("首帧、首尾帧、编辑和延长必须使用 adaptive 画幅")
    if spec.task_type == "edit":
        if spec.duration != -1:
            errors.append("视频编辑的时长必须使用 -1")
        if len(videos) != 1:
            errors.append("视频编辑只支持 1 段输入视频（4-30 秒）")
        if not EDIT_TRIGGERS.search(spec.prompt):
            errors.append("编辑提示词需包含触发词，例如：编辑、修改、替换、删除、增加")
    if spec.task_type in ("edit", "extend") and not videos:
        errors.append("视频编辑和延长至少需要 1 段参考视频")
    if annotations and spec.task_type != "edit":
        errors.append("精准编辑标注帧只能在视频编辑模式下使用")
    if len(images) > 30:
        errors.append("参考图片最多 30 张")
    if len(videos) > 10:
        errors.append("参考视频最多 10 段")
    if len([asset for asset in spec.assets if asset.kind == "audio"]) > 10:
        errors.append("参考音频最多 10 段")
    return errors
