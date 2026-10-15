from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from iphone_color_pages.cli import main, read_json, write_json
from iphone_color_pages.colors import PALETTE, LABELS
from iphone_color_pages.cfgutil import DeviceError
from iphone_color_pages.layout import build_plan, fingerprint


def fixture_session(path):
    source = [["org.example.dock"], ["org.example.red", "org.example.blue"]]
    classes = {"org.example.red": "red", "org.example.blue": "blue"}
    target, summary = build_plan(source, classes, PALETTE, LABELS)
    write_json(path / "device.json", {"ECID": "0xTEST", "name": "Synthetic phone"})
    write_json(path / "plan.json", {
        "schema_version": 1, "device_ecid": "0xTEST", "page_capacity": 24,
        "source_layout": source, "layout": target, "classifications": classes,
        "source_fingerprint": fingerprint(source), "target_fingerprint": fingerprint(target),
        "summary": summary,
    })
    return source, target


class FakeConfigurator:
    def __init__(self, layout, *, add_library_icon=False, fail_after_write=False):
        self.current = deepcopy(layout)
        self.writes = 0
        self.add_library_icon = add_library_icon
        self.fail_after_write = fail_after_write

    def require_device(self, ecid):
        if ecid != "0xTEST":
            raise DeviceError("Wrong device")
        return {"ECID": ecid, "name": "Synthetic phone"}

    def layout(self, ecid):
        self.require_device(ecid)
        return deepcopy(self.current)

    def apply(self, ecid, path):
        self.require_device(ecid)
        self.writes += 1
        self.current = read_json(path)
        if self.add_library_icon:
            self.current[-1].append("org.example.library")
        if self.fail_after_write:
            raise DeviceError("uncertain transport failure")


class CliTests(unittest.TestCase):
    def run_cli(self, argv):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return main(argv)

    def test_apply_requires_widget_acceptance_before_device_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            fixture_session(path)
            with patch("iphone_color_pages.cli.Configurator") as constructor:
                self.assertEqual(self.run_cli(["apply", "--session", directory, "--yes"]), 2)
                constructor.assert_not_called()

    def test_changed_baseline_is_never_written(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _ = fixture_session(Path(directory))
            source[1].reverse()
            fake = FakeConfigurator(source)
            with patch("iphone_color_pages.cli.Configurator", return_value=fake):
                status = self.run_cli(["apply", "--session", directory, "--yes", "--accept-widget-changes"])
            self.assertEqual(status, 2)
            self.assertEqual(fake.writes, 0)

    def test_apply_then_verify_and_repeat_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = fixture_session(Path(directory))
            fake = FakeConfigurator(source)
            with patch("iphone_color_pages.cli.Configurator", return_value=fake):
                args = ["apply", "--session", directory, "--yes", "--accept-widget-changes"]
                self.assertEqual(self.run_cli(args), 0)
                self.assertEqual(self.run_cli(["verify", "--session", directory]), 0)
                self.assertEqual(self.run_cli(args), 0)
            self.assertEqual(fake.writes, 1)
            self.assertEqual(fake.current, target)
            self.assertTrue(read_json(Path(directory) / "verification.json")["ok"])
            self.assertTrue(list(Path(directory).glob("before-*.json")))

    def test_library_addition_is_saved_and_requires_explicit_replan(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _ = fixture_session(Path(directory))
            fake = FakeConfigurator(source, add_library_icon=True)
            with patch("iphone_color_pages.cli.Configurator", return_value=fake):
                status = self.run_cli(["apply", "--session", directory, "--yes", "--accept-widget-changes"])
            self.assertEqual(status, 3)
            self.assertEqual(fake.writes, 1)
            report = read_json(Path(directory) / "verification.json")
            self.assertEqual(report["added"], {"org.example.library": 1})

    def test_uncertain_transport_error_never_retries_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _ = fixture_session(Path(directory))
            fake = FakeConfigurator(source, fail_after_write=True)
            with patch("iphone_color_pages.cli.Configurator", return_value=fake):
                status = self.run_cli(["apply", "--session", directory, "--yes", "--accept-widget-changes"])
            self.assertEqual(status, 2)
            self.assertEqual(fake.writes, 1)
            self.assertTrue(list(Path(directory).glob("readback-*.json")))

    def test_plan_tamper_and_wrong_device_fail_before_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            fixture_session(path)
            plan = read_json(path / "plan.json")
            plan["layout"][1].append("org.example.unreviewed")
            write_json(path / "plan.json", plan)
            with patch("iphone_color_pages.cli.Configurator") as constructor:
                self.assertEqual(self.run_cli(["apply", "--session", directory, "--yes", "--accept-widget-changes"]), 2)
                constructor.assert_not_called()

    def test_wrong_device_is_rejected_before_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            fixture_session(path)
            plan = read_json(path / "plan.json")
            plan["device_ecid"] = "0xDIFFERENT"
            write_json(path / "plan.json", plan)
            with patch("iphone_color_pages.cli.Configurator") as constructor:
                self.assertEqual(self.run_cli(["apply", "--session", directory, "--yes", "--accept-widget-changes"]), 2)
                constructor.assert_not_called()

    def test_confirmation_cancel_and_missing_tty_do_not_access_device(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_session(Path(directory))
            args = ["apply", "--session", directory, "--accept-widget-changes"]
            with patch("iphone_color_pages.cli.Configurator") as constructor:
                with patch("sys.stdin.isatty", return_value=False):
                    self.assertEqual(self.run_cli(args), 2)
                with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="cancel"):
                    self.assertEqual(self.run_cli(args), 1)
                constructor.assert_not_called()

    def test_readback_failure_does_not_repeat_a_write(self):
        class DisconnectedAfterWrite(FakeConfigurator):
            def layout(self, ecid):
                if self.writes:
                    raise DeviceError("Disconnected")
                return super().layout(ecid)
        for fail_during_write in (False, True):
            with self.subTest(fail_during_write=fail_during_write), tempfile.TemporaryDirectory() as directory:
                source, _ = fixture_session(Path(directory))
                fake = DisconnectedAfterWrite(source, fail_after_write=fail_during_write)
                with patch("iphone_color_pages.cli.Configurator", return_value=fake):
                    status = self.run_cli(["apply", "--session", directory, "--yes", "--accept-widget-changes"])
                self.assertEqual(status, 2)
                self.assertEqual(fake.writes, 1)
                self.assertTrue(list(Path(directory).glob("before-*.json")))

    def test_demo_is_offline_and_cannot_be_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo"
            with patch("iphone_color_pages.cli.Configurator") as constructor:
                self.assertEqual(self.run_cli(["demo", "--output", str(output)]), 0)
                self.assertTrue((output / "preview.png").is_file())
                self.assertEqual(self.run_cli(["plan", "--session", str(output)]), 0)
                self.assertEqual(self.run_cli(["apply", "--session", str(output), "--yes", "--accept-widget-changes"]), 2)
                constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
