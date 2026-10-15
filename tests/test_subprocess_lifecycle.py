import subprocess
import sys

import pytest

from pymumu.exception import MuMuException
from pymumu.utils import UtilsMixin


def test_cli_returns_while_child_still_holds_output_handles():
    mumu = UtilsMixin()
    mumu.path = sys.executable
    script = (
        "import subprocess,sys; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(1)']); "
        "print('{\"ok\":true}', flush=True)"
    )
    assert mumu._run("-c", script, timeout=0.5) == {"ok": True}


def test_timeout_reaps_cli(monkeypatch):
    mumu = UtilsMixin()
    mumu.path = sys.executable
    original = subprocess.Popen
    processes = []

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("pymumu.utils.subprocess.Popen", spawn)
    with pytest.raises(subprocess.TimeoutExpired):
        mumu._run("-c", "import time; time.sleep(30)", timeout=0.05)
    assert processes[0].returncode is not None


def test_cli_errors_and_unicode_are_preserved():
    mumu = UtilsMixin()
    mumu.path = sys.executable
    assert mumu._run("-c", "print('你好')").strip() == "你好"
    with pytest.raises(MuMuException, match="test failure"):
        mumu._run("-c", "import sys; print('test failure', file=sys.stderr); sys.exit(1)")
