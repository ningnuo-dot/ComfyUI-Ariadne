"""估价与 TOS 签名测试（全部确定性，不产生网络请求）。"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ariadne_core.seedance.pricing import estimate_ark_price, estimate_kie_credits, seedance_unit_rate
from ariadne_core.tos import presign_get


class ArkPricingTests(unittest.TestCase):
    def test_720p_standard_rate(self):
        # 720p 70 元/百万token：10 秒 720p24 = 1280*720*24*10/1024 = 0.216 百万token → 15.12 元。
        price = estimate_ark_price("720p", 10, includes_video=False)
        self.assertAlmostEqual(price, 15.12, places=2)

    def test_1080p_discount_window(self):
        before = datetime(2026, 9, 10, 0, 0, tzinfo=timezone.utc).timestamp()
        after = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc).timestamp()
        self.assertAlmostEqual(seedance_unit_rate("1080p", includes_video=False, now=before), 77 * 0.72, places=3)
        self.assertAlmostEqual(seedance_unit_rate("1080p", includes_video=False, now=after), 77.0, places=3)

    def test_unsupported_tier_returns_none(self):
        self.assertIsNone(estimate_ark_price("1080p", 10, model="seedance-2.0-mini"))

    def test_adaptive_without_input_unknown(self):
        self.assertIsNone(estimate_ark_price("720p", -1, includes_video=False))


class KiePricingTests(unittest.TestCase):
    def test_e7d40b79_billing_reproduction(self):
        # 实测回归（任务 e7d40b79…）：480p 含视频 17/秒，14 秒参考 + 4 秒输出 = 306。
        credits = estimate_kie_credits("480p", 4, includes_video=True, input_video_seconds=14)
        self.assertEqual(credits, 306)

    def test_adaptive_returns_none(self):
        self.assertIsNone(estimate_kie_credits("720p", -1))


class TosSignatureTests(unittest.TestCase):
    def test_presign_is_deterministic_and_wellformed(self):
        settings = {
            "accessKey": "AKTEST", "secretKey": "SKTEST",
            "bucket": "huoshan-yinpin", "region": "cn-shanghai", "endpoint": "tos-cn-shanghai.volces.com",
        }
        now = datetime(2026, 9, 12, 0, 0, 0, tzinfo=timezone.utc)
        url1 = presign_get(settings, "seedance/a.mp4", now)
        url2 = presign_get(settings, "seedance/a.mp4", now)
        self.assertEqual(url1, url2)
        self.assertTrue(url1.startswith("https://huoshan-yinpin.tos-cn-shanghai.volces.com/seedance/a.mp4?"))
        self.assertIn("X-Tos-Algorithm=TOS4-HMAC-SHA256", url1)
        self.assertIn("X-Tos-Date=20260912T000000Z", url1)
        self.assertIn("X-Tos-SignedHeaders=host", url1)
        self.assertIn("X-Tos-Signature=", url1)

    def test_presign_changes_with_expiry(self):
        settings = {"accessKey": "AK", "secretKey": "SK", "bucket": "b", "region": "r", "endpoint": "e"}
        now = datetime(2026, 9, 12, tzinfo=timezone.utc)
        self.assertNotEqual(presign_get(settings, "k", now, 3600), presign_get(settings, "k", now, 7200))


if __name__ == "__main__":
    unittest.main()
