"""cx-bridge 服务端单元测试：不联网，覆盖答案解析与重试逻辑。

运行：cd cx-bridge && PYTHONIOENCODING=utf-8 python test_server.py
"""
import json
import unittest

import server


class TestParseAnswer(unittest.TestCase):
    def test_plain_json(self):
        out = server.parse_answer('{"answer":["B"],"reason":"因为磁场方向"}')
        self.assertEqual(out["answer"], ["B"])
        self.assertEqual(out["reason"], "因为磁场方向")

    def test_fenced_json(self):
        raw = '```json\n{"answer":["A","C"],"reason":"两个质数"}\n```'
        self.assertEqual(server.parse_answer(raw)["answer"], ["A", "C"])

    def test_answer_as_string(self):
        self.assertEqual(server.parse_answer('{"answer":"H2O"}')["answer"], ["H2O"])

    def test_extra_prose_around_json(self):
        raw = '答案如下：\n{"answer":["B"],"reason":"左手定则"}\n以上。'
        self.assertEqual(server.parse_answer(raw)["answer"], ["B"])

    def test_reason_truncated(self):
        out = server.parse_answer(json.dumps({"answer": ["A"], "reason": "x" * 500}))
        self.assertEqual(len(out["reason"]), 300)

    def test_missing_json_raises(self):
        with self.assertRaises(ValueError):
            server.parse_answer("我不会")

    def test_empty_answer_raises(self):
        with self.assertRaises(ValueError):
            server.parse_answer('{"answer":[]}')

    def test_blank_string_answer_raises(self):
        # 模型答不出时会回空串，必须当失败而不是填个空进页面
        with self.assertRaises(ValueError):
            server.parse_answer('{"answer":["  "]}')

    def test_blank_strings_dropped(self):
        self.assertEqual(server.parse_answer('{"answer":["", "B"]}')["answer"], ["B"])


    def test_numeric_answer_stringified(self):
        self.assertEqual(server.parse_answer('{"answer":[42]}')["answer"], ["42"])


class TestBuildMessages(unittest.TestCase):
    def test_text_only(self):
        msgs = server.build_messages({"stem": "1+1=?", "type": "single",
                                      "options": [{"key": "A", "text": "1"}, {"key": "B", "text": "2"}]})
        self.assertEqual(msgs[0]["role"], "system")
        content = msgs[1]["content"]
        self.assertIsInstance(content, str)
        self.assertIn("A. 1", content)
        self.assertIn("题型：single", content)

    def test_with_image_becomes_parts(self):
        msgs = server.build_messages({"stem": "看图", "images": ["data:image/png;base64,AAA"]})
        content = msgs[1]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "image_url")

    def test_images_capped_at_four(self):
        imgs = ["data:image/png;base64,A"] * 6
        msgs = server.build_messages({"stem": "x", "images": imgs})
        self.assertEqual(len(msgs[1]["content"]), 5)

    def test_non_data_url_image_ignored(self):
        msgs = server.build_messages({"stem": "x", "images": ["https://a/b.png"]})
        self.assertIsInstance(msgs[1]["content"], str)


class TestCompletionText(unittest.TestCase):
    def test_plain_content(self):
        payload = {"choices": [{"message": {"content": '{"answer":["B"]}'}, "finish_reason": "stop"}]}
        self.assertEqual(server.completion_text(payload), '{"answer":["B"]}')

    def test_empty_content_falls_back_to_reasoning_json(self):
        payload = {"choices": [{
            "message": {"content": "", "reasoning_content": "先想一下……最终 {\"answer\":[\"D\"],\"reason\":\"x\"} 好"},
            "finish_reason": "length"}]}
        self.assertEqual(server.completion_text(payload), '{"answer":["D"],"reason":"x"}')

    def test_both_empty_raises(self):
        payload = {"choices": [{"message": {"content": "  "}, "finish_reason": "length"}]}
        with self.assertRaises(ValueError):
            server.completion_text(payload)


class TestSolveOne(unittest.TestCase):
    def setUp(self):
        self._orig = server.deepseek_chat
        self.calls = []

    def tearDown(self):
        server.deepseek_chat = self._orig

    def test_retry_then_success(self):
        def fake(messages, timeout=90):
            self.calls.append(messages)
            if len(self.calls) == 1:
                raise RuntimeError("boom")
            return '{"answer":["B"],"reason":"ok"}'
        server.deepseek_chat = fake
        out = server.solve_one({"id": "1", "stem": "q"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["answer"], ["B"])
        self.assertEqual(len(self.calls), 2)

    def test_gives_up_after_two_attempts(self):
        def fake(messages, timeout=90):
            self.calls.append(messages)
            raise RuntimeError("always")
        server.deepseek_chat = fake
        out = server.solve_one({"id": "1", "stem": "q"})
        self.assertFalse(out["ok"])
        self.assertIn("always", out["error"])
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
