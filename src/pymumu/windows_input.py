"""Windows-native input for MuMu Player.

MuMuManager does not expose a non-ADB text-input command.  This module targets
the window handle reported by ``MuMuManager info`` and pastes Unicode text with
Win32 APIs, keeping the control path independent from ADB.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from typing import Any

_INPUT_LOCK = threading.Lock()


def _parse_window_handle(value: Any) -> int:
    if isinstance(value, int):
        handle = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError("MuMu returned an empty window handle")
        try:
            # MuMuManager reports HWND values as hexadecimal strings, usually
            # without the 0x prefix (for example, "00840F4E").
            handle = int(raw, 16)
        except ValueError as exc:
            raise ValueError(f"Invalid MuMu window handle: {value!r}") from exc
    else:
        raise TypeError(f"Invalid MuMu window handle: {value!r}")
    if handle <= 0:
        raise ValueError(f"Invalid MuMu window handle: {value!r}")
    return handle


def get_instance_window(info: Any) -> int:
    """Return the render HWND from a MuMuManager info response.

    ``main_wnd`` remains a fallback for MuMu versions that do not expose a
    separate render window.
    """

    payload = info
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if not isinstance(payload, dict):
        raise TypeError("MuMu info response does not contain instance data")

    for key in ("render_wnd", "main_wnd"):
        value = payload.get(key)
        if value not in (None, "", 0):
            return _parse_window_handle(value)
    raise ValueError("MuMu info response has no render_wnd or main_wnd")


def _windows_api():
    if sys.platform != "win32":
        raise RuntimeError("MuMu native text input is only available on Windows")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.SetFocus.restype = wintypes.HWND
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return user32, kernel32


def _open_clipboard(user32, retries: int = 20) -> None:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.01)
    error = ctypes.get_last_error()
    raise OSError(error, "Unable to open the Windows clipboard")


def _read_clipboard_text(user32, kernel32) -> tuple[bool, str]:
    cf_unicode_text = 13
    _open_clipboard(user32)
    try:
        if not user32.IsClipboardFormatAvailable(cf_unicode_text):
            return False, ""
        memory = user32.GetClipboardData(cf_unicode_text)
        if not memory:
            return False, ""
        pointer = kernel32.GlobalLock(memory)
        if not pointer:
            return False, ""
        try:
            return True, ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(memory)
    finally:
        user32.CloseClipboard()


def _write_clipboard_text(user32, kernel32, text: str) -> None:
    cf_unicode_text = 13
    gmem_moveable = 0x0002
    buffer = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buffer)
    memory = kernel32.GlobalAlloc(gmem_moveable, size)
    if not memory:
        raise MemoryError("Unable to allocate Windows clipboard memory")

    transferred = False
    try:
        pointer = kernel32.GlobalLock(memory)
        if not pointer:
            raise OSError(ctypes.get_last_error(), "Unable to lock clipboard memory")
        try:
            ctypes.memmove(pointer, ctypes.addressof(buffer), size)
        finally:
            kernel32.GlobalUnlock(memory)

        _open_clipboard(user32)
        try:
            if not user32.EmptyClipboard():
                raise OSError(ctypes.get_last_error(), "Unable to clear the clipboard")
            if not user32.SetClipboardData(cf_unicode_text, memory):
                raise OSError(ctypes.get_last_error(), "Unable to set clipboard text")
            transferred = True
        finally:
            user32.CloseClipboard()
    finally:
        # SetClipboardData transfers ownership to the system on success.
        if not transferred:
            kernel32.GlobalFree(memory)


def _clear_clipboard(user32) -> None:
    _open_clipboard(user32)
    try:
        user32.EmptyClipboard()
    finally:
        user32.CloseClipboard()


def _activate_window(user32, kernel32, window_handle: int) -> int:
    ga_root = 2
    sw_restore = 9
    hwnd = wintypes.HWND(window_handle)
    if not user32.IsWindow(hwnd):
        raise RuntimeError(f"MuMu window no longer exists: 0x{window_handle:X}")

    root = user32.GetAncestor(hwnd, ga_root) or hwnd
    foreground = user32.GetForegroundWindow()
    current_thread = kernel32.GetCurrentThreadId()
    root_thread = user32.GetWindowThreadProcessId(root, None)
    render_thread = user32.GetWindowThreadProcessId(hwnd, None)
    foreground_thread = (
        user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    )
    attached: list[int] = []
    try:
        for thread_id in (foreground_thread, root_thread, render_thread):
            if (
                thread_id
                and thread_id != current_thread
                and thread_id not in attached
                and user32.AttachThreadInput(current_thread, thread_id, True)
            ):
                attached.append(thread_id)
        user32.ShowWindow(root, sw_restore)
        user32.BringWindowToTop(root)
        user32.SetForegroundWindow(root)
        user32.SetFocus(hwnd)
    finally:
        for thread_id in reversed(attached):
            user32.AttachThreadInput(current_thread, thread_id, False)

    active = user32.GetForegroundWindow()
    active_root = user32.GetAncestor(active, ga_root) if active else None
    if active != root and active_root != root:
        raise RuntimeError(
            "Windows could not activate the requested MuMu instance; "
            "bring the emulator window to the foreground and retry"
        )
    return int(root)


def _keyboard_types():
    input_keyboard = 1
    keyeventf_keyup = 0x0002
    ulong_ptr = ctypes.c_size_t
    uint32 = ctypes.c_uint32
    int32 = ctypes.c_int32

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", int32),
            ("dy", int32),
            ("mouseData", uint32),
            ("dwFlags", uint32),
            ("time", uint32),
            ("dwExtraInfo", ulong_ptr),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_uint16),
            ("wScan", ctypes.c_uint16),
            ("dwFlags", uint32),
            ("time", uint32),
            ("dwExtraInfo", ulong_ptr),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", uint32),
            ("wParamL", ctypes.c_uint16),
            ("wParamH", ctypes.c_uint16),
        ]

    class INPUT_UNION(ctypes.Union):
        # The complete union is required: SendInput validates sizeof(INPUT),
        # which is 40 bytes on 64-bit Windows even for keyboard-only events.
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [("type", uint32), ("value", INPUT_UNION)]

    return INPUT, KEYBDINPUT, input_keyboard, keyeventf_keyup


def _send_keyboard_events(user32, events) -> None:
    input_type = type(events)._type_
    user32.SendInput.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(input_type),
        ctypes.c_int,
    ]
    user32.SendInput.restype = wintypes.UINT
    sent = user32.SendInput(len(events), events, ctypes.sizeof(input_type))
    if sent != len(events):
        raise OSError(ctypes.get_last_error(), "Unable to send keyboard input to MuMu")


def send_key(window_handle: int, key: str) -> dict[str, Any]:
    """Send one latency-sensitive key directly to a MuMu render window."""

    scan_codes = {
        "delete": 0x0E,  # Backspace / Android KEYCODE_DEL
        "enter": 0x1C,
        "space": 0x39,
    }
    scan_code = scan_codes.get(key)
    if scan_code is None:
        raise ValueError(f"Unsupported Win32 MuMu key: {key}")

    user32, kernel32 = _windows_api()
    handle = _parse_window_handle(window_handle)
    input_type, keyboard_type, input_keyboard, keyeventf_keyup = _keyboard_types()
    keyeventf_scancode = 0x0008
    events = (
        input_type(
            type=input_keyboard,
            ki=keyboard_type(wScan=scan_code, dwFlags=keyeventf_scancode),
        ),
        input_type(
            type=input_keyboard,
            ki=keyboard_type(
                wScan=scan_code,
                dwFlags=keyeventf_scancode | keyeventf_keyup,
            ),
        ),
    )
    with _INPUT_LOCK:
        root = _activate_window(user32, kernel32, handle)
        _send_keyboard_events(user32, (input_type * len(events))(*events))

    return {
        "method": "win32_keyboard",
        "key": key,
        "window_handle": f"0x{handle:X}",
        "root_window_handle": f"0x{root:X}",
    }


def _send_mouse_button(user32, down: bool) -> None:
    input_type, _, _, _ = _keyboard_types()
    event = input_type(type=0)
    event.mi.dwFlags = 0x0002 if down else 0x0004
    events = (input_type * 1)(event)
    user32.SendInput.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(input_type),
        ctypes.c_int,
    ]
    user32.SendInput.restype = wintypes.UINT
    if user32.SendInput(1, events, ctypes.sizeof(input_type)) != 1:
        raise OSError(ctypes.get_last_error(), "Unable to send mouse input to MuMu")


def _device_to_screen(
    user32,
    window_handle: int,
    x: int,
    y: int,
    device_width: int,
    device_height: int,
) -> tuple[int, int]:
    if device_width <= 0 or device_height <= 0:
        raise ValueError("device dimensions must be positive")
    rect = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(window_handle), ctypes.byref(rect)):
        raise OSError(ctypes.get_last_error(), "Unable to read MuMu render size")
    client_width = rect.right - rect.left
    client_height = rect.bottom - rect.top
    if client_width <= 0 or client_height <= 0:
        raise RuntimeError("MuMu render window has no visible client area")
    # MuMu's 2160 x 3840 render surface reports touch coordinates about 20
    # device pixels below the visible frame. Compensate before scaling so taps
    # and both ends of a swipe use the same calibrated coordinate system.
    calibrated_y = (
        max(0, y - 20)
        if (device_width, device_height) == (2160, 3840)
        else y
    )
    point = wintypes.POINT(
        max(0, min(client_width - 1, round(x * client_width / device_width))),
        max(
            0,
            min(
                client_height - 1,
                round(calibrated_y * client_height / device_height),
            ),
        ),
    )
    if not user32.ClientToScreen(wintypes.HWND(window_handle), ctypes.byref(point)):
        raise OSError(ctypes.get_last_error(), "Unable to map MuMu render coordinates")
    return point.x, point.y


def mouse_gesture(
    window_handle: int,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    device_width: int,
    device_height: int,
    duration_ms: int = 0,
) -> dict[str, Any]:
    """Send a physical mouse tap or drag directly to one MuMu render window."""

    user32, kernel32 = _windows_api()
    handle = _parse_window_handle(window_handle)
    duration_ms = max(0, int(duration_ms))
    with _INPUT_LOCK:
        root = _activate_window(user32, kernel32, handle)
        start = _device_to_screen(
            user32, handle, start_x, start_y, device_width, device_height
        )
        end = _device_to_screen(
            user32, handle, end_x, end_y, device_width, device_height
        )
        previous = wintypes.POINT()
        restore_cursor = bool(user32.GetCursorPos(ctypes.byref(previous)))
        pressed = False
        try:
            if not user32.SetCursorPos(*start):
                raise OSError(ctypes.get_last_error(), "Unable to position the mouse")
            _send_mouse_button(user32, True)
            pressed = True
            if start == end:
                time.sleep(0.01)
            else:
                steps = max(2, min(60, duration_ms // 16 or 2))
                step_delay = duration_ms / steps / 1000 if duration_ms else 0
                for step in range(1, steps + 1):
                    ratio = step / steps
                    if not user32.SetCursorPos(
                        round(start[0] + (end[0] - start[0]) * ratio),
                        round(start[1] + (end[1] - start[1]) * ratio),
                    ):
                        raise OSError(
                            ctypes.get_last_error(), "Unable to drag the mouse"
                        )
                    if step_delay:
                        time.sleep(step_delay)
            _send_mouse_button(user32, False)
            pressed = False
        finally:
            if pressed:
                _send_mouse_button(user32, False)
            if restore_cursor:
                user32.SetCursorPos(previous.x, previous.y)

    return {
        "method": "win32_mouse",
        "window_handle": f"0x{handle:X}",
        "root_window_handle": f"0x{root:X}",
    }


def _send_ctrl_v(user32) -> None:
    input_type, keyboard_type, input_keyboard, keyeventf_keyup = _keyboard_types()
    keyeventf_scancode = 0x0008
    scan_left_control = 0x1D
    scan_v = 0x2F

    events = (
        input_type(
            type=input_keyboard,
            ki=keyboard_type(wScan=scan_left_control, dwFlags=keyeventf_scancode),
        ),
        input_type(
            type=input_keyboard,
            ki=keyboard_type(wScan=scan_v, dwFlags=keyeventf_scancode),
        ),
        input_type(
            type=input_keyboard,
            ki=keyboard_type(
                wScan=scan_v,
                dwFlags=keyeventf_scancode | keyeventf_keyup,
            ),
        ),
        input_type(
            type=input_keyboard,
            ki=keyboard_type(
                wScan=scan_left_control,
                dwFlags=keyeventf_scancode | keyeventf_keyup,
            ),
        ),
    )
    # Send the chord as distinct events. Some MuMu render versions coalesce a
    # single four-event SendInput batch and miss the Ctrl modifier.
    for event in events:
        _send_keyboard_events(user32, (input_type * 1)(event))
        time.sleep(0.02)


def _send_physical_text(user32, text: str) -> None:
    """Type text as physical keys using the active Windows keyboard layout."""

    input_type, keyboard_type, input_keyboard, keyeventf_keyup = _keyboard_types()
    user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    user32.VkKeyScanW.restype = ctypes.c_short
    modifier_keys = ((1, 0x10), (2, 0x11), (4, 0x12))  # Shift, Ctrl, Alt
    event_values = []
    for character in text:
        mapped = user32.VkKeyScanW(character)
        if mapped == -1:
            raise ValueError(
                f"Character cannot be typed as a physical key: {character!r}"
            )
        virtual_key = mapped & 0xFF
        modifiers = (mapped >> 8) & 0xFF
        pressed_modifiers = [key for flag, key in modifier_keys if modifiers & flag]
        event_values.extend(
            input_type(type=input_keyboard, ki=keyboard_type(wVk=key))
            for key in pressed_modifiers
        )
        event_values.append(
            input_type(type=input_keyboard, ki=keyboard_type(wVk=virtual_key))
        )
        event_values.append(
            input_type(
                type=input_keyboard,
                ki=keyboard_type(wVk=virtual_key, dwFlags=keyeventf_keyup),
            )
        )
        event_values.extend(
            input_type(
                type=input_keyboard,
                ki=keyboard_type(wVk=key, dwFlags=keyeventf_keyup),
            )
            for key in reversed(pressed_modifiers)
        )
    if event_values:
        _send_keyboard_events(user32, (input_type * len(event_values))(*event_values))


def paste_text(window_handle: int, text: str) -> dict[str, Any]:
    """Type text into one MuMu instance using Win32 only."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    user32, kernel32 = _windows_api()
    handle = _parse_window_handle(window_handle)

    with _INPUT_LOCK:
        root = _activate_window(user32, kernel32, handle)
        # Give MuMu's render window one message-loop turn after activation.
        time.sleep(0.05)
        # MuMu handles ordinary host keyboard input more reliably than host
        # clipboard synchronization. This path covers digits, Latin text and
        # punctuation, including the browser control API's common "1" input.
        if text.isascii():
            _send_physical_text(user32, text)
            method = "win32_physical_keyboard"
        else:
            _write_clipboard_text(user32, kernel32, text)
            time.sleep(0.35)
            _send_ctrl_v(user32)
            time.sleep(1.0)
            method = "win32_scancode_paste"

    return {
        "method": method,
        "window_handle": f"0x{handle:X}",
        "root_window_handle": f"0x{root:X}",
    }
