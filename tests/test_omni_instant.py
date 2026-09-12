"""Omni（Kie）与一瞬入画契约层测试（全离线）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ariadne_core import instant, omni


class OmniRoleTests(unittest.TestCase):
    def test_reference_mode_numbering(self):
        roles = omni.build_media_roles(has_character=True, scene_count=2, has_video=True, has_character_id=True)
        self.assertIn("<IMAGE_REF_0> is the character and outfit reference", roles[0])
        self.assertIn("<IMAGE_REF_1> is scene reference 1", roles[1])
        self.assertIn("<IMAGE_REF_2> is scene reference 2", roles[2])
        self.assertIn("<VIDEO_REF_0> is the motion, camera, and timing reference", roles[3])
        self.assertIn("<CHARACTER_ID_0> is the fixed identity", roles[4])

    def test_first_last_mode(self):
        roles = omni.build_media_roles(False, 0, False, False, has_first=True, has_last=True)
        self.assertEqual(len(roles), 2)
        self.assertTrue(roles[0].startswith("<FIRST_FRAME>"))
        self.assertTrue(roles[1].startswith("<LAST_FRAME>"))
        only_first = omni.build_media_roles(False, 0, False, False, has_first=True)
        self.assertEqual(len(only_first), 1)

    def test_compile_input_fields_and_prompt(self):
        data = omni.compile_input(
            "测试提示词", "9:16", "1080p", "10",
            has_character=True, scene_count=1, has_video=True, has_character_id=True,
            image_urls=["c", "s1"], character_ids=["char1"],
            video_list=[{"url": "v", "start": 0.0, "ends": 10.0}], seed=42,
        )
        self.assertEqual(data["duration"], "10")  # Kie 要求字符串
        self.assertEqual(data["image_urls"], ["c", "s1"])
        self.assertEqual(data["character_ids"], ["char1"])
        self.assertEqual(data["video_list"][0]["ends"], 10.0)
        self.assertEqual(data["seed"], 42)
        self.assertTrue(data["prompt"].startswith("<IMAGE_REF_0>"))
        self.assertTrue(data["prompt"].endswith("测试提示词"))

    def test_first_last_exclusive(self):
        with self.assertRaises(RuntimeError):
            omni.compile_input("x", "9:16", "1080p", "8", first_frame_url="f", image_urls=["c"])

    def test_enum_validation(self):
        for kwargs in ({"aspect_ratio": "1:1"}, {"resolution": "480p"}, {"duration": "5"}):
            with self.assertRaises(RuntimeError):
                omni.compile_input("x", kwargs.get("aspect_ratio", "9:16"), kwargs.get("resolution", "720p"), kwargs.get("duration", "8"))


class OmniPricingTests(unittest.TestCase):
    def test_no_video_input_table(self):
        self.assertEqual(omni.estimate_omni(4, "1080p", False, False)["credits"], 45)
        self.assertEqual(omni.estimate_omni(10, "4k", False, False)["credits"], 150)

    def test_round_up_takes_expensive_tier(self):
        result = omni.estimate_omni(5, "720p", False, False)
        self.assertEqual(result["credits"], 60)  # 5s 无档 → 取 6s 档
        self.assertEqual(result["rounded_up_duration"], 6)

    def test_with_video_input_flat_and_upper_bound(self):
        self.assertEqual(omni.estimate_omni(8, "1080p", True, False)["credits"], 120)
        only_images = omni.estimate_omni(8, "1080p", False, True)
        self.assertEqual(only_images["credits"], 120)
        self.assertTrue(only_images["upper_bound"])
        self.assertEqual(omni.estimate_omni(8, "4k", True, False)["credits"], 180)


class InstantTests(unittest.TestCase):
    def test_fidelity_prompt_scene_mode(self):
        text = instant.build_fidelity_prompt("9:16", "scene", "", 3)
        self.assertIn("strictly from the 3 labeled reference image(s)", text)
        self.assertIn("No people or human figures", text)
        self.assertIn("9:16 portrait", text)
        self.assertIn("no watermark, no logo, no text", text)

    def test_fidelity_prompt_keep_people_mode(self):
        text = instant.build_fidelity_prompt("16:9", "keep_people", "sunset lighting", 2)
        self.assertIn("Preserve population composition exactly as shown", text)
        self.assertIn("16:9 landscape", text)
        self.assertIn("Extra user constraints: sunset lighting", text)

    def test_validation(self):
        with self.assertRaises(RuntimeError):
            instant.build_fidelity_prompt("1:1", "scene", "", 2)
        with self.assertRaises(RuntimeError):
            instant.build_fidelity_prompt("9:16", "scene", "", 0)
        with self.assertRaises(RuntimeError):
            instant.compile_input([], "p", "9:16", "2K")
        with self.assertRaises(RuntimeError):
            instant.compile_input(["u"], "p", "3:2", "2K")


if __name__ == "__main__":
    unittest.main()
