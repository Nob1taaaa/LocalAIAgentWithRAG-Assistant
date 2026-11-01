import json
import unittest

from ollama_telemetry_proxy import extract_chat_usage


class OllamaUsageParsingTests(unittest.TestCase):
    def test_reads_final_usage_metadata_without_capturing_generated_text(self):
        body = b"\n".join([
            json.dumps({"message": {"content": "private generated content"}, "done": False}).encode(),
            json.dumps({"done": True, "prompt_eval_count": 51, "eval_count": 12, "total_duration": 9000000}).encode(),
        ])
        self.assertEqual(extract_chat_usage(body), {
            "prompt_eval_count": 51,
            "eval_count": 12,
            "total_duration": 9000000,
        })

    def test_returns_none_when_usage_is_absent(self):
        self.assertIsNone(extract_chat_usage(b'{"message":{"content":"not telemetry"},"done":true}'))


if __name__ == "__main__":
    unittest.main()
