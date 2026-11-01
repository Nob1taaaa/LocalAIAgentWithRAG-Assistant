import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from assist_ledger import report_usage


class UsageTelemetryTests(unittest.TestCase):
    def test_skips_when_not_configured(self):
        answer = SimpleNamespace(response_metadata={}, usage_metadata={})
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(report_usage(answer, "llama3.2:3b"))

    def test_sends_counts_and_model_but_not_prompt_content(self):
        answer = SimpleNamespace(
            response_metadata={"prompt_eval_count": 120, "eval_count": 35, "total_duration": 2_500_000_000},
            usage_metadata={},
            content="private answer must not be sent",
        )
        captured = {}

        class Response:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data)
            captured["headers"] = request.headers
            captured["timeout"] = timeout
            return Response()

        env = {
            "ASSIST_LEDGER_FUNCTION_URL": "https://example.invalid/functions/v1/record-model-usage",
            "ASSIST_LEDGER_INGEST_KEY": "test-only-key",
            "ASSIST_LEDGER_REPOSITORY": "owner/repo",
        }
        with patch.dict("os.environ", env, clear=True), patch("urllib.request.urlopen", side_effect=fake_urlopen):
            self.assertTrue(report_usage(answer, "llama3.2:3b"))

        self.assertEqual(captured["payload"]["prompt_tokens"], 120)
        self.assertEqual(captured["payload"]["completion_tokens"], 35)
        self.assertEqual(captured["payload"]["latency_ms"], 2500)
        self.assertEqual(captured["payload"]["model"], "llama3.2:3b")
        self.assertEqual(captured["payload"]["client"], "python-rag")
        self.assertEqual(set(captured["payload"]), {
            "repository", "pull_request_number", "provider", "model", "client",
            "prompt_tokens", "completion_tokens", "latency_ms",
        })
        self.assertNotIn("private answer", json.dumps(captured["payload"]))


if __name__ == "__main__":
    unittest.main()
