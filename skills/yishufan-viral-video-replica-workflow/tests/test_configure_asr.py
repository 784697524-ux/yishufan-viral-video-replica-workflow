import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "configure_asr.py"
SPEC = importlib.util.spec_from_file_location("configure_asr", SCRIPT)
configure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configure)


class ConfigureAsrCheckTests(unittest.TestCase):
    def check(self, file_text, environment):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / ".env"
            if file_text is not None:
                config.write_text(file_text, encoding="utf-8")
            output = io.StringIO()
            with patch.dict(os.environ, environment, clear=True), patch(
                "sys.argv", [str(SCRIPT), "--config", str(config), "--check"]
            ), contextlib.redirect_stdout(output):
                code = configure.main()
            return code, output.getvalue()

    def test_environment_only_is_configured_without_exposing_values(self):
        environment = {
            "DASHSCOPE_API_KEY": "private-environment-key",
            "DASHSCOPE_ENDPOINT": "https://private-endpoint.invalid/v1",
            "DASHSCOPE_ASR_MODELS": "private-model-setting",
        }
        code, output = self.check(None, environment)
        self.assertEqual(code, 0)
        for key, value in environment.items():
            self.assertIn(f"{key}: configured=True", output)
            self.assertNotIn(value, output)

    def test_environment_supplies_missing_file_setting(self):
        code, output = self.check(
            "DASHSCOPE_API_KEY=\nDASHSCOPE_ENDPOINT=https://file.invalid/v1\n",
            {"DASHSCOPE_API_KEY": "environment-key"},
        )
        self.assertEqual(code, 0)
        self.assertNotIn("environment-key", output)
        self.assertNotIn("https://file.invalid/v1", output)

    def test_empty_environment_falls_back_to_file_like_backend(self):
        code, output = self.check(
            "DASHSCOPE_API_KEY=file-key\nDASHSCOPE_ENDPOINT=https://file.invalid/v1\n",
            {"DASHSCOPE_API_KEY": "", "DASHSCOPE_ENDPOINT": ""},
        )
        self.assertEqual(code, 0)
        self.assertNotIn("file-key", output)

    def test_missing_configuration_fails(self):
        code, output = self.check(None, {})
        self.assertEqual(code, 2)
        self.assertIn("DASHSCOPE_API_KEY: configured=False", output)


if __name__ == "__main__":
    unittest.main()
