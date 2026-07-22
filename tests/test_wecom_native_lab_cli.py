import json
import subprocess
import sys


def test_native_lab_scaffold_reports_next_capability():
    completed = subprocess.run(
        [sys.executable, "-m", "wecom_native_lab.cli", "probe"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["data"] == {
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
    }


def test_native_lab_scaffold_does_not_fake_protocol_success():
    completed = subprocess.run(
        [sys.executable, "-m", "wecom_native_lab.cli", "invoke"],
        input=json.dumps({"method": "/login/createDevice", "params": {}}),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["code"] == 5010
    assert payload["data"]["protocol_ready"] is False
