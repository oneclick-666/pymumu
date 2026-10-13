from __future__ import annotations

import json

from pymumu import PyMumu, windows_input
from pymumu.windows_input import get_instance_window


def test_control_methods_only_invoke_mumu_manager(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    mumu.tap(1, 2)
    mumu.swipe(1, 2, 3, 4, 500)
    mumu.key_event("home")
    mumu.touch_down(5, 6)
    mumu.clear_text()

    assert len(calls) == 6
    assert all(call[0].endswith("MumuManager.exe") for call in calls)
    assert all(not any("adb" in part.lower() for part in call) for call in calls)
    assert all(call[1:4] == ["control", "-v", "3"] for call in calls)
    tool_commands = [call for call in calls if call[4:6] == ["tool", "cmd"]]
    assert len(tool_commands) == 5
    assert all(call[6] == "-c" for call in tool_commands)


def test_unicode_text_targets_requested_instance_without_adb(monkeypatch):
    calls = []
    pasted = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        payload = {"main_wnd": "00840F4E", "render_wnd": "00B30C7A"}
        return type(
            "Result",
            (),
            {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""},
        )()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    monkeypatch.setattr(
        "pymumu.control.paste_text",
        lambda window_handle, text: pasted.append((window_handle, text)),
    )
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    mumu.input_text("随风而动", index=61)

    assert calls == [[r"C:\MuMu\MumuManager.exe", "info", "-v", "61"]]
    assert all(not any("adb" in part.lower() for part in call) for call in calls)
    assert pasted == [(int("00B30C7A", 16), "随风而动")]


def test_fast_tap_caches_window_and_skips_control_command(monkeypatch):
    manager_calls = []
    gestures = []

    def fake_run(cmd, **kwargs):
        manager_calls.append(cmd)
        payload = {"render_wnd": "00B30C7A"}
        return type(
            "Result",
            (),
            {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""},
        )()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    monkeypatch.setattr(
        "pymumu.control.mouse_gesture",
        lambda *args: gestures.append(args) or {"method": "win32_mouse"},
    )
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    mumu.tap(100, 200, device_width=1080, device_height=1920)
    mumu.tap(300, 400, device_width=1080, device_height=1920)

    assert manager_calls == [[r"C:\MuMu\MumuManager.exe", "info", "-v", "3"]]
    assert gestures == [
        (int("00B30C7A", 16), 100, 200, 100, 200, 1080, 1920),
        (int("00B30C7A", 16), 300, 400, 300, 400, 1080, 1920),
    ]


def test_delete_uses_cached_win32_window_and_volume_uses_mumu(monkeypatch):
    manager_calls = []
    key_calls = []

    def fake_run(cmd, **kwargs):
        manager_calls.append(cmd)
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps({"render_wnd": "00B30C7A"}),
                "stderr": "",
            },
        )()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    monkeypatch.setattr(
        "pymumu.control.send_key",
        lambda window_handle, key: key_calls.append((window_handle, key))
        or {"method": "win32_keyboard"},
    )
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    mumu.prepare_control()
    mumu.key_event("delete")
    mumu.key_event("volume_down")
    mumu.key_event("volume_up")

    assert manager_calls == [
        [r"C:\MuMu\MumuManager.exe", "info", "-v", "3"],
        [
            r"C:\MuMu\MumuManager.exe",
            "control",
            "-v",
            "3",
            "tool",
            "func",
            "--name",
            "volume_down",
        ],
        [
            r"C:\MuMu\MumuManager.exe",
            "control",
            "-v",
            "3",
            "tool",
            "func",
            "--name",
            "volume_up",
        ],
    ]
    assert key_calls == [
        (int("00B30C7A", 16), "delete"),
    ]


def test_delete_uses_backspace_hardware_scan_code(monkeypatch):
    user32, kernel32 = object(), object()
    sent = []
    monkeypatch.setattr(windows_input, "_windows_api", lambda: (user32, kernel32))
    monkeypatch.setattr(
        windows_input,
        "_activate_window",
        lambda received_user32, received_kernel32, handle: 456,
    )
    monkeypatch.setattr(
        windows_input,
        "_send_keyboard_events",
        lambda received_user32, events: sent.extend(
            (event.ki.wVk, event.ki.wScan, event.ki.dwFlags) for event in events
        ),
    )

    result = windows_input.send_key(123, "delete")

    assert sent == [(0, 0x0E, 0x0008), (0, 0x0E, 0x000A)]
    assert result["method"] == "win32_keyboard"


