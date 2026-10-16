import re
import subprocess
import time
from urllib.parse import urlsplit
from xml.etree import ElementTree

from .exception import MuMuException
from .windows_input import (
    get_instance_window,
    get_render_window,
    mouse_gesture,
    paste_text,
    send_key,
)


class ControlMixin:
    _RENDER_WINDOW_WAIT_TIMEOUT = 10.0
    _RENDER_WINDOW_POLL_INTERVAL = 0.2

    def _instance_window(self, index=None, refresh=False):
        idx = index if index is not None else self.index
        cached = getattr(self, "_cached_window_handle", None)
        if cached is None or refresh:
            cached = get_instance_window(self.info(index=idx))
            self._cached_window_handle = cached
        return cached

    def _render_window(self, index=None, refresh=False):
        idx = index if index is not None else self.index
        cached = getattr(self, "_cached_render_window_handle", None)
        if cached is None or refresh:
            cached = self._wait_for_render_window(idx)
            self._cached_render_window_handle = cached
            self._cached_window_handle = cached
        return cached

    def _wait_for_render_window(self, index):
        deadline = time.monotonic() + self._RENDER_WINDOW_WAIT_TIMEOUT
        while True:
            try:
                return get_render_window(self.info(index=index))
            except RuntimeError as error:
                if (
                    str(error) != "MuMu render window is not ready"
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(self._RENDER_WINDOW_POLL_INTERVAL)

    def _mouse_gesture(self, *args, index=None):
        try:
            return mouse_gesture(self._render_window(index), *args)
        except RuntimeError as error:
            if "window no longer exists" not in str(error):
                raise
            return mouse_gesture(self._render_window(index, refresh=True), *args)

    def _send_key(self, key, index=None):
        try:
            return send_key(self._instance_window(index), key)
        except RuntimeError as error:
            if "window no longer exists" not in str(error):
                raise
            return send_key(self._instance_window(index, refresh=True), key)

    def prepare_control(self, index=None):
        """Wait for and cache the Android render HWND before accepting input."""
        idx = index if index is not None else self.index
        render_handle = self._wait_for_render_window(idx)
        self._cached_render_window_handle = render_handle
        self._cached_window_handle = render_handle
        return {"window_handle": f"0x{render_handle:X}"}

    # App Control
    def app_install(self, apk_path: str, index=None):
        """Install an apk/apks/xapk"""
        idx = index if index is not None else self.index
        return self._run("control", "-v", idx, "app", "install", "--apk", apk_path)

    def app_uninstall(self, package: str, index=None):
        """Uninstall an app by package id"""
        idx = index if index is not None else self.index
        return self._run("control", "-v", idx, "app", "uninstall", "--package", package)

    def app_launch(self, package: str, index=None):
        """Launch an app by package id"""
        idx = index if index is not None else self.index
        return self._run("control", "-v", idx, "app", "launch", "--package", package)

    def app_close(self, package: str, index=None):
        """Close an app by package id"""
        idx = index if index is not None else self.index
        return self._run("control", "-v", idx, "app", "close", "--package", package)

    def app_info(self, package: str = None, index=None):
        """Get app info or list all installed apps"""
        idx = index if index is not None else self.index
        if package:
            return self._run("control", "-v", idx, "app", "info", "--package", package)
        return self._run("control", "-v", idx, "app", "info", "--installed")

    # Toolbar
    def tool_func(self, name: str, index=None):
        """Trigger a toolbar function.
        Options: rotate, go_home, go_back, top_most, fullscreen,
                 shake, screenshot, volume_up, volume_down, volume_mute
        """
        idx = index if index is not None else self.index
        return self._run("control", "-v", idx, "tool", "func", "--name", name)

    def tool_command(self, command: str, index=None, timeout=30):
        """Run a MuMu native tool command without invoking the ADB executable."""
        idx = index if index is not None else self.index
        return self._run(
            "control", "-v", idx, "tool", "cmd", "-c", command, timeout=timeout
        )

    def open_url(self, url: str, index=None):
        """Open an HTTP(S) or app deep link through MuMuManager, without ADB."""
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https", "xhsdiscover"}:
            raise ValueError("Unsupported URL scheme")
        # The generated XHS link is passed through Android's shell. Escape the
        # few characters with meaning inside a double-quoted shell argument.
        quoted = url.replace("\\", "\\\\").replace('"', '\\"')
        quoted = quoted.replace("$", "\\$").replace("`", "\\`")
        command = f'am start -a android.intent.action.VIEW -d "{quoted}"'
        idx = index if index is not None else self.index
        try:
            return self._run(
                "control", "-v", idx, "tool", "cmd", "-c", command, timeout=8
            )
        except subprocess.TimeoutExpired:
            # Some MuMuManager versions keep their CLI process alive after the
            # Android intent has already been delivered. subprocess.run kills
            # only that CLI process; the launched Android activity keeps running.
            return {"dispatched": True, "manager_cli_timed_out": True}

    @staticmethod
    def _ui_xml(value):
        text = value if isinstance(value, str) else str(value or "")
        start = text.find("<?xml")
        if start < 0:
            start = text.find("<hierarchy")
        end = text.rfind("</hierarchy>")
        if start >= 0 and end < start:
            empty = re.match(r"<hierarchy\b[^>]*/>", text[start:])
            if empty:
                return empty.group(0)
        if start < 0 or end < start:
            raise RuntimeError("MuMu UI hierarchy is not ready")
        return text[start : end + len("</hierarchy>")]

    def _dump_ui_xml(self, index=None):
        """Read Android's UI hierarchy through MuMuManager's command channel."""
        idx = index if index is not None else self.index
        # MuMuManager can keep a foreground `uiautomator dump` command alive
        # after Android has started producing the hierarchy. Launch exactly one
        # detached dump, then read its uniquely named result through a separate
        # native command. Avoiding a preceding /dev/tty dump also prevents an
        # orphaned first process from blocking the file-producing process.
        path = f"/sdcard/autoglm-window-{idx}-{time.monotonic_ns()}.xml"
        launch_output = ""
        try:
            launch_output = self.tool_command(
                f"rm -f {path}; "
                f"(uiautomator dump {path} </dev/null >/dev/null 2>&1) &",
                index=idx,
                timeout=2,
            )
        except (MuMuException, subprocess.TimeoutExpired):
            # The detached Android command can continue after its manager
            # wrapper is terminated, so still try to read the result.
            pass
        try:
            return self._ui_xml(launch_output)
        except RuntimeError:
            output = self.tool_command(
                "i=0; "
                f"while [ \"$i\" -lt 10 ]; do "
                f"if [ -s {path} ]; then cat {path}; rm -f {path}; exit 0; fi; "
                "sleep 1; i=$((i + 1)); done; "
                f"rm -f {path}; exit 1",
                index=idx,
                timeout=12,
            )
            return self._ui_xml(output)

    @staticmethod
    def _matching_ui_nodes(
        root,
        *,
        text=None,
        text_contains=None,
        resource_id=None,
        class_name=None,
        package_name=None,
        clickable=None,
        enabled=None,
    ):
        matches = []
        for node in root.iter("node"):
            attributes = node.attrib
            node_text = attributes.get("text", "")
            if text is not None and node_text != text:
                continue
            if text_contains is not None and text_contains not in node_text:
                continue
            if resource_id and attributes.get("resource-id") != resource_id:
                continue
            if class_name and attributes.get("class") != class_name:
                continue
            if package_name and attributes.get("package") != package_name:
                continue
            if clickable is not None and attributes.get("clickable") != str(clickable).lower():
                continue
            if enabled is not None and attributes.get("enabled") != str(enabled).lower():
                continue
            matches.append(node)
        return matches

    def find_and_tap(
        self,
        *,
        text: str | None = None,
        text_contains: str | None = None,
        resource_id: str | None = None,
        class_name: str | None = None,
        package_name: str | None = None,
        selector_index: int = 0,
        clickable: bool | None = None,
        enabled: bool | None = None,
        required_text: str | None = None,
        required_text_contains: str | None = None,
        timeout_ms: int = 30000,
        optional: bool = False,
        wait_until_focused: bool = False,
        wait_until_gone: bool = False,
        index=None,
    ):
        """Wait for one Android UI node and tap its center through MuMuManager."""
        if not any((text, text_contains, resource_id, class_name, package_name)):
            raise ValueError("At least one UI selector is required")
        if selector_index < 0:
            raise ValueError("selector_index must be non-negative")
        idx = index if index is not None else self.index
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        last_error = "element not found"

        def find(root):
            if required_text is not None or required_text_contains is not None:
                guards = self._matching_ui_nodes(
                    root,
                    text=required_text,
                    text_contains=required_text_contains,
                    package_name=package_name,
                    enabled=True,
                )
                if not guards:
                    return None
            matches = self._matching_ui_nodes(
                root,
                text=text,
                text_contains=text_contains,
                resource_id=resource_id,
                class_name=class_name,
                package_name=package_name,
                clickable=clickable,
                enabled=enabled,
            )
            return matches[selector_index] if selector_index < len(matches) else None

        while True:
            try:
                root = ElementTree.fromstring(self._dump_ui_xml(index=idx))
                node = find(root)
                if node is not None:
                    bounds = node.attrib.get("bounds", "")
                    match = re.fullmatch(r"\[(\d+),(\d+)]\[(\d+),(\d+)]", bounds)
                    if not match:
                        raise RuntimeError("Matched UI element has invalid bounds")
                    left, top, right, bottom = map(int, match.groups())
                    self.tool_tap((left + right) // 2, (top + bottom) // 2, index=idx)
                    if not wait_until_focused and not wait_until_gone:
                        return {"text": node.attrib.get("text", ""), "bounds": bounds}
                    while time.monotonic() < deadline:
                        time.sleep(0.5)
                        current = ElementTree.fromstring(self._dump_ui_xml(index=idx))
                        current_node = find(current)
                        if wait_until_gone and current_node is None:
                            return {
                                "text": node.attrib.get("text", ""),
                                "bounds": bounds,
                                "gone": True,
                            }
                        if (
                            wait_until_focused
                            and current_node is not None
                            and current_node.attrib.get("focused") == "true"
                        ):
                            return {
                                "text": current_node.attrib.get("text", ""),
                                "bounds": current_node.attrib.get("bounds", bounds),
                                "focused": True,
                            }
                    expected = text or text_contains or class_name or package_name
                    state = "disappear" if wait_until_gone else "receive focus"
                    raise RuntimeError(f"UI element did not {state}: {expected}")
                expected = text or text_contains or class_name or package_name
                last_error = f"UI element not found: {expected} (index {selector_index})"
            except (
                ElementTree.ParseError,
                RuntimeError,
                subprocess.TimeoutExpired,
            ) as error:
                last_error = str(error)
            if time.monotonic() >= deadline:
                if optional:
                    return {"found": False}
                raise RuntimeError(last_error)
            time.sleep(0.5)

    def wait_for_ui(
        self,
        *,
        class_name: str,
        package_name: str | None = None,
        minimum_matches: int = 1,
        clickable: bool | None = None,
        enabled: bool | None = None,
        required_text: str | None = None,
        required_text_contains: str | None = None,
        required_class_name: str | None = None,
        required_clickable: bool | None = None,
        required_enabled: bool | None = None,
        dismiss_text: str | None = None,
        dismiss_class_name: str | None = None,
        dismiss_required_text: str | None = None,
        timeout_ms: int = 30000,
        index=None,
    ):
        """Wait for a compound UI signature without clicking any element."""
        if minimum_matches < 1:
            raise ValueError("minimum_matches must be positive")
        deadline = time.monotonic() + max(0, timeout_ms) / 1000
        last_counts = (0, 0)
        dismissed = 0
        while True:
            result = self.check_ui(
                class_name=class_name,
                package_name=package_name,
                minimum_matches=minimum_matches,
                clickable=clickable,
                enabled=enabled,
                required_text=required_text,
                required_text_contains=required_text_contains,
                required_class_name=required_class_name,
                required_clickable=required_clickable,
                required_enabled=required_enabled,
                dismiss_text=dismiss_text,
                dismiss_class_name=dismiss_class_name,
                dismiss_required_text=dismiss_required_text,
                index=index,
            )
            dismissed += result["dismissed"]
            last_counts = (result["matches"], result["required_matches"])
            if result["ready"]:
                return {**result, "dismissed": dismissed}
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "UI signature not ready: "
                    f"{last_counts[0]}/{minimum_matches} primary nodes, "
                    f"{last_counts[1]} required nodes"
                )
            time.sleep(0.5)

    def check_ui(
        self,
        *,
        class_name: str,
        package_name: str | None = None,
        minimum_matches: int = 1,
        clickable: bool | None = None,
        enabled: bool | None = None,
        required_text: str | None = None,
        required_text_contains: str | None = None,
        required_class_name: str | None = None,
        required_clickable: bool | None = None,
        required_enabled: bool | None = None,
        dismiss_text: str | None = None,
        dismiss_class_name: str | None = None,
        dismiss_required_text: str | None = None,
        index=None,
    ):
        """Check one UI snapshot and optionally dismiss one matching dialog."""
        if minimum_matches < 1:
            raise ValueError("minimum_matches must be positive")
        idx = index if index is not None else self.index
        try:
            root = ElementTree.fromstring(self._dump_ui_xml(index=idx))
            if dismiss_text and dismiss_required_text:
                dismiss_guards = self._matching_ui_nodes(
                    root,
                    text=dismiss_required_text,
                    package_name=package_name,
                    enabled=True,
                )
                dismiss_nodes = self._matching_ui_nodes(
                    root,
                    text=dismiss_text,
                    class_name=dismiss_class_name,
                    package_name=package_name,
                    clickable=True,
                    enabled=True,
                )
                if dismiss_guards and dismiss_nodes:
                    bounds = dismiss_nodes[0].attrib.get("bounds", "")
                    match = re.fullmatch(
                        r"\[(\d+),(\d+)]\[(\d+),(\d+)]", bounds
                    )
                    if not match:
                        raise RuntimeError("Dismiss UI element has invalid bounds")
                    left, top, right, bottom = map(int, match.groups())
                    self.tool_tap(
                        (left + right) // 2,
                        (top + bottom) // 2,
                        index=idx,
                    )
                    return {
                        "ready": False,
                        "matches": 0,
                        "required_matches": 0,
                        "dismissed": 1,
                    }
            primary = self._matching_ui_nodes(
                root,
                class_name=class_name,
                package_name=package_name,
                clickable=clickable,
                enabled=enabled,
            )
            guards = self._matching_ui_nodes(
                root,
                text=required_text,
                text_contains=required_text_contains,
                class_name=required_class_name,
                package_name=package_name,
                clickable=required_clickable,
                enabled=required_enabled,
            )
            guard_ready = (
                required_text is None
                and required_text_contains is None
                and required_class_name is None
            ) or bool(guards)
            return {
                "ready": len(primary) >= minimum_matches and guard_ready,
                "matches": len(primary),
                "required_matches": len(guards),
                "dismissed": 0,
            }
        except (
            ElementTree.ParseError,
            MuMuException,
            RuntimeError,
            subprocess.TimeoutExpired,
        ) as error:
            return {
                "ready": False,
                "matches": 0,
                "required_matches": 0,
                "dismissed": 0,
                "error": str(error),
            }

    def tool_tap(
        self,
        x: int,
        y: int,
        index=None,
        device_width=None,
        device_height=None,
    ):
        """Tap at position (x, y)"""
        idx = index if index is not None else self.index
        if device_width and device_height:
            return self._mouse_gesture(
                x,
                y,
                x,
                y,
                device_width,
                device_height,
                index=idx,
            )
        return self.tool_command(f"input tap {x} {y}", index=idx)

    def tool_swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 100,
        index=None,
        device_width=None,
        device_height=None,
    ):
        """Swipe from (x1, y1) to (x2, y2)"""
        idx = index if index is not None else self.index
        if device_width and device_height:
            return self._mouse_gesture(
                x1,
                y1,
                x2,
                y2,
                device_width,
                device_height,
                duration_ms,
                index=idx,
            )
        return self.tool_command(
            f"input swipe {x1} {y1} {x2} {y2} {duration_ms}", index=idx
        )

    def tool_long_press(self, x: int, y: int, duration_ms: int = 900, index=None):
        """Long press at position (x, y)"""
        idx = index if index is not None else self.index
        return self.tool_command(
            f"input swipe {x} {y} {x} {y} {duration_ms}", index=idx
        )

    def tool_input_text(self, text: str, index=None):
        """Input Unicode text through the instance's native Windows window."""
        idx = index if index is not None else self.index
        window_handle = self._instance_window(idx)
        return paste_text(window_handle, text)

    # High-level input API. Touch/key operations use MumuManager's control
    # channel; text uses the instance's Win32 window. None use ADB.
    def tap(
        self,
        x: int,
        y: int,
        index=None,
        device_width=None,
        device_height=None,
    ):
        return self.tool_tap(
            x,
            y,
            index=index,
            device_width=device_width,
            device_height=device_height,
        )

    def double_tap(self, x: int, y: int, interval_ms: int = 100, index=None):
        result = self.tool_tap(x, y, index=index)
        time.sleep(max(0, interval_ms) / 1000)
        self.tool_tap(x, y, index=index)
        return result

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        index=None,
        device_width=None,
        device_height=None,
    ):
        return self.tool_swipe(
            x1,
            y1,
            x2,
            y2,
            duration_ms,
            index=index,
            device_width=device_width,
            device_height=device_height,
        )

    def long_press(self, x: int, y: int, duration_ms: int = 900, index=None):
        return self.tool_long_press(x, y, duration_ms, index=index)

    def touch_down(self, x: int, y: int, index=None):
        return self.tool_command(f"input motionevent DOWN {x} {y}", index=index)

    def touch_move(self, x: int, y: int, index=None):
        return self.tool_command(f"input motionevent MOVE {x} {y}", index=index)

    def touch_up(self, x: int, y: int, index=None):
        return self.tool_command(f"input motionevent UP {x} {y}", index=index)

    def input_text(self, text: str, index=None):
        return self.tool_input_text(text, index=index)

    def clear_text(self, index=None):
        # Select all and delete through MuMu's native command channel.
        self.tool_command(
            "input keycombination KEYCODE_CTRL_LEFT KEYCODE_A", index=index
        )
        return self.tool_command("input keyevent KEYCODE_DEL", index=index)

    def key_event(self, key: str, index=None):
        fast_keys = {
            "delete",
            "enter",
            "space",
        }
        if key in fast_keys:
            return self._send_key(key, index=index)
        functions = {
            "back": "go_back",
            "home": "go_home",
            "volume_up": "volume_up",
            "volume_down": "volume_down",
            "volume_mute": "volume_mute",
        }
        commands = {
            "recents": "input keyevent KEYCODE_APP_SWITCH",
            "power": "input keyevent KEYCODE_POWER",
        }
        if key in functions:
            return self.tool_func(functions[key], index=index)
        if key in commands:
            return self.tool_command(commands[key], index=index)
        raise ValueError(f"Unsupported MuMu key: {key}")

    def tool_location(self, longitude: float, latitude: float, index=None):
        """Update GPS location. longitude: -180~180, latitude: -90~90"""
        idx = index if index is not None else self.index
        return self._run(
            "control",
            "-v",
            idx,
            "tool",
            "location",
            "--longitude",
            longitude,
            "--latitude",
            latitude,
        )

    def tool_downcpu(self, cap: int, index=None):
        """Set CPU execution cap (1-100)"""
        idx = index if index is not None else self.index
        return self._run("control", "-v", idx, "tool", "downcpu", "--cap", cap)

    def tool_gyro(self, x: float, y: float, z: float, index=None):
        """Change gravity sensing values"""
        idx = index if index is not None else self.index
        return self._run(
            "control",
            "-v",
            idx,
            "tool",
            "gyro",
            "--gyro_x",
            x,
            "--gyro_y",
            y,
            "--gyro_z",
            z,
        )

    # Simulation
    def set_simulation(self, key: str, value: str, index=None):
        """Change simulated properties.
        Keys: android_id, mac_address, imei
        Use '__null__' to clear value
        """
        idx = index if index is not None else self.index
        return self._run(
            "simulation", "-v", idx, "--simu_key", key, "--simu_value", value
        )

    def set_android_id(self, value: str, index=None):
        """Simulate Android ID"""
        return self.set_simulation("android_id", value, index)

    def set_mac_address(self, value: str, index=None):
        """Simulate MAC address"""
        return self.set_simulation("mac_address", value, index)

    def set_imei(self, value: str, index=None):
        """Simulate IMEI"""
        return self.set_simulation("imei", value, index)

    # Settings
    def get_setting(self, key: str, index=None):
        """Get a player setting value"""
        idx = index if index is not None else self.index
        return self._run("setting", "-v", idx, "--key", key)

    def set_setting(self, key: str, value: str, index=None):
        """Set a player setting value. Use '__null__' to clear"""
        idx = index if index is not None else self.index
        return self._run("setting", "-v", idx, "--key", key, "--value", value)

    def enable_root(self, index=None):
        """Enable root permission for a player"""
        idx = index if index is not None else self.index
        return self._run(
            "setting", "-v", idx, "--key", "root_permission", "--value", "true"
        )

    def get_all_settings(self, index=None):
        """Get all settings for a player"""
        idx = index if index is not None else self.index
        return self._run("setting", "-v", idx, "--all")

    def set_settings_from_file(self, json_path: str, index=None):
        """Apply settings from a .json file"""
        idx = index if index is not None else self.index
        return self._run("setting", "-v", idx, "--path", json_path)
