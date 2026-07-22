import json
import sys
from typing import Any


def main(argv: list[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv[1:])
    if len(arguments) != 1 or arguments[0] not in {"invoke", "probe"}:
        _write({"code": 4001, "msg": "只支持 invoke 或 probe"})
        return 2
    action = arguments[0]
    if action == "probe":
        _write(
            {
                "code": 0,
                "msg": "成功",
                "data": {
                    "transport": "native_lab_scaffold",
                    "protocol_ready": False,
                    "implemented_capabilities": [],
                    "verified_protocol_facts": [
                        "wecom_pad_qr_state_machine",
                        "wecom_pad_check_qrcode_schema",
                        "wecom_pad_jni_boundary",
                        "wecom_pad_request_schemas",
                        "wecom_gaphub_transport_hosts",
                    ],
                    "next_capability": "wecom_gaphub_connection_probe",
                },
            }
        )
        return 0
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        _write({"code": 4002, "msg": "实验请求不是合法 JSON"})
        return 2
    method = request.get("method") if isinstance(request, dict) else None
    _write(
        {
            "code": 5010,
            "msg": "自研协议传输尚未实现",
            "data": {
                "method": method,
                "protocol_ready": False,
                "next_capability": "wecom_gaphub_connection_probe",
            },
        }
    )
    return 0


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    raise SystemExit(main())