def test_fast_key_refreshes_stale_window(monkeypatch):
    handles = iter((123, 456))
    calls = []
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)
    monkeypatch.setattr(
        mumu,
        "_instance_window",
        lambda index=None, refresh=False: next(handles),
    )

    def fake_send_key(window_handle, key):
        calls.append((window_handle, key))
        if window_handle == 123:
            raise RuntimeError("MuMu window no longer exists: 0x7B")
        return {"method": "win32_keyboard"}

    monkeypatch.setattr("pymumu.control.send_key", fake_send_key)

    assert mumu.key_event("delete") == {"method": "win32_keyboard"}
    assert calls == [(123, "delete"), (456, "delete")]


def test_2160_by_3840_coordinates_are_shifted_up_20_device_pixels(monkeypatch):
    class User32:
        def GetClientRect(self, _handle, rect_pointer):
            rect = rect_pointer._obj
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1080, 1920
            return True

        def ClientToScreen(self, _handle, _point_pointer):
            return True

    assert windows_input._device_to_screen(
        User32(), 123, 1080, 2020, 2160, 3840
    ) == (540, 1000)
    assert windows_input._device_to_screen(
        User32(), 123, 1080, 2020, 1080, 2400
    ) == (1079, 1616)


def test_prepare_control_warms_window_cache(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps({"render_wnd": "00B30C7A"}),
                "stderr": "",
            },
        )()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    assert mumu.prepare_control() == {"window_handle": "0xB30C7A"}
    assert mumu._instance_window() == int("00B30C7A", 16)
    assert calls == [[r"C:\MuMu\MumuManager.exe", "info", "-v", "3"]]


def test_instance_window_falls_back_to_main_window():
    assert get_instance_window({"main_wnd": "00840F4E"}) == int("00840F4E", 16)


def test_ascii_text_uses_physical_keyboard(monkeypatch):
    user32, kernel32 = object(), object()
    calls = []
    monkeypatch.setattr(windows_input, "_windows_api", lambda: (user32, kernel32))
    monkeypatch.setattr(windows_input.time, "sleep", lambda delay: None)
    monkeypatch.setattr(
        windows_input,
        "_activate_window",
        lambda received_user32, received_kernel32, handle: 456,
    )
    monkeypatch.setattr(
        windows_input,
        "_send_physical_text",
        lambda received_user32, text: calls.append((received_user32, text)),
    )
    monkeypatch.setattr(
        windows_input,
        "_read_clipboard_text",
        lambda *args: (_ for _ in ()).throw(AssertionError("clipboard must not run")),
    )

    result = windows_input.paste_text(123, "1")

    assert calls == [(user32, "1")]
    assert result == {
        "method": "win32_physical_keyboard",
        "window_handle": "0x7B",
        "root_window_handle": "0x1C8",
    }


def test_unicode_text_uses_scancode_paste(monkeypatch):
    user32, kernel32 = object(), object()
    calls = []
    monkeypatch.setattr(windows_input, "_windows_api", lambda: (user32, kernel32))
    monkeypatch.setattr(windows_input.time, "sleep", lambda delay: None)
    monkeypatch.setattr(
        windows_input,
        "_activate_window",
        lambda received_user32, received_kernel32, handle: 456,
    )
    monkeypatch.setattr(
        windows_input,
        "_write_clipboard_text",
        lambda received_user32, received_kernel32, text: calls.append(
            (received_user32, received_kernel32, text)
        ),
    )
    monkeypatch.setattr(
        windows_input, "_send_ctrl_v", lambda value: calls.append(value)
    )
    result = windows_input.paste_text(123, "随风而动")

    assert calls == [(user32, kernel32, "随风而动"), user32]
    assert result["method"] == "win32_scancode_paste"


def test_paste_shortcut_uses_hardware_scan_codes(monkeypatch):
    calls = []
    monkeypatch.setattr(windows_input.time, "sleep", lambda delay: None)
    monkeypatch.setattr(
        windows_input,
        "_send_keyboard_events",
        lambda user32, events: calls.append(
            [(event.ki.wVk, event.ki.wScan, event.ki.dwFlags) for event in events]
        ),
    )

    windows_input._send_ctrl_v(object())

    assert calls == [
        [(0, 0x1D, 0x0008)],
        [(0, 0x2F, 0x0008)],
        [(0, 0x2F, 0x000A)],
        [(0, 0x1D, 0x000A)],
    ]


def test_explicit_shared_folder_does_not_use_legacy_config(tmp_path):
    mumu = PyMumu(
        path=r"C:\MuMu\MumuManager.exe",
        index=3,
        shared_folder_path=str(tmp_path),
    )

    assert mumu._get_shared_folder_path() == str(tmp_path)
