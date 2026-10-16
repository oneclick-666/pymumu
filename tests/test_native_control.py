from __future__ import annotations

import json
import subprocess

import pytest

from pymumu import PyMumu, windows_input
from pymumu.windows_input import get_instance_window, get_render_window


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
        kwargs["stdout"].write(json.dumps(payload).encode())
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
        kwargs["stdout"].write(json.dumps(payload).encode())
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


def test_prepare_waits_for_render_window_before_touch(monkeypatch):
    manager_calls = []
    gestures = []
    responses = iter(
        (
            {"main_wnd": "00840F4E"},
            {"main_wnd": "00840F4E", "render_wnd": "00B30C7A"},
        )
    )

    def fake_run(cmd, **kwargs):
        manager_calls.append(cmd)
        payload = json.dumps(next(responses))
        kwargs["stdout"].write(payload.encode())
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": payload,
                "stderr": "",
            },
        )()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    monkeypatch.setattr(
        "pymumu.control.mouse_gesture",
        lambda *args: gestures.append(args) or {"method": "win32_mouse"},
    )
    monkeypatch.setattr("pymumu.control.time.sleep", lambda _delay: None)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    assert mumu.prepare_control() == {"window_handle": "0xB30C7A"}
    mumu.tap(100, 200, device_width=1080, device_height=1920)

    assert len(manager_calls) == 2
    assert gestures == [
        (int("00B30C7A", 16), 100, 200, 100, 200, 1080, 1920),
    ]


def test_first_touch_waits_for_render_window(monkeypatch):
    responses = iter(
        (
            {"main_wnd": "00840F4E"},
            {"main_wnd": "00840F4E"},
            {"render_wnd": "00B30C7A"},
        )
    )
    gestures = []

    monkeypatch.setattr(
        PyMumu,
        "info",
        lambda self, index=None: next(responses),
    )
    monkeypatch.setattr("pymumu.control.time.sleep", lambda _delay: None)
    monkeypatch.setattr(
        "pymumu.control.mouse_gesture",
        lambda *args: gestures.append(args) or {"method": "win32_mouse"},
    )
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.tap(100, 200, device_width=1080, device_height=1920)

    assert result == {"method": "win32_mouse"}
    assert gestures[0][0] == int("00B30C7A", 16)


def test_delete_uses_cached_win32_window_and_volume_uses_mumu(monkeypatch):
    manager_calls = []
    key_calls = []

    def fake_run(cmd, **kwargs):
        manager_calls.append(cmd)
        kwargs["stdout"].write(json.dumps({"render_wnd": "00B30C7A"}).encode())
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


def test_all_resolutions_map_without_fixed_vertical_offset(monkeypatch):
    class User32:
        def GetClientRect(self, _handle, rect_pointer):
            rect = rect_pointer._obj
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 1080, 1920
            return True

        def ClientToScreen(self, _handle, _point_pointer):
            return True

    assert windows_input._device_to_screen(
        User32(), 123, 1080, 2020, 2160, 3840
    ) == (540, 1010)
    assert windows_input._device_to_screen(
        User32(), 123, 720, 1300, 1440, 2560
    ) == (540, 975)
    assert windows_input._device_to_screen(
        User32(), 123, 1080, 2020, 1080, 2400
    ) == (1079, 1616)


def test_prepare_control_warms_window_cache(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        kwargs["stdout"].write(json.dumps({"render_wnd": "00B30C7A"}).encode())
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


def test_open_url_and_ui_selector_use_only_mumu_manager(monkeypatch):
    calls = []
    hierarchy = """<?xml version="1.0" encoding="UTF-8"?><hierarchy><node text="添加标题" resource-id="com.xingin.xhs:id/0_resource_name_obfuscated" class="android.widget.EditText" bounds="[100,200][500,300]" /></hierarchy>"""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        value = hierarchy if "uiautomator dump" in " ".join(cmd) else ""
        kwargs["stdout"].write(value.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)
    mumu.open_url("xhsdiscover://js_share_sdk?share_code=one%26two")
    result = mumu.find_and_tap(
        text="添加标题",
        resource_id="com.xingin.xhs:id/0_resource_name_obfuscated",
        class_name="android.widget.EditText",
        timeout_ms=0,
    )
    assert result["bounds"] == "[100,200][500,300]"
    command_text = "\n".join(" ".join(call) for call in calls)
    assert "android.intent.action.VIEW" in command_text
    assert "uiautomator dump /sdcard/autoglm-window-3-" in command_text
    assert "input tap 300 250" in command_text
    assert "adb" not in command_text.lower()


def test_open_url_rejects_unsafe_scheme(monkeypatch):
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)
    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        mumu.open_url("file:///etc/passwd")


