"""提示词优化契约层单测：系统规则原文存在、五段式输入、SSE 半包/停止语义、base_url 校验。"""
from __future__ import annotations

import unittest

from ariadne_core.seedance import optimizer


class SystemRuleTests(unittest.TestCase):
    def test_skill_file_present_and_full(self):
        """权威系统规则必须以原文迁移（非手写缩水版）：关键章节 + 体量下限。"""
        text = optimizer.system_rule_text("sd25-pe")
        self.assertIn("# Seedance 2.5 Prompt Optimizer", text)
        self.assertIn("## 不可违反的原则", text)
        self.assertIn("## 视频生成模板", text)
        self.assertIn("## 视频编辑模板", text)
        self.assertIn("## 视频延长模板", text)
        self.assertIn("## 最终自检", text)
        self.assertGreater(len(text), 20000)  # 原文约 7 万字节，缩水版到不了这个量级

    def test_skill_per_node_type_architecture(self):
        """skill 按节点类型区分：目录白名单 + 非法名拒绝 + 缺失拒绝。"""
        self.assertIn("sd25-pe", optimizer.available_skills())
        self.assertTrue(optimizer.valid_skill_name("sd25-pe"))
        for bad in ("../evil", "sd25-pe.SKILL", "Missing-Skill", "sd25_pe"):
            self.assertFalse(optimizer.valid_skill_name(bad), bad)
        with self.assertRaises(ValueError):
            optimizer.system_rule_text("missing-skill")

    def test_chat_body_embeds_system_rule(self):
        body = optimizer.build_chat_body("m1", "用户输入", disable_thinking=False)
        self.assertEqual(body["stream"], True)
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertIn("Seedance 2.5 Prompt Optimizer", body["messages"][0]["content"])
        self.assertEqual(body["messages"][1]["content"], "用户输入")
        self.assertNotIn("thinking", body)

    def test_thinking_toggle_only_for_bigmodel(self):
        body = optimizer.build_chat_body("m", "x", disable_thinking=optimizer.supports_thinking_toggle("https://open.bigmodel.cn/api/paas/v4"))
        self.assertEqual(body["thinking"], {"type": "disabled"})
        body2 = optimizer.build_chat_body("m", "x", disable_thinking=optimizer.supports_thinking_toggle("https://api.deepseek.com"))
        self.assertNotIn("thinking", body2)

    def test_base_url_validation(self):
        self.assertTrue(optimizer.valid_base_url("https://api.deepseek.com"))
        self.assertTrue(optimizer.valid_base_url("http://127.0.0.1:8191/v1"))  # 本地 mock 允许
        for bad in ("", "ftp://x", "file:///etc/passwd", "javascript:alert(1)", "api.deepseek.com"):
            self.assertFalse(optimizer.valid_base_url(bad), bad)

    def test_local_infra_host_rejected(self):
        """云元数据/本机基础设施端点拒绝（防 SSRF 探测），本地回环不受影响。"""
        self.assertTrue(optimizer.is_local_infra_host("http://169.254.169.254/latest/meta-data"))
        self.assertTrue(optimizer.is_local_infra_host("http://metadata.google.internal"))
        self.assertFalse(optimizer.is_local_infra_host("http://127.0.0.1:8192"))
        self.assertFalse(optimizer.valid_base_url("http://169.254.169.254/latest/meta-data"))


class UserContentTests(unittest.TestCase):
    def test_five_section_input(self):
        content = optimizer.build_optimizer_user_content(
            task_type="auto", prompt="  一只猫  ",
            assets=[{"kind": "image", "role": "character", "label": "图片1"},
                    {"kind": "video", "role": "motion", "label": "视频1"},
                    {"kind": "audio", "role": "audio", "label": "音频1"}],
            duration=-1, resolution="720p", aspect_ratio="9:16", generate_audio=True,
        )
        self.assertIn("【本次优化任务】", content)
        self.assertIn("任务模式（用户已在页面选择）：全能参考", content)
        self.assertIn("仅编号清单，当前无法读取素材内容", content)
        self.assertIn("@图片1：图片（人物）", content)
        self.assertIn("@视频1：视频（动作）", content)
        self.assertIn("@音频1：音频（声音）", content)
        self.assertIn("总时长 自动（跟随原视频）", content)
        self.assertIn("页面生成参数（仅供规划，不得写入 Prompt）", content)
        self.assertIn("【原始提示词】\n一只猫", content)
        self.assertIn("【执行要求】", content)

    def test_no_assets_no_fake_inventory(self):
        content = optimizer.build_optimizer_user_content(
            task_type="text", prompt="p", assets=[], duration=10,
            resolution="480p", aspect_ratio="16:9", generate_audio=False,
        )
        self.assertNotIn("参考素材清单", content)
        self.assertIn("总时长 10 秒", content)
        self.assertIn("无声", content)


class SseParserTests(unittest.TestCase):
    def test_full_events(self):
        state = optimizer.new_sse_parser()
        deltas = optimizer.feed_sse(state, 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
                                            'data: {"choices":[{"delta":{}}]}\n\n'
                                            "data: [DONE]\n\n")
        self.assertEqual(deltas, ["你好"])

    def test_half_packet_chunk_boundaries(self):
        """一行 SSE 被拆在两次 chunk 中间也必须正确拼接（半包）。"""
        state = optimizer.new_sse_parser()
        payload = 'data: {"choices":[{"delta":{"content":"片段"}}]}\n\n'
        cut = len(payload) // 2
        out = optimizer.feed_sse(state, payload[:cut])
        self.assertEqual(out, [])
        out += optimizer.feed_sse(state, payload[cut:])
        self.assertEqual(out, ["片段"])

    def test_ignores_noise_and_keeps_buffer(self):
        state = optimizer.new_sse_parser()
        out = optimizer.feed_sse(state, ": heartbeat\n\n"
                                       'data: {"choices":[{"delta":{"reasoning_content":"思考"}}]}\n\n'
                                       'data: {"choices":[{"delta":{"content":"a"}}]}\n\ndata: {"ch')
        self.assertEqual(out, ["a"])
        # 残包留在 buffer，下一片到达后正常出增量
        out = optimizer.feed_sse(state, 'oices":[{"delta":{"content":"b"}}]}\n\n')
        self.assertEqual(out, ["b"])


if __name__ == "__main__":
    unittest.main()
