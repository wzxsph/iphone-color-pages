"""Small subprocess adapter for Apple's installed cfgutil executable."""

from pathlib import Path
import json
import os
import shutil
import subprocess

from PIL import Image

from .layout import safe_app_id, validate_layout

DEFAULT_CFGUTIL = Path("/Applications/Apple Configurator.app/Contents/MacOS/cfgutil")


class DeviceError(RuntimeError):
    pass


def has_error_payload(value):
    """cfgutil may include benign Errors={ECID: {}} on successful queries."""
    if isinstance(value, dict):
        return any(has_error_payload(item) for item in value.values())
    if isinstance(value, list):
        return any(has_error_payload(item) for item in value)
    return bool(value)


def decode_result(text):
    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeviceError("cfgutil did not return valid JSON") from exc
    if isinstance(result, dict) and (result.get("Type") == "Error" or has_error_payload(result.get("Error")) or has_error_payload(result.get("Errors"))):
        message = result.get("Message") or result.get("Error") or "Unknown cfgutil error"
        raise DeviceError(str(message))
    if isinstance(result, dict) and isinstance(result.get("Output"), dict):
        output = result["Output"]
        if has_error_payload(output.get("Errors")) or has_error_payload(output.get("Error")):
            raise DeviceError("cfgutil reported errors in its output")
        for value in output.values():
            if isinstance(value, dict) and (has_error_payload(value.get("Errors")) or has_error_payload(value.get("Error"))):
                raise DeviceError("cfgutil reported errors for a selected device")
    return result


def unwrap_layout(result, ecid):
    if isinstance(result, list):
        return validate_layout(result)
    if isinstance(result, dict):
        output = result.get("Output", {})
        key = next((k for k in output if isinstance(k, str) and k.casefold() == ecid.casefold()), None) if isinstance(output, dict) else None
        if key is not None:
            candidate = output[key]
            if isinstance(candidate, dict):
                candidate = candidate.get("iconLayout", candidate.get("IconLayout"))
            if candidate is not None:
                return validate_layout(candidate)
    raise DeviceError("cfgutil returned no icon layout for the selected ECID")


class Configurator:
    def __init__(self, executable=None):
        requested = str(executable) if executable else str(DEFAULT_CFGUTIL)
        resolved = shutil.which(requested)
        if not resolved and not executable:
            resolved = shutil.which("cfgutil")
        if not resolved:
            raise DeviceError("Install Apple Configurator for Mac first, or supply --cfgutil /path/to/cfgutil")
        self.executable = str(Path(resolved).resolve())
        self.last_stderr = ""

    def run(self, command, *, ecid=None, cwd=None, timeout=120, json_output=True):
        args = [self.executable]
        if ecid:
            args += ["--ecid", ecid]
        if json_output:
            args += ["--format", "JSON"]
        args += list(command)
        directory = Path(cwd).resolve() if cwd else Path.cwd()
        # cfgutil 2.21 actively chdir()s to PWD. Setting cwd alone exports icons
        # to the inherited working directory instead of the session directory.
        env = dict(os.environ, PWD=str(directory))
        try:
            result = subprocess.run(args, cwd=directory, env=env, capture_output=True,
                                    text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise DeviceError("cfgutil timed out; the device may be locked or disconnected. Do not retry a write before reading its state.") from exc
        except OSError as exc:
            raise DeviceError(f"Could not launch cfgutil: {exc}") from exc
        self.last_stderr = result.stderr.strip()
        if result.returncode:
            message = (result.stderr or result.stdout).strip()
            raise DeviceError(f"cfgutil failed ({result.returncode}): {message[:2000]}")
        if result.stdout.strip() and json_output:
            return decode_result(result.stdout)
        return result.stdout

    def devices(self):
        result = self.run(["list"])
        if not isinstance(result, dict) or not isinstance(result.get("Output"), dict):
            raise DeviceError("Unexpected cfgutil device list")
        return [{**value, "ECID": key} for key, value in result["Output"].items()
                if key not in ("Errors", "Error", "Warnings") and isinstance(value, dict)]

    def require_device(self, ecid):
        device = next((d for d in self.devices() if d["ECID"].lower() == ecid.lower()), None)
        if not device:
            raise DeviceError("The selected ECID is not connected. Check the USB cable, unlock the phone, and trust this Mac.")
        return device

    def layout(self, ecid):
        return unwrap_layout(self.run(["get-icon-layout"], ecid=ecid), ecid)

    def names(self, ecid):
        try:
            result = self.run(["get", "installedApps"], ecid=ecid)
            apps = result["Output"][ecid]["installedApps"]
            return {a["bundleIdentifier"]: a.get("displayName") or a.get("itunesName") or a["bundleIdentifier"] for a in apps}
        except (DeviceError, KeyError, TypeError):
            return {}

    def export_icons(self, ecid, identifiers, destination):
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        def valid_png(path):
            try:
                with Image.open(path) as icon:
                    if icon.format != "PNG":
                        return False
                    icon.verify()
                return True
            except (OSError, ValueError):
                return False
        expected = sorted({i for i in identifiers if safe_app_id(i)})
        ids = [i for i in expected if not valid_png(destination / f"{i}.png")]
        warnings = []
        for start in range(0, len(ids), 64):
            try:
                self.run(["get-app-icon", "--raw", *ids[start:start+64]], ecid=ecid,
                         cwd=destination, json_output=False)
                if self.last_stderr:
                    warnings.append(self.last_stderr[:2000])
            except DeviceError as exc:
                warnings.append(str(exc))
        warnings += [f"Missing or unreadable PNG: {i}" for i in expected if not valid_png(destination / f"{i}.png")]
        return warnings

    def apply(self, ecid, path):
        # --force allows identifiers for uninstalled apps; never use it here.
        return self.run(["set-icon-layout", str(Path(path).resolve())], ecid=ecid)
