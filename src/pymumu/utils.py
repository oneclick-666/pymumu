import json
import os
import subprocess
import tempfile
from typing import Any

try:
    import winreg
except ImportError:  # pragma: no cover - only available on Windows
    winreg = None  # type: ignore[assignment]
from .exception import MuMuException, MuMuNotFoundError


class UtilsMixin:
    def _find_mumu(self):
        if winreg is not None:
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MuMuPlayerGlobal",
                )
                display_icon, _ = winreg.QueryValueEx(key, "DisplayIcon")
                winreg.CloseKey(key)
                nx_main = os.path.dirname(display_icon)
                exe = os.path.join(nx_main, "MumuManager.exe")
                if os.path.exists(exe):
                    return exe
            except FileNotFoundError:
                pass
        if os.path.exists(
            r"C:\Program Files\Netease\MuMuPlayer\nx_main\MumuManager.exe"
        ):
            return r"C:\Program Files\Netease\MuMuPlayer\nx_main\MumuManager.exe"
        for candidate in (
            r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\MuMuManager.exe",
            r"C:\Program Files (x86)\Netease\MuMuPlayer-12.0\shell\MuMuManager.exe",
        ):
            if os.path.exists(candidate):
                return candidate
        raise MuMuNotFoundError("MuMuPlayer not found")

    def _run(self, *args: Any, allowErrors: bool = False, timeout: float = 30):
        cmd = [self.path, *[str(a) for a in args]]
        # A launched MuMu process may inherit CLI output handles. Capturing
        # pipes waits for that child to close them, even after the CLI exits.
        # Files keep both normal completion and subprocess.run's timeout bounded.
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            result = subprocess.run(cmd, stdout=out, stderr=err, timeout=timeout)
            out.seek(0)
            err.seek(0)
            stdout = out.read().decode("utf-8", errors="replace")
            stderr = err.read().decode("utf-8", errors="replace")
        if result.returncode != 0:
            if not allowErrors:
                raise MuMuException(f"Command {' '.join(cmd)} failed: {stderr}")
        if not stdout or not stdout.strip():
            return stdout
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return stdout
