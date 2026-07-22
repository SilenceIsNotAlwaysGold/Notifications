import json
import os
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
        "diagnostic_capabilities": [
            "wecom_gaphub_dns_preflight",
            "wecom_gaphub_zero_byte_tcp_preflight",
        ],
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


def test_connection_probe_never_claims_protocol_readiness():
    completed = subprocess.run(
        [sys.executable, "-m", "wecom_native_lab.cli", "connection-probe"],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "WECOM_NATIVE_LAB_GAPHUB_ENDPOINTS_JSON": "[]",
        },
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["data"]["probe_scope"] == "dns_only"
    assert payload["data"]["payload_bytes_sent"] == 0
    assert payload["data"]["server_correlated"] is False
    assert payload["data"]["protocol_ready"] is False


def test_connection_probe_rejects_unverified_hosts():
    completed = subprocess.run(
        [sys.executable, "-m", "wecom_native_lab.cli", "connection-probe"],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "WECOM_NATIVE_LAB_GAPHUB_ENDPOINTS_JSON": (
                '[{"host":"example.com","port":443}]'
            ),
        },
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["code"] == 4003
