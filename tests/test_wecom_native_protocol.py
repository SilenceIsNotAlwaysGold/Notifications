import pytest

from wecom_native_lab.protocol import (
    IlinkQrStatus,
    ProtocolDecodeError,
    WecomPadQrStatus,
    decode_check_login_qr_code_response,
    decode_get_login_qr_code_response,
    decode_wecom_pad_qr_check,
    encode_get_login_qr_code_request,
)
from wecom_protocol_gateway.native_lab import _state_for


def test_encodes_verified_ilink_get_qr_code_request_fields():
    assert encode_get_login_qr_code_request(
        verify_scene=3, confirmation=b"test-confirmation"
    ) == b"\x08\x03\x12\x11test-confirmation"


def test_decodes_verified_ilink_qr_code_path():
    assert decode_get_login_qr_code_response(
        b"\x0a\x19/ilink/test/login-qr-code"
    ) == "/ilink/test/login-qr-code"


def test_decodes_verified_ilink_qr_check_fields_and_stage():
    payload = (
        b"\x08\x01"
        b"\x10\xb9\x60"
        b"\x1a\x0ctest-account"
        b"\x22\x16https://example.test/a"
        b"\x2a\x03biz"
    )

    result = decode_check_login_qr_code_response(payload)

    assert result.status is IlinkQrStatus.SCANNED
    assert result.stage == "qr_scanned"
    assert result.uin == 12345
    assert result.nickname == "test-account"
    assert result.avatar_url == "https://example.test/a"
    assert result.business_confirmation == b"biz"


@pytest.mark.parametrize(
    "payload",
    [b"", b"\x08", b"\x0a\x05abc", b"\x08\x09", b"\x0a\x01x"],
)
def test_rejects_malformed_or_semantically_invalid_qr_check(payload):
    with pytest.raises(ProtocolDecodeError):
        decode_check_login_qr_code_response(payload)


def test_rejects_qr_path_with_invalid_utf8():
    with pytest.raises(ProtocolDecodeError):
        decode_get_login_qr_code_response(b"\x0a\x01\xff")


def test_confirmed_qr_does_not_claim_account_is_online():
    assert _state_for(
        "/login/checkLoginQrcode", {"status": 2}, {"online": False}
    ) == ("qr_login_succeeded", False)


def test_pad_verification_status_is_not_treated_as_login_success():
    assert _state_for(
        "/login/checkLoginQrcode", {"status": 10}, {"online": False}
    ) == ("verification_required", False)


def test_decodes_verified_wecom_pad_qr_check_without_exposing_session_material():
    payload = (
        b"\x08\x02"
        b"\x10\xb9\x60"
        b"\x1a\x0ctest-account"
        b"\x22\x16https://example.test/a"
        b"\x30\x01"
        b"\x40\x8f\x4e"
        b"\x4a\x03tgt"
        b"\x5a\x04corp"
    )

    result = decode_wecom_pad_qr_check(payload)

    assert result.status is WecomPadQrStatus.SUCCEEDED
    assert result.stage == "qr_login_succeeded"
    assert result.vid == 12345
    assert result.nickname == "test-account"
    assert result.icon_url == "https://example.test/a"
    assert result.is_bind_wechat is True
    assert result.gid == 9999
    assert result.corp_info_present is True
    assert result.session_material_present is True
    assert not hasattr(result, "tgt")


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\x08\x09",
        b"\x0a\x01x",
        b"\x08\x01\x32\x01x",
        b"\x08\x01\x30\x02",
        b"\x08\x01\x1a\x01\xff",
    ],
)
def test_rejects_invalid_wecom_pad_qr_check(payload):
    with pytest.raises(ProtocolDecodeError):
        decode_wecom_pad_qr_check(payload)
