from fastapi.testclient import TestClient

from wecom_archive_sidecar.main import app


PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
test-private-key
-----END PRIVATE KEY-----
"""


def test_sidecar_health_defaults_to_not_configured(monkeypatch):
    monkeypatch.delenv("WECOM_ARCHIVE_SIDECAR_BACKEND", raising=False)

    response = TestClient(app).get("/wecom-archive/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "backend": "not_configured"}


def test_sidecar_mock_messages_returns_contract_shape(monkeypatch):
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_BACKEND", "mock")
    monkeypatch.delenv("WECOM_ARCHIVE_SIDECAR_MOCK_SCENARIO", raising=False)

    response = TestClient(app).post(
        "/wecom-archive/messages",
        json={
            "seq": 0,
            "limit": 20,
            "corp_id": "wwxxxx",
            "archive_secret": "secret",
            "private_key": PRIVATE_KEY,
            "public_key_ver": "1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"messages": []}


def test_sidecar_mock_legal_demo_messages_allow_empty_credentials(monkeypatch):
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_BACKEND", "mock")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_MOCK_SCENARIO", "legal_demo")

    response = TestClient(app).post(
        "/wecom-archive/messages",
        json={
            "seq": 3001,
            "limit": 20,
        },
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [message["msgid"] for message in messages] == [
        "sidecar_demo_court",
        "sidecar_demo_payment_notice",
        "sidecar_demo_payment_done",
    ]
    assert messages[0]["file"]["filename"] == "开庭传票.pdf"


def test_sidecar_mock_media_returns_base64(monkeypatch):
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_BACKEND", "mock")

    response = TestClient(app).post(
        "/wecom-archive/media/download",
        json={
            "raw_message": {"msgid": "msg_001", "msgtype": "image"},
            "target_filename": "msg_001.jpg",
            "corp_id": "wwxxxx",
            "archive_secret": "secret",
            "private_key": PRIVATE_KEY,
            "public_key_ver": "1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"content_base64": "bW9jayB3ZWNvbSBhcmNoaXZlIGltYWdlIGJ5dGVz"}


def test_sidecar_mock_allows_empty_private_key_source(monkeypatch):
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_BACKEND", "mock")

    response = TestClient(app).post(
        "/wecom-archive/messages",
        json={
            "seq": 0,
            "limit": 20,
            "corp_id": "wwxxxx",
            "archive_secret": "secret",
            "public_key_ver": "1",
        },
    )

    assert response.status_code == 200


def test_sidecar_not_configured_requires_private_key_source(monkeypatch):
    monkeypatch.delenv("WECOM_ARCHIVE_SIDECAR_BACKEND", raising=False)

    response = TestClient(app).post(
        "/wecom-archive/messages",
        json={
            "seq": 0,
            "limit": 20,
            "corp_id": "wwxxxx",
            "archive_secret": "secret",
            "public_key_ver": "1",
        },
    )

    assert response.status_code == 422
