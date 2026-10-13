import time

from .windows_input import get_instance_window, mouse_gesture, paste_text, send_key


class ControlMixin:
    def _instance_window(self, index=None, refresh=False):
        idx = index if index is not None else self.index
        cached = getattr(self, "_cached_window_handle", None)
        if cached is None or refresh:
            cached = get_instance_window(self.info(index=idx))
            self._cached_window_handle = cached
        return cached

    def _mouse_gesture(self, *args, index=None):
        try:
            return mouse_gesture(self._instance_window(index), *args)
        except RuntimeError as error:
            if "window no longer exists" not in str(error):
                raise
            return mouse_gesture(self._instance_window(index, refresh=True), *args)

    def _send_key(self, key, index=None):
        try:
            return send_key(self._instance_window(index), key)
        except RuntimeError as error:
            if "window no longer exists" not in str(error):
                raise
            return send_key(self._instance_window(index, refresh=True), key)

    def prepare_control(self, index=None):
        """Resolve and cache the render window before interactive input starts."""
        return {"window_handle": f"0x{self._instance_window(index, refresh=True):X}"}

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

    def tool_command(self, command: str, index=None):
        """Run a MuMu native tool command without invoking the ADB executable."""
        idx = index if index is not None else self.index
        return self._run("control", "-v", idx, "tool", "cmd", "-c", command)

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
            "volume_up",
            "volume_down",
            "volume_mute",
        }
        if key in fast_keys:
            return self._send_key(key, index=index)
        functions = {
            "back": "go_back",
            "home": "go_home",
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
