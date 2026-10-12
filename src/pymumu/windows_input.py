"""Windows-native text input for MuMu Player.

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


def _send_ctrl_v(user32) -> None:
    input_keyboard = 1
    keyeventf_keyup = 0x0002
    vk_control = 0x11
    vk_v = 0x56
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

    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    events = (INPUT * 4)(
        INPUT(type=input_keyboard, ki=KEYBDINPUT(wVk=vk_control)),
        INPUT(type=input_keyboard, ki=KEYBDINPUT(wVk=vk_v)),
        INPUT(
            type=input_keyboard,
            ki=KEYBDINPUT(wVk=vk_v, dwFlags=keyeventf_keyup),
        ),
        INPUT(
            type=input_keyboard,
            ki=KEYBDINPUT(wVk=vk_control, dwFlags=keyeventf_keyup),
        ),
    )
    sent = user32.SendInput(len(events), events, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError(ctypes.get_last_error(), "Unable to send Ctrl+V to MuMu")


def paste_text(window_handle: int, text: str) -> dict[str, Any]:
    """Paste Unicode text into one MuMu instance using Win32 only."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    user32, kernel32 = _windows_api()
    handle = _parse_window_handle(window_handle)

    with _INPUT_LOCK:
        had_text, previous_text = _read_clipboard_text(user32, kernel32)
        try:
            _write_clipboard_text(user32, kernel32, text)
            root = _activate_window(user32, kernel32, handle)
            _send_ctrl_v(user32)
            # Let MuMu consume WM_PASTE before restoring the user's clipboard.
            time.sleep(0.15)
        finally:
            if had_text:
                _write_clipboard_text(user32, kernel32, previous_text)
            else:
                _clear_clipboard(user32)

    return {
        "method": "win32_clipboard",
        "window_handle": f"0x{handle:X}",
        "root_window_handle": f"0x{root:X}",
    }
