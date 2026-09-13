"""Kie 渠道 / Veo / 可灵 / 图生图注册表 / 方舟错误翻译 / 配置脱敏测试（全离线）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ariadne_core import config, kling, providers, veo31
from ariadne_core.seedance.contract import SeedanceAsset, SeedanceJobSpec
from ariadne_core.seedance.kie_channel import compile_kie_prompt, compile_kie_request


class SeedanceKieChannelTests(unittest.TestCase):
    def spec(self, **kw) -> SeedanceJobSpec:
        base = dict(task_type="auto", prompt="测试", assets=[], duration=10, resolution="720p",
                    aspect_ratio="9:16", generate_audio=True, output_format="mp4")
        base.update(kw)
        return SeedanceJobSpec(**base)

    def test_prompt_compiles_to_kie_prefix(self):
        assets = [SeedanceAsset("image", "character", "u1", label="@图片1"), SeedanceAsset("video", "motion", "v1")]
        text = compile_kie_prompt("@图片1用于模特", assets)
        self.assertIn("@Image1用于模特", text)
        self.assertIn("@Image1提供人物外观与服装", text)
        self.assertIn("@Video1提供动作、运镜与节奏", text)

    def test_kie_duty_numbering_with_free_assets_first(self):
        """无职责素材（free）排在职责素材之前时，职责句编号必须跟着替换编号走（2026-09-14 回归）。"""
        assets = [
            SeedanceAsset("image", "free", "u0", label="@图片1"),
            SeedanceAsset("image", "character", "u1", label="@图片2"),
        ]
        text = compile_kie_prompt("@图片1氛围参照，@图片2是模特", assets)
        self.assertIn("@Image2提供人物外观与服装", text)
        self.assertNotIn("@Image1提供", text)

    def test_input_whitelist_and_fields(self):
        s = self.spec(assets=[SeedanceAsset("image", "character", "u1")])
        request = compile_kie_request(s)
        self.assertEqual(request["model"], "bytedance/seedance-2-5")
        input_data = request["input"]
        self.assertEqual(input_data["reference_image_urls"], ["u1"])
        self.assertEqual(input_data["duration"], 10)
        self.assertEqual(set(input_data) - {"prompt", "aspect_ratio", "resolution", "duration",
                                            "generate_audio", "output_format", "reference_image_urls"}, set())

    def test_first_last_frames_not_numbered_parity_with_ark(self):
        # P0 回归钉子：Kie 渠道首尾帧同样不占编号（与方舟 compile_references 对齐），
        # 否则首尾帧任务里 @ImageN 与 reference_image_urls 错位、引用悬空照扣费。
        s = self.spec(
            task_type="first-last",
            assets=[
                SeedanceAsset("image", "first-frame", "f"),
                SeedanceAsset("image", "last-frame", "l"),
                SeedanceAsset("image", "character", "c1", label="@图片1"),
            ],
        )
        text = compile_kie_prompt(s.prompt, s.assets)
        self.assertIn("@Image1", text)
        self.assertNotIn("@Image2", text)
        self.assertNotIn("@Image3", text)

    def test_edit_and_extend_rejected(self):
        for task_type in ("edit", "extend"):
            with self.assertRaises(RuntimeError) as ctx:
                compile_kie_request(self.spec(task_type=task_type))
            self.assertIn("Kie 未开通", str(ctx.exception))

    def test_adaptive_rejected(self):
        with self.assertRaises(RuntimeError):
            compile_kie_request(self.spec(duration=-1))


class VeoTests(unittest.TestCase):
    def test_generate_compile(self):
        body = veo31.compile_generate_request({
            "taskType": "reference", "prompt": "测试", "assets": [{"url": "u1"}, {"url": "u2"}],
            "model": "veo3_fast", "duration": 8, "resolution": "1080p", "aspectRatio": "16:9", "watermark": "",
        })
        self.assertEqual(body["generationType"], "REFERENCE_2_VIDEO")
        self.assertEqual(body["imageUrls"], ["u1", "u2"])
        self.assertEqual(body["aspect_ratio"], "16:9")
        self.assertNotIn("watermark", body)

    def test_extend_model_mapping_and_validation(self):
        body = veo31.compile_extend_request({
            "taskType": "extend", "prompt": "续", "model": "veo3_fast", "extendTaskId": " t1 ",
            "assets": [], "duration": 8, "resolution": "1080p", "aspectRatio": "16:9",
        })
        self.assertEqual(body["model"], "fast")
        self.assertEqual(body["taskId"], "t1")
        with self.assertRaises(RuntimeError):
            veo31.compile_extend_request({"model": "veo3", "extendTaskId": "", "prompt": "x"})

    def test_estimate_unknown_combo_returns_none(self):
        self.assertIsNone(veo31.estimate_veo_credits("text", "veo3_fast", "720p"))  # 价目表未列
        self.assertEqual(veo31.estimate_veo_credits("text", "veo3", "720p"), 225)
        self.assertEqual(veo31.estimate_veo_credits("extend", "veo3_lite", "720p"), 15)


class KlingTests(unittest.TestCase):
    def test_multi_shot_duration_sum_and_prompt_omitted(self):
        body = kling.compile_request({
            "taskType": "multi-shot", "prompt": "x", "elements": [], "duration": 5,
            "aspectRatio": "9:16", "sound": True, "qualityMode": "std",
            "shots": [{"prompt": "镜1", "duration": 3}, {"prompt": "镜2", "duration": 4}],
        })
        self.assertEqual(body["input"]["duration"], "7")
        self.assertTrue(body["input"]["multi_shots"])
        self.assertNotIn("prompt", body["input"])

    def test_element_mapping_binary(self):
        body = kling.compile_request({
            "taskType": "omni", "prompt": "@角色1 走路", "elements": [
                {"name": "角色1", "imageUrls": ["a.jpg", "b.jpg"]},
                {"name": "动作1", "videoUrl": "v.mp4"},
                {"name": "坏的"},  # 无素材 → 丢弃
            ],
            "duration": 5, "aspectRatio": "9:16", "sound": False, "qualityMode": "pro",
        })
        elements = body["input"]["kling_elements"]
        self.assertEqual(len(elements), 2)
        self.assertEqual(elements[0]["element_input_urls"], ["a.jpg", "b.jpg"])
        self.assertEqual(elements[1]["element_input_video_urls"], ["v.mp4"])

    def test_duration_bounds(self):
        with self.assertRaises(RuntimeError):
            kling.compile_request({"taskType": "text", "prompt": "x", "elements": [], "duration": 16,
                                   "sound": True, "qualityMode": "std"})

    def test_estimate(self):
        self.assertEqual(kling.estimate_kie(10)["usd"], 0.7)
        self.assertEqual(kling.estimate_kie(10)["credits"], 140)  # 14 credits/秒 × 10s


class ProvidersTests(unittest.TestCase):
    def test_ref_field_differs_by_provider(self):
        self.assertEqual(providers.get_provider("kie-nano-banana-pro")["ref_field"], "image_input")
        self.assertEqual(providers.get_provider("kie-seedream-5-pro")["ref_field"], "image_urls")
        self.assertEqual(providers.get_provider("kie-gpt-image-2")["ref_field"], "input_urls")

    def test_alias_and_unknown(self):
        self.assertEqual(providers.get_provider("nano-banana-pro")["key"], "kie-nano-banana-pro")
        with self.assertRaises(ValueError):
            providers.get_provider("no-such")

    def test_resolution_mapping(self):
        provider = providers.get_provider("kie-seedream-5-pro")
        self.assertEqual(providers.resolve_resolution(provider, "high"), "high")
        self.assertEqual(providers.resolve_resolution(provider, "1K"), "basic")
        self.assertIsNone(providers.resolve_resolution(providers.get_provider("kie-grok-imagine-2"), "2K"))


class ArkErrorTests(unittest.TestCase):
    def _fake_response(self, status, text):
        class FakeResponse:
            status_code = status

            @property
            def text(self):
                return text

        return FakeResponse()

    def test_pixel_error_translated_with_number(self):
        from ariadne_core.seedance.ark import read_ark_error

        body = {"content": [
            {"type": "text", "text": "x"},
            {"type": "video_url", "video_url": {"url": "http://x/v.mp4"}, "role": "reference_video"},
        ]}
        error = read_ark_error(
            self._fake_response(400, '{"error":{"message":"content[1]: video pixel count must be greater than or equal to 407696"}}'),
            {"message": "content[1]: video pixel count must be greater than or equal to 407696"},
            body,
        )
        self.assertIn("@视频1 参考视频尺寸过小", str(error))
        self.assertIn("407696", str(error))

    def test_sensitive_person_translated(self):
        from ariadne_core.seedance.ark import read_ark_error

        payload = {"error": {"code": "InputImageSensitiveContentDetected.PrivacyInformation", "message": "real person"}}
        error = read_ark_error(self._fake_response(400, "x"), payload, {"content": [{"type": "text", "text": "x"}, {"type": "image_url", "image_url": {"url": "u"}}]})
        self.assertIn("疑似包含真人面孔", str(error))
        self.assertIn("非真人素材", str(error))


class ConfigTests(unittest.TestCase):
    def test_masked_config_hides_secrets(self):
        masked = config.masked_config({"ark_api_key": "abcd1234efgh5678", "kie_api_key": "", "tos": {"accessKey": "short"}})
        self.assertEqual(masked["ark_api_key"], "abcd****78")
        self.assertEqual(masked["tos"]["accessKey"], "****")

    def test_save_empty_does_not_wipe(self, ):
        # 用临时文件模拟（不触碰真实 config.local.json）。
        import json
        import tempfile

        original = config.CONFIG_PATH
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.local.json"
                path.write_text(json.dumps({"kie_api_key": "keep-me"}), encoding="utf-8")
                config.CONFIG_PATH = path
                config.save_config({"kie_api_key": ""})
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["kie_api_key"], "keep-me")
        finally:
            config.CONFIG_PATH = original


if __name__ == "__main__":
    unittest.main()
