import json
import os
import shutil
import time

from .exception import MuMuException


class SharesMixin:
    def __init__(self):
        self.shared_folder_path = None

    def _get_shared_folder_path(self):
        """Determine the path to the shared folder used for file transfers."""
        exe = self.path
        base = os.path.dirname(exe)
        mumu_root = os.path.dirname(base)
        configs_dir = os.path.join(mumu_root, "configs")
        vm_config = os.path.join(configs_dir, "vm_config.json")
        with open(vm_config, "r") as f:
            config = json.load(f)
        self.shared_folder_path = config["vm"]["sharefolder"]["user"]["path"]
        return self.shared_folder_path

    def _copy_to_shared_folder(self, local_path: str, shared_subpath: str):
        """Copy a file to the shared folder
        Args:
            local_path: Path to local file to copy
            shared_subpath: Relative path inside shared folder (can include subdirectories)
        Returns:
            str: Destination path if successful, None if failed
        """
        try:
            if self.shared_folder_path is None:
                self._get_shared_folder_path()
            dest_path = os.path.join(self.shared_folder_path, shared_subpath)
            dest_dir = os.path.dirname(dest_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(local_path, dest_path)
            if os.path.exists(dest_path):
                print(f"✓ Copied to: {dest_path}")
                return dest_path
            else:
                print(f"✗ Copy failed: {dest_path}")
                return None
        except FileNotFoundError:
            raise FileNotFoundError(f"Local file not found: {local_path}")
        except Exception as e:
            raise MuMuException(f"Error copying file to shared folder: {e}")

    def _get_latest_file(self, shared_subpath: str):
        """Get the latest file from the shared folder
        Args:
            shared_subpath: Relative path inside shared folder (can include subdirectories)
        Returns:
            str: Path to the latest file, or None if not found
        """
        try:
            if self.shared_folder_path is None:
                self._get_shared_folder_path()
            full_path = os.path.join(self.shared_folder_path, shared_subpath)
            if os.path.isdir(full_path):
                files = os.listdir(full_path)
                if not files:
                    return None
                latest_file = max(
                    files, key=lambda f: os.path.getctime(os.path.join(full_path, f))
                )
                return os.path.join(full_path, latest_file)
            elif os.path.isfile(full_path):
                return full_path
            else:
                return None
        except Exception as e:
            raise MuMuException(f"Error getting latest file from shared folder: {e}")

    def _get_latest_screenshot(self, index=None):
        """Get the latest screenshot from the shared folder"""
        folder = self._get_shared_folder_path()
        screenshots_path = os.path.join(folder, "Screenshots")
        os.makedirs(screenshots_path, exist_ok=True)
        before = {
            path: os.path.getmtime(os.path.join(screenshots_path, path))
            for path in os.listdir(screenshots_path)
        }
        requested_at = time.time()
        self.tool_func("screenshot", index=index)
        deadline = requested_at + 10
        while time.time() < deadline:
            latest = self._get_latest_file("Screenshots")
            if latest:
                name = os.path.basename(latest)
                modified = os.path.getmtime(latest)
                if name not in before or modified > before[name]:
                    return latest
            time.sleep(0.1)
        raise TimeoutError("MuMu screenshot was not created within 10 seconds")
