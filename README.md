# pymumu

A Python API for controlling and managing **MuMu Player** Android emulator — inspired by [pymemuc](https://github.com/pyclashbot/pymemuc).

## Features

- Auto-detect MuMu Player installation via Windows Registry
- Start, stop, restart, clone, and delete emulator instances
- Control app lifecycle (install, uninstall, launch, close)
- ADB shell commands and key events
- Window management (show, hide, layout)
- Simulate device properties (Android ID, MAC, IMEI)
- GPS location spoofing
- Import/export instances as `.mumudata` files
- Tap, swipe, long press via shell

---

## Requirements

- Windows 10/11
- [MuMu Player](https://www.mumuplayer.com/) installed
- Python 3.8+

---

## Installation

```bash
pip install pymumu
```

Or install from source:

```bash
git clone https://github.com/rhuda21/pymumu
cd pymumu
pip install -e .
```

---

## Quick Start

```python
from pymumu import PyMumu

# auto detect MuMu installation
mumu = PyMumu()

# or pass path manually
mumu = PyMumu(path=r"C:\Program Files\Netease\MuMuPlayer\nx_main\MumuManager.exe")

print(mumu)
# PyMumu(path='C:\...MumuManager.exe', index=0)
```

---

## Usage

### Instance Management

```python
# get version and info
mumu.version()
mumu.info(index=0)

# lifecycle
mumu.start(index=0)
mumu.stop(index=0)
mumu.restart(index=0)

# management
mumu.create()
mumu.clone(index=0, number=3)   # clone 3 times
mumu.delete(index=1)
mumu.rename("MyDevice", index=0)

# import / export
mumu.import_player(r"C:\backup.mumudata")
mumu.export_player(index=0, directory=r"C:\backups", zip=True)
```

### Window Control

```python
mumu.show_window(index=0)
mumu.hide_window(index=0)
mumu.layout_window(x=0, y=0, width=720, height=1280, index=0)
mumu.sort()
```

### App Control

```python
mumu.app_install(r"C:\Downloads\app.apk", index=0)
mumu.app_uninstall("com.example.app", index=0)
mumu.app_launch("com.example.app", index=0)
mumu.app_close("com.example.app", index=0)
mumu.app_info("com.example.app", index=0)
mumu.app_info(index=0)  # list all installed apps
```

### ADB & Shell

```python
# adb commands
mumu.adb_connect(index=0)
mumu.adb_cmd("connect", index=0)

# shell commands
mumu.shell("input tap 500 500", index=0)
mumu.getprop("ro.build.version.release", index=0)
mumu.setprop("ro.build.version.release", "12", index=0)
```

### Touch & Input

```python
mumu.tap(500, 500, index=0)
mumu.swipe(100, 500, 600, 500, duration_ms=300, index=0)
mumu.long_press(500, 500, duration_ms=900, index=0)
# Uses physical Windows keys for ASCII and persistent clipboard paste for Chinese.
# Neither path uses ADB.
mumu.input_text("随风而动", index=0)
```

### Key Events

```python
mumu.key_back(index=0)
mumu.key_home(index=0)
mumu.key_task(index=0)
mumu.key_enter(index=0)
mumu.volume_up(index=0)
mumu.volume_down(index=0)
mumu.volume_mute(index=0)
```

### Toolbar

```python
mumu.tool_func("screenshot", index=0)
mumu.tool_func("rotate", index=0)
mumu.tool_location(longitude=-0.1276, latitude=51.5074, index=0)  # London
mumu.tool_downcpu(cap=50, index=0)
mumu.tool_gyro(x=0.0, y=9.8, z=0.0, index=0)
```

### Simulation

```python
mumu.set_android_id("abc123", index=0)
mumu.set_mac_address("00:11:22:33:44:55", index=0)
mumu.set_imei("123456789012345", index=0)
mumu.set_simulation("android_id", "__null__", index=0)  # clear
```

### Settings

```python
mumu.get_setting("root_permission", index=0)
mumu.set_setting("root_permission", "true", index=0)
mumu.get_all_settings(index=0)
mumu.set_settings_from_file(r"C:\settings.json", index=0)
```

### Shortcuts & Drivers

```python
mumu.shortcut_create(index=0)
mumu.shortcut_delete(index=0)
mumu.driver_install()
mumu.driver_uninstall()
```

### Logging

```python
mumu.log_on()
mumu.log_off()
```

---

## HTTP control service

Install the service extras on the Windows machine that runs MuMu Player:

```powershell
pip install -e ".[service]"
pymumu-service --host 0.0.0.0 --port 8765
```

The service exposes native MuMu controls at:

- `POST /api/v1/emulators/{index}/control`
- `GET /api/v1/emulators/{index}/screenshot`
- `GET /api/v1/emulators/{index}/current-app`
- `POST /api/v1/emulators/{index}/files`

These routes execute `MumuManager.exe` and never execute `adb.exe`. If an
existing FastAPI application already manages MuMu instance lifecycle, mount
the router into it so lifecycle and control share one base URL:

```python
from fastapi import FastAPI
from pymumu.server import create_router

app = FastAPI()
app.include_router(create_router())
```

AutoGLM may continue to use its existing scrcpy connection for the live video
stream. Input, screenshots used by agents, app launch, file transfer and key
events are handled by this service.

---

## Multiple Instances

```python
# use index parameter on any method
mumu.start(index=0)
mumu.start(index=1)
mumu.start(index=2)

# or set default index
mumu = PyMumu(index=2)
mumu.start()  # starts instance 2
```

---

## Error Handling

```python
from pymumu import PyMumu, MuMuException, MuMuNotFoundError

try:
    mumu = PyMumu()
    mumu.start(index=0)
except MuMuNotFoundError:
    print("MuMu Player not found!")
except MuMuException as e:
    print(f"Error: {e}")
```

### Exceptions

| Exception | Description |
|---|---|
| `MuMuException` | Base exception for all pymumu errors |
| `MuMuNotFoundError` | MuMu Player installation not found |
| `EmulatorNotRunningError` | Emulator is not running |
| `AdbCommandError` | ADB command failed |
| `InvalidInstanceError` | Invalid emulator index |

---

## Project Structure

```
src/pymumu/
├── __init__.py       # public API
├── pymumu.py         # main class
├── instance.py       # instance management mixin
├── control.py        # app/tool/settings mixin
├── adb.py            # adb/shell/keyevents mixin
├── utils.py          # _run, _find_mumu
└── exception.py      # custom exceptions
```

---

## License

MIT
