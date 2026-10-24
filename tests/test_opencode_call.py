import json
import os
import unittest
from unittest.mock import MagicMock, patch

from scripts.opencode_call import _parse_response_text, call_opencode, resolve_api_key


class TestOpenCodeCall(unittest.TestCase):

    def test_resolve_api_key_explicit(self):
        self.assertEqual(resolve_api_key("test-key-123"), "test-key-123")

    @patch.dict(os.environ, {"OPENCODE_API_KEY": "env-opencode-key"})
    def test_resolve_api_key_env(self):
        self.assertEqual(resolve_api_key(), "env-opencode-key")

    def test_parse_response_text_responses_wire(self):
        body = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Hello from OpenCode!"}
                    ],
                }
            ]
        }
        self.assertEqual(_parse_response_text(body, "responses"), "Hello from OpenCode!")

    def test_parse_response_text_chat_wire(self):
        body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Chat completion format",
                    }
                }
            ]
        }
        self.assertEqual(_parse_response_text(body, "chat"), "Chat completion format")

    @patch.dict(os.environ, {"OPENCODE_API_KEY": "mock-key"})
    def test_call_opencode_mocked_success(self):
        mock_body = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Synthesized text"}],
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_body).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = call_opencode(prompt="Test prompt", model="muse-spark-1.3-contributor")
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["content"], "Synthesized text")


if __name__ == "__main__":
    unittest.main()
