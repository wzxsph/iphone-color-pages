import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from iphone_color_pages.cfgutil import Configurator, DeviceError, decode_result, unwrap_layout


class ConfiguratorTests(unittest.TestCase):
    def test_raw_and_enveloped_layouts(self):
        layout = [[], ["org.example.a"]]
        self.assertEqual(unwrap_layout(layout, "0xAB"), layout)
        self.assertEqual(unwrap_layout({"Output": {"0xAB": layout}}, "0xab"), layout)
        with self.assertRaises(DeviceError):
            unwrap_layout({"Output": {"0xOTHER": layout}}, "0xAB")

    def test_success_exit_json_can_still_be_an_error(self):
        for error in ({"Type": "Error", "Message": "Failed"},
                      {"Type": "CommandOutput", "Output": {"Errors": ["failed"]}},
                      {"Output": {"0xAB": {"Errors": {"property": "failed"}}}}):
            with self.subTest(error=error), self.assertRaises(DeviceError):
                decode_result(json.dumps(error))

    def test_successful_queries_may_contain_nested_empty_error_containers(self):
        value = {"Type": "CommandOutput", "Output": {
            "0xAB": {"installedApps": [], "Errors": {}}, "Errors": {"0xAB": {}}}}
        self.assertEqual(decode_result(json.dumps(value)), value)
        value["Output"]["Errors"]["0xAB"] = {"installedApps": {"Message": "Locked"}}
        with self.assertRaises(DeviceError):
            decode_result(json.dumps(value))

    def test_pwd_and_cwd_are_both_set_for_icon_export(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            def run(args, **kwargs):
                self.assertEqual(Path(kwargs["cwd"]), directory.resolve())
                self.assertEqual(kwargs["env"]["PWD"], str(directory.resolve()))
                Image.new("RGB", (16, 16), "blue").save(directory / "org.example.a.png")
                return subprocess.CompletedProcess(args, 0, "", "Saved 1 icons.")
            with patch("iphone_color_pages.cfgutil.subprocess.run", side_effect=run):
                warnings = Configurator(sys.executable).export_icons("0xAB", ["org.example.a", "/", "../escape"], directory)
            self.assertFalse(any("Missing" in warning for warning in warnings))
            self.assertTrue((directory / "org.example.a.png").is_file())

    def test_missing_or_broken_png_is_reported_even_on_success(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "org.example.a.png").write_text("broken")
            result = subprocess.CompletedProcess([], 0, "", "Saved 0 icons.")
            with patch("iphone_color_pages.cfgutil.subprocess.run", return_value=result) as run:
                warnings = Configurator(sys.executable).export_icons("0xAB", ["org.example.a"], directory)
            self.assertEqual(run.call_count, 1)
            self.assertTrue(any("Missing or unreadable" in warning for warning in warnings))

    def test_timeout_is_uncertain_and_not_retried(self):
        with patch("iphone_color_pages.cfgutil.subprocess.run", side_effect=subprocess.TimeoutExpired([], 1)) as run:
            with self.assertRaisesRegex(DeviceError, "Do not retry"):
                Configurator(sys.executable).apply("0xAB", Path("synthetic-layout.json"))
            self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