def test_open_url_treats_stuck_manager_cli_as_dispatched(monkeypatch):
    def fake_run(_cmd, **_kwargs):
        raise __import__("subprocess").TimeoutExpired("MuMuManager.exe", 8)

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.open_url("xhsdiscover://js_share_sdk?share_code=code")

    assert result == {"dispatched": True, "manager_cli_timed_out": True}


def test_ui_selector_reads_regular_xml_file(monkeypatch):
    calls = []
    hierarchy = '<hierarchy><node text="发布笔记" bounds="[10,20][110,80]" /></hierarchy>'

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        command = " ".join(cmd)
        value = hierarchy if "uiautomator dump" in command else ""
        kwargs["stdout"].write(value.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)
    result = mumu.find_and_tap(text="发布笔记", timeout_ms=0)

    assert result["bounds"] == "[10,20][110,80]"
    command_text = "\n".join(" ".join(call) for call in calls)
    assert "uiautomator dump /sdcard/autoglm-window-3-" in command_text
    assert "input tap 60 50" in command_text
    assert "adb" not in command_text.lower()


def test_ui_selector_can_wait_until_button_disappears(monkeypatch):
    hierarchy = '<hierarchy><node text="发布笔记" bounds="[10,20][110,80]" /></hierarchy>'
    dumps = iter([hierarchy, "<hierarchy />"])

    def fake_run(cmd, **kwargs):
        command = " ".join(cmd)
        value = next(dumps) if "uiautomator dump" in command else ""
        kwargs["stdout"].write(value.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    monkeypatch.setattr("pymumu.control.time.sleep", lambda _seconds: None)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.find_and_tap(
        text="发布笔记", timeout_ms=1000, wait_until_gone=True
    )

    assert result["gone"] is True


def test_ui_selector_uses_edit_text_order_and_verifies_focus(monkeypatch):
    before = """<hierarchy>
      <node text="新版标题提示" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" focused="false" bounds="[60,944][2160,1144]" />
      <node text="新版正文提示" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" focused="false" bounds="[0,1144][2160,2192]" />
    </hierarchy>"""
    after = before.replace('text="新版正文提示"', 'text=""').replace(
        'focused="false" bounds="[0,1144]',
        'focused="true" bounds="[0,1144]',
        1,
    )
    dumps = iter([before, after])

    def fake_run(cmd, **kwargs):
        command = " ".join(cmd)
        value = next(dumps) if "uiautomator dump" in command else ""
        kwargs["stdout"].write(value.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    monkeypatch.setattr("pymumu.control.time.sleep", lambda _seconds: None)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.find_and_tap(
        class_name="android.widget.EditText",
        package_name="com.xingin.xhs",
        selector_index=1,
        clickable=True,
        enabled=True,
        timeout_ms=1000,
        wait_until_focused=True,
    )

    assert result["focused"] is True
    assert result["bounds"] == "[0,1144][2160,2192]"


def test_wait_for_ui_requires_complete_publish_page_in_one_snapshot(monkeypatch):
    incomplete = """<hierarchy>
      <node text="添加标题" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" />
      <node text="发布笔记" class="android.widget.Button" package="com.xingin.xhs" clickable="true" enabled="true" />
    </hierarchy>"""
    complete = """<hierarchy>
      <node text="添加标题" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" />
      <node text="添加作品描述" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" />
      <node text="发布笔记" class="android.widget.Button" package="com.xingin.xhs" clickable="true" enabled="true" />
    </hierarchy>"""
    dumps = iter([incomplete, complete])
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        command = " ".join(cmd)
        value = next(dumps) if "uiautomator dump" in command else ""
        kwargs["stdout"].write(value.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    monkeypatch.setattr("pymumu.control.time.sleep", lambda _seconds: None)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.wait_for_ui(
        class_name="android.widget.EditText",
        package_name="com.xingin.xhs",
        minimum_matches=2,
        clickable=True,
        enabled=True,
        required_text="发布笔记",
        required_class_name="android.widget.Button",
        required_clickable=True,
        required_enabled=True,
        timeout_ms=1000,
    )

    assert result == {
        "ready": True,
        "matches": 2,
        "required_matches": 1,
        "dismissed": 0,
    }
    assert not any("input tap" in " ".join(call) for call in calls)


def test_wait_for_ui_dismisses_late_permission_popup(monkeypatch):
    popup = """<hierarchy>
      <node text="申请获取您的相册内容位置信息" class="android.widget.TextView" package="com.xingin.xhs" enabled="true" />
      <node text="取消" class="android.widget.TextView" package="com.xingin.xhs" clickable="true" enabled="true" bounds="[204,2365][702,2485]" />
    </hierarchy>"""
    page = """<hierarchy>
      <node text="添加标题" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" />
      <node text="添加作品描述" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" />
      <node text="发布笔记" class="android.widget.Button" package="com.xingin.xhs" clickable="true" enabled="true" />
    </hierarchy>"""
    dumps = iter([popup, page])
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        command = " ".join(cmd)
        value = next(dumps) if "uiautomator dump" in command else ""
        kwargs["stdout"].write(value.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    monkeypatch.setattr("pymumu.control.time.sleep", lambda _seconds: None)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.wait_for_ui(
        class_name="android.widget.EditText",
        package_name="com.xingin.xhs",
        minimum_matches=2,
        clickable=True,
        enabled=True,
        required_text="发布笔记",
        required_class_name="android.widget.Button",
        required_clickable=True,
        required_enabled=True,
        dismiss_text="取消",
        dismiss_class_name="android.widget.TextView",
        dismiss_required_text="申请获取您的相册内容位置信息",
        timeout_ms=1000,
    )

    assert result["dismissed"] == 1
    assert any("input tap 453 2425" in " ".join(call) for call in calls)


def test_check_ui_returns_ready_from_one_complete_snapshot(monkeypatch):
    page = """<hierarchy>
      <node text="添加标题" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" />
      <node text="添加作品描述" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" />
      <node text="发布笔记" class="android.widget.Button" package="com.xingin.xhs" clickable="true" enabled="true" />
    </hierarchy>"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "uiautomator dump" in " ".join(cmd):
            kwargs["stdout"].write(page.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.check_ui(
        class_name="android.widget.EditText",
        package_name="com.xingin.xhs",
        minimum_matches=2,
        clickable=True,
        enabled=True,
        required_text="发布笔记",
        required_class_name="android.widget.Button",
        required_clickable=True,
        required_enabled=True,
    )

    assert result == {
        "ready": True,
        "matches": 2,
        "required_matches": 1,
        "dismissed": 0,
    }
    assert not any("input tap" in " ".join(call) for call in calls)


def test_check_ui_reads_detached_dump_after_manager_timeout(monkeypatch):
    page = """<hierarchy>
      <node text="添加标题" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" />
      <node text="添加作品描述" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" />
      <node text="发布笔记" class="android.widget.Button" package="com.xingin.xhs" clickable="true" enabled="true" />
    </hierarchy>"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        command = " ".join(cmd)
        if "uiautomator dump" in command:
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        if "while [" in command:
            kwargs["stdout"].write(page.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.check_ui(
        class_name="android.widget.EditText",
        package_name="com.xingin.xhs",
        minimum_matches=2,
        clickable=True,
        enabled=True,
        required_text="发布笔记",
        required_class_name="android.widget.Button",
        required_clickable=True,
        required_enabled=True,
    )

    assert result["ready"] is True
    assert any(
        "uiautomator dump /sdcard/autoglm-window-3-" in " ".join(call)
        and " 2>&1) &" in " ".join(call)
        for call in calls
    )
    assert any("while [" in " ".join(call) for call in calls)
    assert not any("input tap" in " ".join(call) for call in calls)


def test_check_ui_returns_not_ready_for_incomplete_snapshot(monkeypatch):
    incomplete = """<hierarchy>
      <node text="添加标题" class="android.widget.EditText" package="com.xingin.xhs" clickable="true" enabled="true" />
      <node text="发布笔记" class="android.widget.Button" package="com.xingin.xhs" clickable="true" enabled="true" />
    </hierarchy>"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "uiautomator dump" in " ".join(cmd):
            kwargs["stdout"].write(incomplete.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.check_ui(
        class_name="android.widget.EditText",
        package_name="com.xingin.xhs",
        minimum_matches=2,
        clickable=True,
        enabled=True,
        required_text="发布笔记",
        required_class_name="android.widget.Button",
        required_clickable=True,
        required_enabled=True,
    )

    assert result == {
        "ready": False,
        "matches": 1,
        "required_matches": 1,
        "dismissed": 0,
    }
    assert not any("input tap" in " ".join(call) for call in calls)


def test_check_ui_dismisses_matching_permission_popup_once(monkeypatch):
    popup = """<hierarchy>
      <node text="申请获取您的相册内容位置信息" class="android.widget.TextView" package="com.xingin.xhs" enabled="true" />
      <node text="取消" class="android.widget.TextView" package="com.xingin.xhs" clickable="true" enabled="true" bounds="[204,2365][702,2485]" />
    </hierarchy>"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "uiautomator dump" in " ".join(cmd):
            kwargs["stdout"].write(popup.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.check_ui(
        class_name="android.widget.EditText",
        package_name="com.xingin.xhs",
        minimum_matches=2,
        clickable=True,
        enabled=True,
        required_text="发布笔记",
        required_class_name="android.widget.Button",
        required_clickable=True,
        required_enabled=True,
        dismiss_text="取消",
        dismiss_class_name="android.widget.TextView",
        dismiss_required_text="申请获取您的相册内容位置信息",
    )

    assert result == {
        "ready": False,
        "matches": 0,
        "required_matches": 0,
        "dismissed": 1,
    }
    assert sum("input tap 453 2425" in " ".join(call) for call in calls) == 1


def test_optional_popup_cancel_requires_matching_dialog_title(monkeypatch):
    unrelated = """<hierarchy>
      <node text="其他弹窗" class="android.widget.TextView" package="com.xingin.xhs" enabled="true" bounds="[0,0][100,50]" />
      <node text="取消" class="android.widget.TextView" package="com.xingin.xhs" clickable="true" enabled="true" bounds="[10,60][90,100]" />
    </hierarchy>"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        command = " ".join(cmd)
        value = unrelated if "uiautomator dump" in command else ""
        kwargs["stdout"].write(value.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.find_and_tap(
        text="取消",
        class_name="android.widget.TextView",
        package_name="com.xingin.xhs",
        clickable=True,
        enabled=True,
        required_text="申请获取您的相册内容位置信息",
        timeout_ms=0,
        optional=True,
        wait_until_gone=True,
    )

    assert result == {"found": False}
    assert not any("input tap" in " ".join(call) for call in calls)


def test_permission_popup_cancel_is_clicked_and_verified_gone(monkeypatch):
    popup = """<hierarchy>
      <node text="申请获取您的相册内容位置信息" class="android.widget.TextView" package="com.xingin.xhs" enabled="true" bounds="[108,2094][1332,2149]" />
      <node text="取消" class="android.widget.TextView" package="com.xingin.xhs" clickable="true" enabled="true" bounds="[204,2365][702,2485]" />
    </hierarchy>"""
    dumps = iter([popup, "<hierarchy />"])
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        command = " ".join(cmd)
        value = next(dumps) if "uiautomator dump" in command else ""
        kwargs["stdout"].write(value.encode())
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("pymumu.utils.subprocess.run", fake_run)
    monkeypatch.setattr("pymumu.control.time.sleep", lambda _seconds: None)
    mumu = PyMumu(path=r"C:\MuMu\MumuManager.exe", index=3)

    result = mumu.find_and_tap(
        text="取消",
        class_name="android.widget.TextView",
        package_name="com.xingin.xhs",
        clickable=True,
        enabled=True,
        required_text="申请获取您的相册内容位置信息",
        timeout_ms=1000,
        optional=True,
        wait_until_gone=True,
    )

    assert result["gone"] is True
    assert any("input tap 453 2425" in " ".join(call) for call in calls)


def test_instance_window_falls_back_to_main_window():
    assert get_instance_window({"main_wnd": "00840F4E"}) == int("00840F4E", 16)


def test_render_window_never_falls_back_to_main_window():
    try:
        get_render_window({"main_wnd": "00840F4E"})
    except RuntimeError as error:
        assert str(error) == "MuMu render window is not ready"
    else:
        raise AssertionError("main_wnd must not be used for touch input")


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


def test_physical_text_sends_characters_sequentially(monkeypatch):
    class VkKeyScan:
        argtypes = None
        restype = None

        def __call__(self, character):
            return ord(character)

    class User32:
        VkKeyScanW = VkKeyScan()

    calls = []
    monkeypatch.setattr(windows_input.time, "sleep", lambda delay: None)
    monkeypatch.setattr(
        windows_input,
        "_send_keyboard_events",
        lambda user32, events: calls.append(
            [(event.ki.wVk, event.ki.dwFlags) for event in events]
        ),
    )

    windows_input._send_physical_text(User32(), "123456")

    assert calls == [
        [(ord(character), flags)]
        for character in "123456"
        for flags in (0, 0x0002)
    ]


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
