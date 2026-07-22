import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
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
    _wecom_package = "com.tencent.wework"
    _wecom_launcher = "com.tencent.wework/.launch.LaunchSplashActivity"

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

    def sender_login_status(self) -> dict[str, Any]:
        self._ensure_available()
        component = self._foreground_component()
        if component is None or component[0] != self._wecom_package:
            stage = "not_open"
        else:
            activity = component[1].lower()
            if "loginveryfystep1activity" in activity:
                stage = "phone"
            elif any(
                marker in activity
                for marker in ("loginveryfystep2activity", "verifycode", "sms")
            ):
                stage = "verification_code"
            elif "jswebactivity" in activity:
                stage = "qr_code"
            elif any(marker in activity for marker in ("realname", "cardidcheck")):
                stage = "identity_verification"
            elif any(marker in activity for marker in ("facecheck", "faceverify")):
                stage = "face_verification"
            elif "login" in activity:
                stage = "login_pending"
            elif any(
                marker in activity
                for marker in ("wwmainactivity", "launcherui", "mainactivity")
            ):
                stage = "logged_in"
            else:
                stage = "login_pending"
        return {"stage": stage, "online": True}

    def open_sender_login(self) -> None:
        self._ensure_available()
        self._run_text(
            [
                "-s",
                self.serial,
                "shell",
                "am",
                "start",
                "-n",
                self._wecom_launcher,
            ]
        )

    def submit_sender_phone(self, phone: str) -> None:
        if not re.fullmatch(r"1\d{10}", phone):
            raise ValueError("请输入正确的 11 位手机号")
        self._require_login_stage("phone")
        self.tap(985, 466)
        self.tap(480, 466)
        self.input_text(phone)
        self.tap(540, 680)

    def submit_sender_verification_code(self, code: str) -> None:
        if not re.fullmatch(r"\d{4,8}", code):
            raise ValueError("请输入 4-8 位数字验证码")
        self._require_login_stage("verification_code")
        self.tap(540, 470)
        self.input_text(code)
        self.tap(540, 680)

    def submit_sender_identity_number(self, identity_number: str) -> None:
        normalized = identity_number.strip().upper()
        if not re.fullmatch(r"(?:\d{15}|\d{17}[0-9X])", normalized):
            raise ValueError("请输入正确的身份证号码")
        self._require_login_stage("identity_verification")
        self.tap(620, 995)
        self._replace_identity_number(normalized)
        self.keyevent("back")
        time.sleep(0.5)
        self.tap(540, 1150)
        self._wait_for_login_stage_change("identity_verification")

    def refresh_sender_qr_code(self) -> None:
        self._require_login_stage("qr_code")
        self.tap(540, 850)

    def _ensure_available(self) -> None:
        if shutil.which(self.adb_binary) is None:
            raise AndroidDeviceControlError("服务器未安装 ADB")

    def _foreground_component(self) -> tuple[str, str] | None:
        output = self._run_text(
            ["-s", self.serial, "shell", "dumpsys", "window"]
        )
        match = re.search(
            r"mFocusedApp=.*?\s([A-Za-z0-9._]+)/([A-Za-z0-9._$]+)(?:\s|})",
            output,
        )
        if match is None:
            match = re.search(
                r"mCurrentFocus=.*?\s([A-Za-z0-9._]+)/([A-Za-z0-9._$]+)(?:\s|})",
                output,
            )
        if match is None:
            return None
        return match.group(1), match.group(2)

    def _require_login_stage(self, expected: str) -> None:
        actual = self.sender_login_status()["stage"]
        if actual != expected:
            raise AndroidDeviceControlError("企业微信登录步骤已变化，请刷新页面")

    def _clear_focused_text(self) -> None:
        # This Android build drops all but the first key in a multi-keyevent call.
        self._run_text(
            [
                "-s",
                self.serial,
                "shell",
                "sh",
                "-c",
                "i=0; input keyevent KEYCODE_MOVE_END; "
                "while [ \"$i\" -lt 100 ]; do "
                "input keyevent KEYCODE_DEL; i=$((i + 1)); done",
            ]
        )

    def _replace_identity_number(self, identity_number: str) -> None:
        for _ in range(3):
            self._clear_focused_text()
            self.input_text(identity_number)
            time.sleep(0.3)
            if self._identity_field_value() == identity_number:
                return
        raise AndroidDeviceControlError(
            "身份证号码未能正确写入企业微信，请重试"
        )

    def _identity_field_value(self) -> str:
        dump_path = "/sdcard/legal_wecom_identity_check.xml"
        self._run_text(
            [
                "-s",
                self.serial,
                "shell",
                "uiautomator",
                "dump",
                dump_path,
            ]
        )
        try:
            xml_text = self._run_text(
                ["-s", self.serial, "shell", "cat", dump_path]
            )
            root = ET.fromstring(xml_text)
            for node in root.iter("node"):
                if node.attrib.get("resource-id") == "com.tencent.wework:id/c3_":
                    return node.attrib.get("text", "")
        except ET.ParseError as exc:
            raise AndroidDeviceControlError(
                "无法确认企业微信身份证输入结果"
            ) from exc
        finally:
            self._run_text(
                ["-s", self.serial, "shell", "rm", "-f", dump_path]
            )
        raise AndroidDeviceControlError("未找到企业微信身份证输入框")

    def _wait_for_login_stage_change(self, previous_stage: str) -> None:
        for _ in range(5):
            time.sleep(0.5)
            if self.sender_login_status()["stage"] != previous_stage:
                return
        raise AndroidDeviceControlError(
            "企业微信未进入下一步，请检查身份证号后重试"
        )

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
