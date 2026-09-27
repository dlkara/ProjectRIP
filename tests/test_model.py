from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from project_autopsy.model import ModelError, OpenAIModel, STRING, object_schema


class ModelGatewayTests(unittest.TestCase):
    def test_unauthorized_response_does_not_echo_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-proj-private-test-key"}):
            model = OpenAIModel()
            error = HTTPError(
                "https://api.openai.com/v1/responses",
                401,
                "Unauthorized",
                {},
                io.BytesIO(b"Incorrect API key: sk-proj-private-test-key"),
            )
            with patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaises(ModelError) as result:
                    model.structured("smoke", object_schema({"ok": STRING}), "Return JSON.", {"test": "hello"})
        self.assertIn("인증", str(result.exception))
        self.assertNotIn("sk-proj", str(result.exception))


if __name__ == "__main__":
    unittest.main()
