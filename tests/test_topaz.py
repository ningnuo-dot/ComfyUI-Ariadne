"""Topaz 视频超分离线测试：契约纯函数 + mock 端到端 generate（零网络零费用）。"""
from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ariadne_core import kie as kie_core, topaz


class TopazContractTests(unittest.TestCase):
    def test_parse_factor_from_widget_label(self):
        self.assertEqual(topaz.parse_factor("1(修复增强)"), "1")
        self.assertEqual(topaz.parse_factor("2(2倍放大)"), "2")
        self.assertEqual(topaz.parse_factor("4(4倍放大)"), "4")
        self.assertEqual(topaz.parse_factor("4"), "4")
        with self.assertRaises(ValueError):
            topaz.parse_factor("8(8倍)")

    def test_compile_request_matches_official_fields(self):
        # 官方字段：video_url + upscale_factor（字符串枚举，OpenAPI）+ nsfw_checker（接入页，默认 true）。
        body = topaz.compile_request("https://example.com/a.mp4", "2")
        self.assertEqual(body, {"model": "topaz/video-upscale", "input": {
            "video_url": "https://example.com/a.mp4", "upscale_factor": "2", "nsfw_checker": True}})
        off = topaz.compile_request("https://example.com/a.mp4", "4", nsfw_checker=False)
        self.assertEqual(off["input"]["nsfw_checker"], False)

    def test_validate_source_extension_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            small = Path(tmp) / "a.mp4"
            small.write_bytes(b"\x00" * 16)
            topaz.validate_source(str(small))  # 不抛即过
            bad_ext = Path(tmp) / "b.avi"
            bad_ext.write_bytes(b"\x00")
            with self.assertRaisesRegex(RuntimeError, "MP4/MOV/MKV"):
                topaz.validate_source(str(bad_ext))
            missing = Path(tmp) / "c.mp4"
            with self.assertRaisesRegex(RuntimeError, "不存在"):
                topaz.validate_source(str(missing))
            # 体积上限：把常量压小模拟超限（不真造 50MB 文件）。
            big = Path(tmp) / "d.mov"
            big.write_bytes(b"\x00" * 64)
            with patch.object(topaz, "MAX_SOURCE_BYTES", 10):
                with self.assertRaisesRegex(RuntimeError, "50MB"):
                    topaz.validate_source(str(big))

    def test_estimate_cny_canvas_formula(self):
        # 画布版口径：1×/2× 每秒 8 credits、4× 14，单价 0.036 元。
        self.assertEqual(topaz.estimate_cny(10, "2"), 2.88)
        self.assertEqual(topaz.estimate_cny(10, "1"), 2.88)
        self.assertEqual(topaz.estimate_cny(10, "4"), 5.04)

    def test_poll_task_returns_credits_consumed(self):
        payload = {"data": {"state": "success", "resultJson": json.dumps({"resultUrls": ["https://x/y.mp4"]}),
                            "remainedCredits": 100, "creditsConsumed": 12}}

        class FakeResponse:
            status_code = 200

        with patch.object(kie_core, "request_json", return_value=(FakeResponse(), payload)), \
                patch("ariadne_core.kie.time.sleep"):
            result = kie_core.poll_task("t1", "KEY", poll_interval_seconds=0)
        self.assertEqual(result["resultUrls"], ["https://x/y.mp4"])
        self.assertEqual(result["creditsConsumed"], 12)
        self.assertEqual(result["remainedCredits"], 100)


class TopazNodeContractTests(unittest.TestCase):
    def test_input_types(self):
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "ariadne_nodes_topaz_contract", root / "nodes" / "topaz_node.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["ariadne_nodes_topaz_contract"] = module
        spec.loader.exec_module(module)
        schema = module.AriadneTopazUpscale.INPUT_TYPES()
        self.assertEqual(schema["required"]["source_video"][0], "VIDEO")
        # nsfw_checker 为官网接入页列出的合法字段（默认 true），必须有开关（画布版同款）。
        self.assertEqual(schema["required"]["nsfw_checker"][0], "BOOLEAN")
        self.assertTrue(schema["required"]["nsfw_checker"][1]["default"])
        self.assertTrue(schema["required"]["upscale_factor"][1]["default"].startswith("2"))


