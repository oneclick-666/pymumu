from __future__ import annotations

from pymumu import PyMumu


def test_control_methods_only_invoke_mumu_manager(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    mumu.tap(1, 2)
    mumu.swipe(1, 2, 3, 4, 500)
    mumu.input_text("中文 text")
    mumu.key_event("home")
    mumu.touch_down(5, 6)
    mumu.clear_text()

    assert len(calls) == 7
    assert all(call[0].endswith("MumuManager.exe") for call in calls)
    assert all(not any("adb" in part.lower() for part in call) for call in calls)
    assert all(call[1:4] == ["control", "-v", "3"] for call in calls)


def test_explicit_shared_folder_does_not_use_legacy_config(tmp_path):
    mumu = PyMumu(
        path=r"C:\MuMu\MumuManager.exe",
        index=3,
        shared_folder_path=str(tmp_path),
    )

    assert mumu._get_shared_folder_path() == str(tmp_path)
