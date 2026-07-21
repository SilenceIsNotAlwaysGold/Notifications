import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from wecom_sender_sidecar.android_device import (
    AndroidDeviceError,
    AndroidDeviceManager,
)


DEFAULT_ACCESSIBILITY_COMPONENT = (
    "cn.zhihe.legal.sender/"
    "cn.zhihe.legal.sender.automation.WeComAccessibilityService"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="企业微信 Linux Android 自有发送端设备管理"
    )
    parser.add_argument(
        "--serial",
        default=os.getenv("WECOM_ANDROID_SERIAL", "127.0.0.1:5555"),
    )
    parser.add_argument(
        "--adb-binary",
        default=os.getenv("WECOM_ANDROID_ADB_BINARY", "adb"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="检查设备与自动化就绪状态")
    _add_runtime_options(check)

    install = subparsers.add_parser("install", help="安装企业微信和自动化 APK")
    install.add_argument("--wecom-apk", type=Path, required=True)
    install.add_argument("--companion-apk", type=Path, required=True)

    configure = subparsers.add_parser(
        "configure", help="启用无障碍服务并配置 ADB 反向端口"
    )
    _add_runtime_options(configure)
    configure.add_argument("--host-port", type=int, default=8092)
    return parser


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--wecom-package",
        default="com.tencent.wework",
    )
    parser.add_argument(
        "--companion-package",
        default="cn.zhihe.legal.sender",
    )
    parser.add_argument(
        "--accessibility-component",
        default=DEFAULT_ACCESSIBILITY_COMPONENT,
    )
    parser.add_argument("--device-port", type=int, default=8092)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manager = AndroidDeviceManager(
            serial=args.serial,
            adb_binary=args.adb_binary,
        )
        if args.command == "check":
            result = manager.preflight(
                wecom_package=args.wecom_package,
                companion_package=args.companion_package,
                accessibility_component=args.accessibility_component,
                reverse_port=args.device_port,
            )
            exit_code = 0 if result["automation_ready"] else 2
        elif args.command == "install":
            manager.ensure_available()
            manager.connect()
            result = {
                "wecom": manager.install_apk(args.wecom_apk),
                "companion": manager.install_apk(args.companion_apk),
            }
            exit_code = 0
        else:
            result = manager.configure_runtime(
                accessibility_component=args.accessibility_component,
                companion_package=args.companion_package,
                host_port=args.host_port,
                device_port=args.device_port,
            )
            exit_code = 0
    except (AndroidDeviceError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps({"success": True, "result": result}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
