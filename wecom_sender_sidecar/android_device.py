import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any


class AndroidDeviceError(RuntimeError):
    pass


class AndroidDeviceManager:
    _serial_pattern = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
    _package_pattern = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{1,254}$")
    _component_pattern = re.compile(
        r"^[A-Za-z][A-Za-z0-9_.]{1,254}/[A-Za-z0-9_.$]{1,254}$"
    )

    def __init__(
        self,
        *,
        serial: str,
        adb_binary: str = "adb",
        timeout_seconds: float = 30,
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
        self.timeout_seconds = timeout_seconds

    def preflight(
        self,
        *,
        wecom_package: str = "com.tencent.wework",
        companion_package: str = "org.yameida.worktool",
        accessibility_component: str = (
            "org.yameida.worktool/org.yameida.worktool.service.WeworkService"
        ),
        reverse_port: int = 8092,
    ) -> dict[str, Any]:
        self._validate_package(wecom_package)
        self._validate_package(companion_package)
        self._validate_component(accessibility_component)
        self._validate_port(reverse_port)
        self.ensure_available()
        self.connect()

        state = self._run_device(["get-state"])
        boot_completed = self._shell(["getprop", "sys.boot_completed"]) == "1"
        sdk_text = self._shell(["getprop", "ro.build.version.sdk"])
        abi_text = self._shell(["getprop", "ro.product.cpu.abilist"])
        sdk = int(sdk_text) if sdk_text.isdigit() else None
        device_abis = [item for item in abi_text.split(",") if item]
        enabled_services = self._enabled_accessibility_services()
        reverse_rules = self._run_device(["reverse", "--list"])

        checks = {
            "device_online": state == "device",
            "boot_completed": boot_completed,
            "android_sdk_supported": sdk is not None and sdk >= 24,
            "wecom_installed": self.package_installed(wecom_package),
            "companion_installed": self.package_installed(companion_package),
            "accessibility_enabled": accessibility_component in enabled_services,
            "reverse_port_configured": f"tcp:{reverse_port}" in reverse_rules,
        }
        return {
            "automation_ready": all(checks.values()),
            "checks": checks,
            "device": {
                "serial": self.serial,
                "state": state,
                "sdk": sdk,
                "abis": device_abis,
            },
            "manual_checks": [
                "企业微信通知账号已登录",
                "WorkTool Host 为 http://127.0.0.1:8092 且链接号与 robot_id 一致",
                "测试外部群已人工核对群名与发送目标",
            ],
        }

    def install_apk(self, apk_path: Path) -> dict[str, Any]:
        resolved = apk_path.expanduser().resolve()
        if not resolved.is_file() or resolved.suffix.lower() != ".apk":
            raise AndroidDeviceError(f"APK 文件不存在：{resolved}")
        device_abis = self.device_abis()
        apk_abis = inspect_apk_abis(resolved)
        compatible = not apk_abis or bool(set(device_abis).intersection(apk_abis))
        if not compatible:
            raise AndroidDeviceError(
                "APK ABI 与 Android 容器不兼容："
                f"apk={','.join(apk_abis)} device={','.join(device_abis)}"
            )
        self._run_device(["install", "-r", "--no-streaming", str(resolved)])
        return {
            "path": str(resolved),
            "apk_abis": apk_abis or ["universal"],
            "device_abis": device_abis,
            "installed": True,
        }

    def configure_runtime(
        self,
        *,
        accessibility_component: str,
        companion_package: str,
        host_port: int = 8092,
        device_port: int = 8092,
    ) -> dict[str, Any]:
        self._validate_component(accessibility_component)
        self._validate_package(companion_package)
        self._validate_port(host_port)
        self._validate_port(device_port)
        self.ensure_available()
        self.connect()

        enabled_services = self._enabled_accessibility_services()
        enabled_services.add(accessibility_component)
        merged_services = ":".join(sorted(enabled_services))
        self._shell(
            [
                "settings",
                "put",
                "secure",
                "enabled_accessibility_services",
                merged_services,
            ]
        )
        self._shell(["settings", "put", "secure", "accessibility_enabled", "1"])
        self._run_device(
            ["reverse", f"tcp:{device_port}", f"tcp:{host_port}"]
        )
        self._shell(["svc", "power", "stayon", "true"])
        self._shell(
            ["dumpsys", "deviceidle", "whitelist", f"+{companion_package}"]
        )
        self._shell(
            [
                "monkey",
                "-p",
                companion_package,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ]
        )
        return {
            "accessibility_component": accessibility_component,
            "reverse": f"tcp:{device_port}->tcp:{host_port}",
            "companion_launched": True,
        }

    def package_installed(self, package: str) -> bool:
        self._validate_package(package)
        try:
            result = self._shell(["pm", "path", package])
        except AndroidDeviceError:
            return False
        return result.startswith("package:")

    def device_abis(self) -> list[str]:
        value = self._shell(["getprop", "ro.product.cpu.abilist"])
        return [item.strip() for item in value.split(",") if item.strip()]

    def connect(self) -> None:
        if ":" not in self.serial:
            return
        result = self._run(["connect", self.serial])
        lowered = result.lower()
        if "connected" not in lowered and "already" not in lowered:
            raise AndroidDeviceError("ADB 无法连接 Android 容器")

    def ensure_available(self) -> None:
        if shutil.which(self.adb_binary) is None:
            raise AndroidDeviceError(f"未找到 ADB 可执行文件：{self.adb_binary}")

    def _enabled_accessibility_services(self) -> set[str]:
        value = self._shell(
            ["settings", "get", "secure", "enabled_accessibility_services"]
        )
        if not value or value == "null":
            return set()
        return {item for item in value.split(":") if item}

    def _shell(self, args: list[str]) -> str:
        return self._run_device(["shell", *args])

    def _run_device(self, args: list[str]) -> str:
        return self._run(["-s", self.serial, *args])

    def _run(self, args: list[str]) -> str:
        try:
            completed = subprocess.run(
                [self.adb_binary, *args],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise AndroidDeviceError("未找到 ADB 可执行文件") from exc
        except subprocess.TimeoutExpired as exc:
            raise AndroidDeviceError(
                f"ADB 命令执行超过 {self.timeout_seconds:g} 秒"
            ) from exc
        except OSError as exc:
            raise AndroidDeviceError("ADB 命令启动失败") from exc
        if completed.returncode != 0:
            detail = _safe_error(completed.stderr or completed.stdout)
            raise AndroidDeviceError(
                f"ADB 命令失败（退出码 {completed.returncode}）"
                + (f"：{detail}" if detail else "")
            )
        return completed.stdout.strip()

    @classmethod
    def _validate_package(cls, value: str) -> None:
        if not cls._package_pattern.fullmatch(value):
            raise ValueError("Android package 格式不正确")

    @classmethod
    def _validate_component(cls, value: str) -> None:
        if not cls._component_pattern.fullmatch(value):
            raise ValueError("Android accessibility component 格式不正确")

    @staticmethod
    def _validate_port(value: int) -> None:
        if not 1 <= value <= 65535:
            raise ValueError("Android 端口必须在 1-65535 之间")


def inspect_apk_abis(apk_path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(apk_path) as archive:
            abis = {
                parts[1]
                for name in archive.namelist()
                if name.startswith("lib/")
                and len((parts := name.split("/"))) >= 3
                and parts[1]
            }
    except (OSError, zipfile.BadZipFile) as exc:
        raise AndroidDeviceError(f"APK 文件无法解析：{apk_path}") from exc
    return sorted(abis)


def _safe_error(value: str) -> str:
    return " ".join(value.strip().split())[:240]
