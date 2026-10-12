"""HTTP control service for MuMu Player.

The service intentionally exposes only MumuManager-backed operations. It does
not import, execute, or connect to ADB. AutoGLM can therefore keep scrcpy for
video while routing every MuMu control action through this service.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import struct
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .pymumu import PyMumu


class ControlRequest(BaseModel):
    action: Literal[
        "tap",
        "double_tap",
        "long_press",
        "swipe",
        "touch_down",
        "touch_move",
        "touch_up",
        "text",
        "clear_text",
        "key",
        "launch_app",
        "close_app",
    ]
    x: int | None = Field(default=None, ge=0, le=10000)
    y: int | None = Field(default=None, ge=0, le=10000)
    start_x: int | None = Field(default=None, ge=0, le=10000)
    start_y: int | None = Field(default=None, ge=0, le=10000)
    end_x: int | None = Field(default=None, ge=0, le=10000)
    end_y: int | None = Field(default=None, ge=0, le=10000)
    duration_ms: int = Field(default=300, ge=0, le=10000)
    text: str | None = Field(default=None, max_length=20000)
    key: str | None = None
    package: str | None = None


def _required(value: Any, name: str) -> Any:
    if value is None:
        raise HTTPException(status_code=422, detail=f"{name} is required")
    return value


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("MuMu screenshot is not a valid PNG")
    return struct.unpack(">II", data[16:24])


def create_router(manager_path: str | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/emulators", tags=["MuMu control"])
    current_packages: dict[int, str] = {}

    def manager(index: int) -> PyMumu:
        return PyMumu(
            path=manager_path or os.getenv("PYMUMU_MANAGER_PATH"), index=index
        )

    @router.post("/{index}/control")
    def control(index: int, request: ControlRequest) -> dict[str, Any]:
        mumu = manager(index)
        try:
            action = request.action
            if action in {
                "tap",
                "double_tap",
                "long_press",
                "touch_down",
                "touch_move",
                "touch_up",
            }:
                x, y = _required(request.x, "x"), _required(request.y, "y")
                if action == "tap":
                    result = mumu.tap(x, y)
                elif action == "double_tap":
                    result = mumu.double_tap(x, y)
                elif action == "long_press":
                    result = mumu.long_press(x, y, request.duration_ms)
                else:
                    result = getattr(mumu, action)(x, y)
            elif action == "swipe":
                result = mumu.swipe(
                    _required(request.start_x, "start_x"),
                    _required(request.start_y, "start_y"),
                    _required(request.end_x, "end_x"),
                    _required(request.end_y, "end_y"),
                    request.duration_ms,
                )
            elif action == "text":
                result = mumu.input_text(_required(request.text, "text"))
            elif action == "clear_text":
                result = mumu.clear_text()
            elif action == "key":
                result = mumu.key_event(_required(request.key, "key"))
                if request.key == "home":
                    current_packages.pop(index, None)
            elif action == "launch_app":
                package = _required(request.package, "package")
                result = mumu.app_launch(package)
                current_packages[index] = package
            else:
                package = _required(request.package, "package")
                result = mumu.app_close(package)
                if current_packages.get(index) == package:
                    current_packages.pop(index, None)
            return {"success": True, "result": result}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/{index}/screenshot")
    def screenshot(index: int) -> dict[str, Any]:
        try:
            path = manager(index)._get_latest_screenshot(index=index)
            if not path:
                raise RuntimeError("MuMu did not produce a screenshot")
            data = Path(path).read_bytes()
            width, height = _png_size(data)
            return {
                "success": True,
                "image": base64.b64encode(data).decode("ascii"),
                "width": width,
                "height": height,
                "is_sensitive": False,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/{index}/current-app")
    def current_app(index: int) -> dict[str, Any]:
        """Return the app last launched through the native MuMu control API."""
        return {"success": True, "package": current_packages.get(index, "")}

    @router.post("/{index}/files")
    def upload_file(index: int, file: UploadFile = File(...)) -> dict[str, Any]:
        """Copy a file into MuMu's native shared folder without using ADB."""
        safe_name = Path(file.filename or "upload.bin").name
        if safe_name in {"", ".", ".."}:
            raise HTTPException(status_code=400, detail="invalid filename")
        try:
            mumu = manager(index)
            shared_root = Path(mumu._get_shared_folder_path())
            target_dir = shared_root / "Download" / "AutoGLM"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{int(time.time() * 1000)}-{safe_name}"
            with target.open("wb") as output:
                shutil.copyfileobj(file.file, output)
            return {
                "success": True,
                "filename": target.name,
                "path": str(target),
                "size": target.stat().st_size,
                "media_scanned": True,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return router


def create_app(manager_path: str | None = None) -> FastAPI:
    app = FastAPI(title="pymumu service", version="0.2.0")
    app.include_router(create_router(manager_path))
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve pymumu controls over HTTP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--manager-path", default=None)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(create_app(args.manager_path), host=args.host, port=args.port)


app = create_app()
