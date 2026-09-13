"""离线运行时测试：真实 ffmpeg 媒体操作（不产生任何网络请求/费用）+ mock 端到端 generate。"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ariadne_core import media


def _make_test_video(path: Path, seconds: float = 4.0, size: str = "480x854") -> Path:
    """ffmpeg testsrc 生成测试视频（480×854 = 410,040 像素，过官方像素线）。"""
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24:duration={seconds}",
        "-pix_fmt", "yuv420p", str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    return path


class MediaOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ariadne-media-"))
        cls.video = _make_test_video(cls.tmp / "test.mp4")

    def test_probe_video(self):
        info = media.probe_video(str(self.video))
        self.assertEqual((info["width"], info["height"]), (480, 854))
        self.assertAlmostEqual(info["seconds"], 4.0, delta=0.2)
        self.assertEqual(info["pixels"], 480 * 854)
        self.assertGreaterEqual(info["pixels"], 407696)  # 官方像素线下限

    def test_validate_video_pixels_pass_and_fail(self):
        from ariadne_core.seedance.ark_media import validate_video_pixels

        info = validate_video_pixels(str(self.video), "测试")
        self.assertEqual(info["width"], 480)
        small = _make_test_video(self.tmp / "small.mp4", size="320x240")  # 76,800 像素，低于 407,696
        with self.assertRaises(RuntimeError) as ctx:
            validate_video_pixels(str(small), "测试小图")
        self.assertIn("尺寸过小", str(ctx.exception))

    def test_trim_single_range(self):
        out = media.trim_video(str(self.video), [[0.0, 2.0]], str(self.tmp), "test.mp4")
        info = media.probe_video(out)
        self.assertAlmostEqual(info["seconds"], 2.0, delta=0.4)

    def test_trim_multi_range_concat(self):
        out = media.trim_video(str(self.video), [[0.0, 1.0], [2.0, 3.0]], str(self.tmp), "test.mp4")
        info = media.probe_video(out)
        self.assertAlmostEqual(info["seconds"], 2.0, delta=0.6)

    def test_trim_empty_ranges_rejected(self):
        with self.assertRaises(RuntimeError):
            media.trim_video(str(self.video), [[3.5, 1.0]], str(self.tmp), "test.mp4")

    def test_detect_cut_points(self):
        # testsrc 自带画面变化；至少不应崩溃且返回有序列表。
        points = media.detect_cut_points(str(self.video))
        self.assertTrue(all(0 < point < 4 for point in points))

    def test_image_to_file_roundtrip(self):
        import numpy as np
        from PIL import Image

        tensor = np.zeros((1, 32, 48, 3), dtype=np.float32)
        tensor[..., 0] = 1.0  # 纯红
        path = media.image_to_file(tensor)
        image = Image.open(path)
        self.assertEqual(image.size, (48, 32))
        self.assertEqual(image.getpixel((0, 0))[0], 255)

    def test_audio_to_wav(self):
        import torch

        audio = {"waveform": torch.zeros(1, 1, 1600), "sample_rate": 16000}
        path = media.audio_to_wav(audio)
        self.assertGreater(Path(path).stat().st_size, 44)


class MockEndToEndTests(unittest.TestCase):
    """mock 网络层的端到端 generate()：瓦片资产组装 → 编译 → 假提交 → 落盘 → VIDEO 返回。

    绝不触网：run_ark_seedance / request_bytes 被替换为内存假实现。
    """

    def _load_node_module(self):
        root = Path(__file__).resolve().parent.parent
        # 桩掉 ComfyUI 专属模块，使节点模块可在测试进程导入。
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
        self.tmp_out = Path(tempfile.mkdtemp(prefix="ariadne-out-"))
        self.tmp_in = Path(tempfile.mkdtemp(prefix="ariadne-in-"))
        (self.tmp_in / "ariadne" / "image").mkdir(parents=True, exist_ok=True)
        folder_paths.get_output_directory = lambda: str(self.tmp_out)
        folder_paths.get_input_directory = lambda: str(self.tmp_in)
        sys.modules.setdefault("folder_paths", folder_paths)

        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "ariadne_nodes_seedance", root / "nodes" / "seedance25_node.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["ariadne_nodes_seedance"] = module
        spec.loader.exec_module(module)
        return module

    def test_generate_end_to_end_mock(self):
        module = self._load_node_module()
        node = module.AriadneSeedance25Video()

        # 预置一张瓦片素材（真实落盘到 input 目录，走完整 _resolve_input_path）。
        import numpy as np
        from PIL import Image

        buffer = io.BytesIO()
        Image.fromarray(np.zeros((854, 480, 3), dtype=np.uint8)).save(buffer, format="PNG")
        tile_name = "mock-ref.png"
        (self.tmp_in / "ariadne" / "image" / tile_name).write_bytes(buffer.getvalue())
        tiles = [{"kind": "image", "name": tile_name, "subfolder": "ariadne/image", "role": "character", "seconds": 0}]

        captured = {}

        def fake_run_ark(spec, request_body, api_key, *args, **kwargs):
            captured["spec"] = spec
            captured["body"] = request_body
            return {"taskId": "cmock-1", "videoUrl": "memory://fake.mp4"}

        def fake_download(method, url, phase=""):
            return b"FAKE_MP4_BYTES"

        original_run = module.run_ark_seedance
        original_download = module.request_bytes
        original_key = module.config.resolve_ark_key
        original_tos = module.config.tos_settings
        module.run_ark_seedance = fake_run_ark
        module.request_bytes = fake_download
        module.config.resolve_ark_key = lambda: "KEY"
        module.config.tos_settings = lambda: None  # 隔离真实 config.local.json：用户配置 TOS 后小图不得真传桶
        try:
            result = node.generate(
                prompt="@图片1 站在阳台上", task_type="auto(全能参考)", duration=10,
                resolution="720p", aspect_ratio="9:16", generate_audio=True,
                output_format="mp4", channel="ark(火山方舟直连)", download_folder=str(self.tmp_out),
                ariadne_assets=json.dumps(tiles),
            )
        finally:
            module.run_ark_seedance = original_run
            module.request_bytes = original_download
            module.config.resolve_ark_key = original_key
            module.config.tos_settings = original_tos

        spec, body = captured["spec"], captured["body"]
        # 编号与职责句编译真实生效。
        self.assertEqual(spec.assets[0].label, "@图片1")
        self.assertIn("@图像1", body["content"][0]["text"])
        self.assertIn("素材职责：@图像1提供人物外观与服装", body["content"][0]["text"])
        # 归一化把本地文件转成了 data URL（无 TOS 配置、小图）。
        self.assertTrue(spec.assets[0].url.startswith("data:image/png;base64,"))
        # 成片真实落盘 + VIDEO 返回（FakeVideoFromFile 路径 = 落盘路径）。
        saved = self.tmp_out / "Seedance版_cmock-1.mp4"
        self.assertEqual(saved.read_bytes(), b"FAKE_MP4_BYTES")
        video_output, info = result["result"]
        self.assertEqual(video_output.path, str(saved))
        self.assertIn("Seedance 2.5 完成", info)
        self.assertIn("预估费用", info)

    def test_generate_free_variant_no_role_duties(self):
        """自由引用版：图像只编号不加职责句，身份由提示词手工指定。"""
        module = self._load_node_module()
        node = module.AriadneSeedance25Free()

        import numpy as np
        import torch
        from PIL import Image

        buffer = io.BytesIO()
        Image.fromarray(np.zeros((64, 64, 3), dtype=np.uint8)).save(buffer, format="PNG")
        buffer.seek(0)
        image_1 = torch.from_numpy(np.array(Image.open(buffer).convert("RGB"))).float().unsqueeze(0) / 255.0

        captured = {}

        def fake_run_ark(spec, request_body, api_key, *args, **kwargs):
            captured["spec"] = spec
            captured["body"] = request_body
            return {"taskId": "cfree-1", "videoUrl": "memory://fake.mp4"}

        original_run = module.run_ark_seedance
        original_download = module.request_bytes
        original_key = module.config.resolve_ark_key
        original_tos = module.config.tos_settings
        module.run_ark_seedance = fake_run_ark
        module.request_bytes = lambda *args, **kwargs: b"FAKE_MP4_BYTES"
        module.config.resolve_ark_key = lambda: "KEY"
        module.config.tos_settings = lambda: None
        try:
            result = node.generate(
                prompt="@图片1 站在阳台上", task_type="auto(全能参考)", duration=5,
                resolution="480p", aspect_ratio="adaptive", generate_audio=True,
                output_format="mp4", channel="ark(火山方舟直连)", download_folder=str(self.tmp_out),
                ariadne_assets="[]", image_1=image_1,
            )
        finally:
            module.run_ark_seedance = original_run
            module.request_bytes = original_download
            module.config.resolve_ark_key = original_key
            module.config.tos_settings = original_tos

        spec, body = captured["spec"], captured["body"]
        self.assertEqual(spec.assets[0].role, "free")
        self.assertEqual(spec.assets[0].label, "@图片1")
        self.assertIn("@图像1 站在阳台上", body["content"][0]["text"])
        # 自由引用版：只编号，不生成素材职责句（身份/职责由用户手工写在提示词里）。
        self.assertNotIn("素材职责", body["content"][0]["text"])
        ref_items = [c for c in body["content"] if c.get("type") == "image_url"]
        self.assertEqual(len(ref_items), 1)
        self.assertEqual(ref_items[0]["role"], "reference_image")

    def test_generate_rejects_invalid_tiles_before_any_network(self):
        module = self._load_node_module()
        node = module.AriadneSeedance25Video()
        tiles = [{"kind": "image", "name": "ghost.png", "subfolder": "ariadne/image", "role": "character"}]
        with self.assertRaises(RuntimeError) as ctx:
            node.generate(
                prompt="x", task_type="auto(全能参考)", duration=10, resolution="720p",
                aspect_ratio="9:16", generate_audio=True, output_format="mp4",
                channel="ark(火山方舟直连)", download_folder=str(self.tmp_out),
                ariadne_assets=json.dumps(tiles),
            )
        self.assertIn("素材文件不存在", str(ctx.exception))

    def test_generate_validation_blocks_before_network(self):
        module = self._load_node_module()
        node = module.AriadneSeedance25Video()
        with self.assertRaises(RuntimeError) as ctx:
            node.generate(
                prompt="", task_type="text(文生视频)", duration=3, resolution="720p",
                aspect_ratio="9:16", generate_audio=True, output_format="mp4",
                channel="ark(火山方舟直连)", download_folder=str(self.tmp_out), ariadne_assets="[]",
            )
        self.assertIn("校验失败", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
