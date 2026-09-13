"""提示词优化契约层（画布插件 optimizer.ts 的 Python 版，供 /ariadne/optimize 与单测使用）。

- 系统规则：resources/skills/<skill>.SKILL.md 原文迁移，**按节点类型取不同 skill**
  （Seedance 2.5 用 sd25-pe；后续节点各配各的 skill，架构见 valid_skill_name/available_skills）；
- 五段式输入：任务模式 + 素材清单 + 页面参数 + 原始提示词 + 执行要求（与前端构造互为镜像）；
- SSE 增量解析：心跳、半包、[DONE] 与 reasoning_content 一律忽略。
"""
from __future__ import annotations

import re
from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "resources" / "skills"
_SKILL_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.SKILL\.md$")
_skill_cache: dict[str, str] = {}

KIND_LABEL = {"image": "图片", "video": "视频", "audio": "音频"}
ROLE_LABEL = {"first-frame": "首帧", "last-frame": "尾帧", "character": "人物", "wardrobe": "服装",
              "scene": "场景", "motion": "动作", "audio": "声音", "annotation": "标注帧"}
TASK_LABEL = {"auto": "全能参考", "reference": "全能参考", "text": "文生视频",
              "first-frame": "首帧", "first-last": "首尾帧", "edit": "视频编辑", "extend": "视频延长"}

DEFAULT_SKILL = "sd25-pe"


def available_skills() -> list[str]:
    """skills 目录下合法的 skill 名（文件名白名单，防路径注入）。"""
    if not _SKILLS_DIR.is_dir():
        return []
    return sorted(p.name[:-9] for p in _SKILLS_DIR.glob("*.SKILL.md") if _SKILL_FILE_RE.match(p.name))


def valid_skill_name(skill: str) -> bool:
    return skill in available_skills()


def system_rule_text(skill: str = DEFAULT_SKILL) -> str:
    """加载指定 skill 原文（模块级缓存；缺失/非法时抛错——宁可不优化也不发缩水版）。"""
    if skill in _skill_cache:
        return _skill_cache[skill]
    if not valid_skill_name(skill):
        raise ValueError(f"未知技能：{skill}（可用：{', '.join(available_skills()) or '无'}）")
    text = (_SKILLS_DIR / f"{skill}.SKILL.md").read_text(encoding="utf-8")
    _skill_cache[skill] = text
    return text


def supports_thinking_toggle(base_url: str) -> bool:
    """关闭思考的 thinking 字段是智谱 BigModel 写法，其他站点不下发（原版同款）。"""
    return "bigmodel.cn" in str(base_url or "")


def normalize_base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def valid_base_url(value: str) -> bool:
    url = normalize_base_url(value)
    if not (url.startswith(("http://", "https://")) and "://" in url and len(url) > len("https://")):
        return False
    return not is_local_infra_host(url)


def is_local_infra_host(value: str) -> bool:
    """拦截云厂商元数据地址等本机基础设施端点（防 SSRF 探测内网；mock/本地回环不受影响）。"""
    from urllib.parse import urlparse

    try:
        host = (urlparse(normalize_base_url(value)).hostname or "").lower()
    except ValueError:
        return True
    if host == "169.254.169.254" or host.endswith(".169.254.169.254"):
        return True
    if host == "metadata" or host.startswith("metadata.") or host.endswith(".metadata"):
        return True
    return False


def build_optimizer_user_content(task_type: str, prompt: str, assets: list[dict],
                                 duration: int, resolution: str, aspect_ratio: str,
                                 generate_audio: bool) -> str:
    """五段式用户输入。素材只传编号/类型/角色（没有多模态读取时不得声称看过素材）。"""
    lines = ["【本次优化任务】", f"任务模式（用户已在页面选择）：{TASK_LABEL.get(task_type, task_type)}"]
    if assets:
        lines.append("参考素材清单（仅编号清单，当前无法读取素材内容，不得假装已查看）：")
        for asset in assets:
            kind = str(asset.get("kind") or "")
            role = str(asset.get("role") or "")
            label = str(asset.get("label") or "") or KIND_LABEL.get(kind, "素材")
            role_text = f"（{ROLE_LABEL[role]}）" if role in ROLE_LABEL else ""
            lines.append(f"@{label}：{KIND_LABEL.get(kind, kind or '素材')}{role_text}")
    params = "、".join([
        f"总时长 {'自动（跟随原视频）' if duration == -1 else f'{duration} 秒'}",
        f"分辨率 {resolution}",
        f"画幅 {'自适应' if aspect_ratio == 'adaptive' else aspect_ratio}",
        "有声" if generate_audio else "无声",
    ])
    lines.append(f"页面生成参数（仅供规划，不得写入 Prompt）：{params}")
    lines.append("【原始提示词】")
    lines.append(str(prompt or "").strip())
    lines.append("【执行要求】")
    lines.append("按系统提示词的工作流输出优化后的 Prompt。低置信度分歧按合理假设保守处理，"
                 "不要向我提问。只输出 Prompt 正文本身，不要附加参数提示、素材提示、补充说明等"
                 "任何正文之外的行，不要使用代码围栏。")
    return "\n".join(lines)


def build_chat_body(model: str, user_content: str, disable_thinking: bool = False, skill: str = DEFAULT_SKILL) -> dict:
    body: dict = {
        "model": model,
        "stream": True,
        # 优化任务要干净正文；流式增量里忽略 reasoning_content。
        "messages": [
            {"role": "system", "content": system_rule_text(skill)},
            {"role": "user", "content": user_content},
        ],
    }
    if disable_thinking:
        body["thinking"] = {"type": "disabled"}
    return body


def new_sse_parser() -> dict:
    """增量 SSE 解析器状态（支持半包：一行被拆在两次 chunk 之间也能正确拼接）。"""
    return {"buffer": ""}


def feed_sse(state: dict, text: str) -> list[str]:
    """喂入一段 SSE 文本，返回其中解析出的正文增量列表（半包残留留在 buffer）。"""
    state["buffer"] += str(text or "")
    deltas: list[str] = []
    lines = state["buffer"].split("\n")
    state["buffer"] = lines.pop() or ""
    for line in lines:
        line = line.rstrip("\r")
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            import json

            delta = json.loads(payload).get("choices", [{}])[0].get("delta", {}).get("content")
        except (ValueError, IndexError, AttributeError, TypeError):
            continue
        if isinstance(delta, str) and delta:
            deltas.append(delta)
    return deltas
