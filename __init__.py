"""ComfyUI-Ariadne：Ariadne 视频家族 ComfyUI 节点包。

- Ariadne · Seedance 2.5（火山方舟直连 + Kie 双渠道，@引用契约/素材职责句/校验/估价全量移植）
- Ariadne · Veo 3.1（Kie）
- Ariadne · 可灵 Kling 3.0（Kie，元素/多镜头）
- Ariadne · Kie 图生图（五家服务商）

Omni 不在本包：官方 Interactions API 已有核心 partner 节点（comfy_api_nodes/nodes_gemini.py
GeminiVideoOmniV2）与本机 ComfyUI-Kie 包 KieOmniVideo 两条现成路线，不重复造轮子。

自有路由：/ariadne/upload|trim|estimate|config|tos_test|optimize（loopback 限定 + 幂等注册）。
密钥：config.local.json（gitignore）或 ARK_API_KEY/KIE_API_KEY 环境变量。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SOURCE = Path(__file__).resolve().parent
if str(_SOURCE) not in sys.path:
    sys.path.insert(0, str(_SOURCE))


def _load(name: str):
    """以唯一模块名按路径加载节点模块（避免与宿主顶层模块名冲突，Kie 包同款）。"""
    py = _SOURCE / "nodes" / f"{name}.py"
    mod_name = f"{_SOURCE.name}__nodes__{name}"
    spec = importlib.util.spec_from_file_location(mod_name, py)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


_seedance = _load("seedance25_node")
_veo = _load("veo31_node")
_kling = _load("kling_node")
_image = _load("image_node")

NODE_CLASS_MAPPINGS = {}
NODE_CLASS_MAPPINGS.update(_seedance.NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_veo.NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_kling.NODE_CLASS_MAPPINGS)
NODE_CLASS_MAPPINGS.update(_image.NODE_CLASS_MAPPINGS)

NODE_DISPLAY_NAME_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS.update(_seedance.NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_veo.NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_kling.NODE_DISPLAY_NAME_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_image.NODE_DISPLAY_NAME_MAPPINGS)

WEB_DIRECTORY = "./web/js"

__version__ = "0.1.0"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY", "__version__"]

def _load_root(name: str):
    """按唯一模块名加载包根模块（防 sys.modules["routes"] 等顶层名冲突/劫持）。"""
    py = _SOURCE / f"{name}.py"
    mod_name = f"{_SOURCE.name}__{name}"
    spec = importlib.util.spec_from_file_location(mod_name, py)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


try:
    _load_root("routes").register_routes()
except ImportError:
    pass  # 无 PromptServer 环境（单测/语法检查）跳过路由注册
except Exception as _routes_error:  # noqa: BLE001 - 路由注册失败必须留痕（端点静默 404 最难查）
    import logging

    logging.warning("[ComfyUI-Ariadne] 自有路由注册失败（/ariadne/* 不可用）：%s", _routes_error)
