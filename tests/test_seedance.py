"""Seedance 契约层测试（画布插件 74 项 fixture 的关键子集翻译；全部离线不产生任何调用）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ariadne_core.seedance.compile import compile_annotation_block, compile_prompt, compile_references, compile_request
from ariadne_core.seedance.contract import SeedanceAsset, SeedanceJobSpec
from ariadne_core.seedance.validate import validate_job


def spec(**overrides) -> SeedanceJobSpec:
    base = dict(
        task_type="auto", prompt="测试提示词", assets=[], duration=10,
        resolution="720p", aspect_ratio="9:16", generate_audio=True, output_format="mp4",
    )
    base.update(overrides)
    return SeedanceJobSpec(**base)


class CompileTests(unittest.TestCase):
    def test_reference_numbering_by_kind(self):
        assets = [
            SeedanceAsset("image", "character", "u1"),
            SeedanceAsset("video", "motion", "v1"),
            SeedanceAsset("image", "scene", "u2"),
            SeedanceAsset("audio", "audio", "a1"),
        ]
        refs = compile_references(assets)
        self.assertEqual([r["reference"] for r in refs], ["@图像1", "@视频1", "@图像2", "@音频1"])

    def test_first_last_frames_not_numbered(self):
        assets = [
            SeedanceAsset("image", "first-frame", "f"),
            SeedanceAsset("image", "last-frame", "l"),
            SeedanceAsset("image", "character", "u1"),
        ]
        refs = compile_references(assets)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["reference"], "@图像1")

    def test_prompt_label_translation_and_duty(self):
        assets = [SeedanceAsset("image", "character", "u1", label="@图片1")]
        refs = compile_references(assets)
        text = compile_prompt("@图片1用于模特的五官", refs)
        self.assertIn("@图像1用于模特的五官", text)
        self.assertIn("@图像1提供人物外观与服装", text)

    def test_prompt_without_labels_still_gets_duty(self):
        # 与 TS 行为对齐：即使提示词没写标签，场景素材也追加职责句（角色在场景/人物等五类时）。
        refs = compile_references([SeedanceAsset("image", "scene", "u1")])
        self.assertEqual(compile_prompt("一只猫", refs), "一只猫\n素材职责：@图像1提供场景结构、光线与构图。")

    def test_annotation_block_binds_timestamp(self):
        assets = [
            SeedanceAsset("video", "motion", "v1"),
            SeedanceAsset("image", "annotation", "f1", timestamp_seconds=0.0),
            SeedanceAsset("image", "annotation", "f2", timestamp_seconds=12.4),
        ]
        refs = compile_references(assets)
        block = compile_annotation_block("edit", refs)
        self.assertIn("@图像1 是 @视频1 开头的标注帧", block)
        self.assertIn("@图像2 是 @视频1 第12秒的标注帧", block)
        self.assertIn("不得出现任何标注笔迹", block)
        self.assertEqual(compile_annotation_block("auto", refs), "")

    def test_request_assembly_roles_and_body(self):
        s = spec(
            task_type="reference",
            assets=[
                SeedanceAsset("image", "first-frame", "f"),
                SeedanceAsset("image", "last-frame", "l"),
                SeedanceAsset("image", "character", "u1", label="@图片1"),
            ],
            aspect_ratio="adaptive",
        )
        request = compile_request(s)
        body = request["body"]
        self.assertEqual(body["model"], "doubao-seedance-2-5-260628")
        self.assertEqual(body["ratio"], "adaptive")
        self.assertEqual(body["duration"], 10)
        self.assertEqual(body["omni_reference_task_type"], "reference")
        types = [item["type"] for item in body["content"]]
        self.assertEqual(types, ["text", "image_url", "image_url", "image_url"])
        roles = [item.get("role") for item in body["content"][1:]]
        self.assertEqual(roles, ["first_frame", "last_frame", "reference_image"])


class ValidateTests(unittest.TestCase):
    def test_text_mode_rejects_assets(self):
        errors = validate_job(spec(task_type="text", assets=[SeedanceAsset("image", "scene", "u")]))
        self.assertTrue(any("文生视频不能包含参考素材" in e for e in errors))

    def test_edit_requires_trigger_duration_and_single_video(self):
        s = spec(task_type="edit", duration=10, aspect_ratio="adaptive",
                 assets=[SeedanceAsset("video", "motion", "v")])
        errors = validate_job(s)
        self.assertTrue(any("-1" in e for e in errors))
        self.assertTrue(any("触发词" in e for e in errors))
        s2 = spec(task_type="edit", duration=-1, aspect_ratio="adaptive",
                  prompt="把外套编辑成红色", assets=[SeedanceAsset("video", "motion", "v")])
        self.assertEqual(validate_job(s2), [])

    def test_edit_rejects_two_videos(self):
        s = spec(task_type="edit", duration=-1, prompt="修改", aspect_ratio="adaptive",
                 assets=[SeedanceAsset("video", "motion", "v1"), SeedanceAsset("video", "motion", "v2")])
        self.assertTrue(any("只支持 1 段" in e for e in validate_job(s)))

    def test_first_last_mode(self):
        s = spec(task_type="first-last", aspect_ratio="adaptive",
                 assets=[SeedanceAsset("image", "first-frame", "f"), SeedanceAsset("image", "last-frame", "l")])
        self.assertEqual(validate_job(s), [])
        bad = spec(task_type="first-last", aspect_ratio="9:16",
                   assets=[SeedanceAsset("image", "last-frame", "l")])
        errors = validate_job(bad)
        self.assertTrue(any("adaptive" in e for e in errors))
        self.assertTrue(any("尾帧必须和首帧一起提供" in e for e in errors))

    def test_annotation_only_in_edit(self):
        s = spec(task_type="auto", assets=[SeedanceAsset("image", "annotation", "f")])
        self.assertTrue(any("标注帧只能在视频编辑模式" in e for e in validate_job(s)))

    def test_asset_limits(self):
        images = [SeedanceAsset("image", "character", f"u{i}") for i in range(31)]
        self.assertTrue(any("参考图片最多 30 张" in e for e in validate_job(spec(assets=images))))
        videos = [SeedanceAsset("video", "motion", f"v{i}") for i in range(11)]
        self.assertTrue(any("参考视频最多 10 段" in e for e in validate_job(spec(assets=videos))))

    def test_duration_range(self):
        self.assertTrue(any("4-30 秒" in e for e in validate_job(spec(duration=3))))
        self.assertTrue(any("4-30 秒" in e for e in validate_job(spec(duration=31))))


if __name__ == "__main__":
    unittest.main()
