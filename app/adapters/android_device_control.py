import re
import shutil
import subprocess
from typing import Any


class AndroidDeviceControlError(RuntimeError):
    pass


class AndroidDeviceControl:
    _serial_pattern = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
    _safe_text_pattern = re.compile(r"^[A-Za-z0-9 @._+\-:/]{1,256}$")
    _keyevents = {
        "back": "KEYCODE_BACK",
        "home": "KEYCODE_HOME",
        "recent": "KEYCODE_APP_SWITCH",
        "enter": "KEYCODE_ENTER",
        "delete": "KEYCODE_DEL",
    }

    def __init__(
        self,
        *,
        serial: str,
        adb_binary: str = "adb",
        timeout_seconds: float = 10,
    ) -> None:
        serial = serial.strip()
        if not self._serial_pattern.fullmatch(serial):
            raise ValueError("Android ADB serial 格式不正确")
        if not adb_binary.strip():
            raise ValueError("ADB 可执行文件不能为空")
        if timeout_seconds <= 0:
            raise ValueError("ADB 超时时间必须大于 0")
        self.serial = serial
        self.adb_binary = adb_binary.strip()
        self.timeout_seconds = min(float(timeout_seconds), 30.0)

    def status(self) -> dict[str, Any]:
        self._ensure_available()
        state = self._run_text(["-s", self.serial, "get-state"])
        size_text = self._run_text(
            ["-s", self.serial, "shell", "wm", "size"]
        )
        size_match = re.search(r"(\d{2,5})x(\d{2,5})", size_text)
        width = int(size_match.group(1)) if size_match else None
        height = int(size_match.group(2)) if size_match else None
        return {
            "online": state == "device",
            "state": state,
            "width": width,
            "height": height,
        }

    def screenshot(self) -> bytes:
        self._ensure_available()
        data = self._run_bytes(
            ["-s", self.serial, "exec-out", "screencap", "-p"]
        )
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise AndroidDeviceControlError("Android 截图返回格式不正确")
        return data

    def tap(self, x: int, y: int) -> None:
        self._validate_coordinate(x, y)
        self._run_text(
            ["-s", self.serial, "shell", "input", "tap", str(x), str(y)]
        )

    def swipe(
        self,
        *,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int,
    ) -> None:
        self._validate_coordinate(start_x, start_y)
        self._validate_coordinate(end_x, end_y)
        if not 100 <= duration_ms <= 3000:
            raise ValueError("滑动时长必须在 100-3000 毫秒之间")
        self._run_text(
            [
                "-s",
                self.serial,
                "shell",
                "input",
                "swipe",
                str(start_x),
                str(start_y),
                str(end_x),
                str(end_y),
                str(duration_ms),
            ]
        )

    def input_text(self, value: str) -> None:
        if not self._safe_text_pattern.fullmatch(value):
            raise ValueError("仅支持 1-256 位安全英文、数字和常用符号")
        encoded = value.replace(" ", "%s")
        self._run_text(
            ["-s", self.serial, "shell", "input", "text", encoded]
        )

    def keyevent(self, key: str) -> None:
        keycode = self._keyevents.get(key)
        if keycode is None:
            raise ValueError("不支持的 Android 按键")
        self._run_text(
            ["-s", self.serial, "shell", "input", "keyevent", keycode]
        )

    def _ensure_available(self) -> None:
        if shutil.which(self.adb_binary) is None:
            raise AndroidDeviceControlError("服务器未安装 ADB")

    def _run_text(self, args: list[str]) -> str:
        completed = self._run(args, text=True)
        return completed.stdout.strip()

    def _run_bytes(self, args: list[str]) -> bytes:
        completed = self._run(args, text=False)
        return completed.stdout

    def _run(
        self,
        args: list[str],
        *,
        text: bool,
    ) -> subprocess.CompletedProcess:
        try:
            completed = subprocess.run(
                [self.adb_binary, *args],
                capture_output=True,
                text=text,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AndroidDeviceControlError("Android 控制命令执行超时") from exc
        except OSError as exc:
            raise AndroidDeviceControlError("Android 控制命令启动失败") from exc
        if completed.returncode != 0:
            raw_error = completed.stderr or completed.stdout or b""
            if isinstance(raw_error, bytes):
                detail = raw_error.decode("utf-8", errors="ignore")
            else:
                detail = raw_error
            safe_detail = " ".join(detail.strip().split())[:200]
            message = "Android 控制命令失败"
            if safe_detail:
                message = f"{message}：{safe_detail}"
            raise AndroidDeviceControlError(message)
        return completed

    @staticmethod
    def _validate_coordinate(x: int, y: int) -> None:
        if not 0 <= x <= 8192 or not 0 <= y <= 8192:
            raise ValueError("Android 坐标超出允许范围")
