import argparse
import json
import sys

from app.core.config import get_settings
from app.core.config_validator import validate_runtime_config


def check_config() -> int:
    result = validate_runtime_config(get_settings())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["errors"]:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-config", help="校验运行时配置")

    args = parser.parse_args()
    if args.command == "check-config":
        return check_config()
    parser.error(f"未知命令：{args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
