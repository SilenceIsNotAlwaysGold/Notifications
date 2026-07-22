import pytest

from app.adapters.wecom_protocol_account import (
    WeComProtocolAccount,
    WeComProtocolAccountError,
)
from app.core.config import get_settings


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def account(**overrides):
    values = {
        "base_url": "https://gateway.example.test",
        "api_path": "/api/qw/doApi",
        "token": "secret-token",
        "guid": "sender-guid",
        "timeout_seconds": 8,
    }
    values.update(overrides)
    return WeComProtocolAccount(**values)


def test_missing_protocol_config_is_reported_without_request(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.wecom_protocol_account.httpx.post",
        lambda *args, **kwargs: pytest.fail("must not request gateway"),
    )

    result = account(token=None, guid=None).status()

    assert result == {
        "backend": "protocol",
        "stage": "not_configured",
        "online": False,
        "missing": ["WECOM_PROTOCOL_ACCOUNT_TOKEN", "WECOM_PROTOCOL_ACCOUNT_GUID"],
    }


def test_start_login_returns_gateway_qr_code(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return FakeResponse(
            {"code": 0, "data": {"qrCodeUrl": "https://qr.example.test/login.png"}}
        )

    monkeypatch.setattr("app.adapters.wecom_protocol_account.httpx.post", fake_post)

    result = account().start_login()

    assert result["stage"] == "qr_code"
    assert result["qr_code"] == "https://qr.example.test/login.png"
    assert captured["headers"]["WECOM-TOKEN"] == "secret-token"
    assert captured["json"] == {
        "method": "/login/getLoginQrcode",
        "params": {"guid": "sender-guid"},
    }


@pytest.mark.parametrize(
    ("payload", "expected_stage"),
    [
        ({"online": True}, "logged_in"),
        ({"needVerify": True}, "verification_code"),
        ({"status": 10}, "verification_code"),
        ({"status": 2}, "login_pending"),
        ({"status": 0}, "qr_code"),
    ],
)
def test_poll_login_normalizes_gateway_states(monkeypatch, payload, expected_stage):
    monkeypatch.setattr(
        "app.adapters.wecom_protocol_account.httpx.post",
        lambda *args, **kwargs: FakeResponse({"code": 0, "data": payload}),
    )

    assert account().poll_login()["stage"] == expected_stage


def test_pad_qr_success_without_online_receipt_is_not_reported_as_logged_in(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.adapters.wecom_protocol_account.httpx.post",
        lambda *args, **kwargs: FakeResponse(
            {"code": 0, "data": {"status": 2, "online": False}}
        ),
    )

    result = account().poll_login()

    assert result["stage"] == "login_pending"
    assert result["online"] is False


def test_gateway_business_error_is_not_reported_as_login_state(monkeypatch):
    monkeypatch.setattr(
        "app.adapters.wecom_protocol_account.httpx.post",
        lambda *args, **kwargs: FakeResponse({"code": 401, "msg": "token invalid"}),
    )

    with pytest.raises(WeComProtocolAccountError, match="token invalid"):
        account().status()


def test_sender_account_api_reports_missing_configuration(client, monkeypatch):
    monkeypatch.setenv("WECOM_ACCOUNT_LOGIN_MODE", "protocol")
    monkeypatch.setenv("WECOM_PROTOCOL_ACCOUNT_BASE_URL", "https://gateway.example.test")
    monkeypatch.delenv("WECOM_PROTOCOL_ACCOUNT_TOKEN", raising=False)
    monkeypatch.delenv("WECOM_PROTOCOL_ACCOUNT_GUID", raising=False)
    get_settings.cache_clear()

    response = client.get("/api/v1/legal/sender-account/status")

    assert response.status_code == 200
    assert response.json()["data"]["stage"] == "not_configured"
    assert response.json()["data"]["missing"] == [
        "WECOM_PROTOCOL_ACCOUNT_TOKEN",
        "WECOM_PROTOCOL_ACCOUNT_GUID",
    ]
    get_settings.cache_clear()