class TopazEndToEndMockTests(unittest.TestCase):
    """mock 网络层端到端：VIDEO 输入 → 校验 → 上传 → 建任务 → 轮询 → 落盘 → VIDEO 返回。"""

    def _load_node_module(self):
        comfy_api = types.ModuleType("comfy_api")
        comfy_latest = types.ModuleType("comfy_api.latest")

        class FakeVideoFromFile:
            def __init__(self, path):
                self.path = path

        class FakeInputImpl:
            VideoFromFile = staticmethod(FakeVideoFromFile)

        comfy_latest.InputImpl = FakeInputImpl
        comfy_api.latest = comfy_latest
        sys.modules.setdefault("comfy_api", comfy_api)
        sys.modules.setdefault("comfy_api.latest", comfy_latest)

        folder_paths = types.ModuleType("folder_paths")
        self.tmp_out = Path(tempfile.mkdtemp(prefix="ariadne-topaz-out-"))
        folder_paths.get_output_directory = lambda: str(self.tmp_out)
        sys.modules.setdefault("folder_paths", folder_paths)

        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location("ariadne_nodes_topaz", root / "nodes" / "topaz_node.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules["ariadne_nodes_topaz"] = module
        spec.loader.exec_module(module)
        return module

    def test_upscale_end_to_end_mock(self):
        module = self._load_node_module()
        node = module.AriadneTopazUpscale()

        source = Path(tempfile.mkdtemp(prefix="ariadne-topaz-in-")) / "src.mp4"
        source.write_bytes(b"\x00" * 32)  # 假 mp4：probe 失败 → 时长 0 → 估价显示未知（不阻断）

        class FakeVideo:
            def get_stream_source(self):
                return str(source)

        captured = {}

        def fake_upload(kind, path, api_key, **kwargs):
            captured["upload"] = (kind, path, api_key)
            return "https://kie.example/uploaded.mp4"

        def fake_create(body, api_key, phase="创建任务"):
            captured["body"] = body
            return "task_topaz_1"

        def fake_poll(task_id, api_key, poll_interval_seconds=5, timeout_seconds=1800, progress=None, fail_hints=None):
            captured["poll"] = (task_id, api_key)
            return {"state": "success", "resultUrls": ["https://kie.example/result.mp4"],
                    "remainedCredits": None, "creditsConsumed": 12}

        def fake_download(method, url, phase=""):
            captured["download"] = (method, url)
            return b"FAKE_UPSCALED"

        originals = (module.kie_core.upload_to_kie, module.kie_core.create_task, module.kie_core.poll_task,
                     module.request_bytes, module.config.resolve_kie_key)
        module.kie_core.upload_to_kie = fake_upload
        module.kie_core.create_task = fake_create
        module.kie_core.poll_task = fake_poll
        module.request_bytes = fake_download
        module.config.resolve_kie_key = lambda: "KEY"
        try:
            result = node.upscale(FakeVideo(), "4(4倍放大)", True, str(self.tmp_out))
        finally:
            (module.kie_core.upload_to_kie, module.kie_core.create_task, module.kie_core.poll_task,
             module.request_bytes, module.config.resolve_kie_key) = originals

        kind, path, api_key = captured["upload"]
        self.assertEqual((kind, path, api_key), ("video", str(source), "KEY"))
        # 请求体严格匹配官方字段（接入页三项 + 模型标识）。
        self.assertEqual(captured["body"], {"model": "topaz/video-upscale",
                                            "input": {"video_url": "https://kie.example/uploaded.mp4",
                                                      "upscale_factor": "4", "nsfw_checker": True}})
        self.assertEqual(captured["poll"], ("task_topaz_1", "KEY"))
        self.assertEqual(captured["download"], ("GET", "https://kie.example/result.mp4"))
        saved = self.tmp_out / "Topaz_task_topaz_1.mp4"
        self.assertEqual(saved.read_bytes(), b"FAKE_UPSCALED")
        video_output, info = result["result"]
        self.assertEqual(video_output.path, str(saved))
        self.assertIn("4倍放大", info)
        self.assertIn("实耗 12 credits", info)


if __name__ == "__main__":
    unittest.main()

    def test_parse_factor_accepts_clean_labels(self):
        """下拉值改用干净标签（无括号重复数字）后仍能解析；旧格式与裸倍数保持兼容。"""
        self.assertEqual(topaz.parse_factor("修复增强"), "1")
        self.assertEqual(topaz.parse_factor("2倍放大"), "2")
        self.assertEqual(topaz.parse_factor("4倍放大"), "4")
