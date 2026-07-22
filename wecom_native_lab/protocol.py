from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ProtocolDecodeError(ValueError):
    pass


class IlinkQrStatus(IntEnum):
    NO_SCAN = 0
    SCANNED = 1
    CONFIRMED = 2
    CANCELED = 3
    EXPIRED = 4


class WecomPadQrStatus(IntEnum):
    NEVER = 0
    IN_PROGRESS = 1
    SUCCEEDED = 2
    FAILED = 3
    REFUSED = 4
    IN_PROGRESS_WECHAT = 5
    SUCCEEDED_WECHAT = 6
    FAILED_WECHAT = 7
    REFUSED_WECHAT = 8
    NEEDS_VERIFICATION = 10


@dataclass(frozen=True)
class WecomPadQrCheck:
    status: WecomPadQrStatus
    vid: int | None = None
    nickname: str | None = None
    icon_url: str | None = None
    is_bind_wechat: bool | None = None
    gid: int | None = None
    corp_info_present: bool = False
    session_material_present: bool = False

    @property
    def stage(self) -> str:
        return {
            WecomPadQrStatus.NEVER: "qr_pending",
            WecomPadQrStatus.IN_PROGRESS: "qr_scanned",
            WecomPadQrStatus.SUCCEEDED: "qr_login_succeeded",
            WecomPadQrStatus.FAILED: "qr_failed",
            WecomPadQrStatus.REFUSED: "qr_refused",
            WecomPadQrStatus.IN_PROGRESS_WECHAT: "qr_scanned_wechat",
            WecomPadQrStatus.SUCCEEDED_WECHAT: "qr_login_succeeded_wechat",
            WecomPadQrStatus.FAILED_WECHAT: "qr_failed_wechat",
            WecomPadQrStatus.REFUSED_WECHAT: "qr_refused_wechat",
            WecomPadQrStatus.NEEDS_VERIFICATION: "verification_required",
        }[self.status]


@dataclass(frozen=True)
class IlinkQrCheck:
    status: IlinkQrStatus
    uin: int | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    business_confirmation: bytes | None = None

    @property
    def stage(self) -> str:
        return {
            IlinkQrStatus.NO_SCAN: "qr_pending",
            IlinkQrStatus.SCANNED: "qr_scanned",
            IlinkQrStatus.CONFIRMED: "qr_confirmed",
            IlinkQrStatus.CANCELED: "qr_canceled",
            IlinkQrStatus.EXPIRED: "qr_expired",
        }[self.status]


def encode_get_login_qr_code_request(
    *, verify_scene: int | None = None, confirmation: bytes | None = None
) -> bytes:
    payload = bytearray()
    if verify_scene is not None:
        if verify_scene < 0:
            raise ValueError("verify_scene must be non-negative")
        payload.extend(_field_varint(1, verify_scene))
    if confirmation is not None:
        payload.extend(_field_bytes(2, confirmation))
    return bytes(payload)


def decode_get_login_qr_code_response(payload: bytes) -> str:
    fields = _decode_fields(payload)
    values = fields.get(1, [])
    if not values:
        raise ProtocolDecodeError("QR code response does not contain path")
    return _decode_text(_expect_bytes(values[-1], 1), 1)


def decode_check_login_qr_code_response(payload: bytes) -> IlinkQrCheck:
    fields = _decode_fields(payload)
    status_number = _expect_int(_last_required(fields, 1), 1)
    try:
        status = IlinkQrStatus(status_number)
    except ValueError as exc:
        raise ProtocolDecodeError(f"unknown QR status: {status_number}") from exc
    return IlinkQrCheck(
        status=status,
        uin=_optional_int(fields, 2),
        nickname=_optional_text(fields, 3),
        avatar_url=_optional_text(fields, 4),
        business_confirmation=_optional_bytes(fields, 5),
    )


def decode_wecom_pad_qr_check(payload: bytes) -> WecomPadQrCheck:
    """Decode the verified, non-secret subset of WwQrcodeLogin.CheckQrcodeData."""
    fields = _decode_fields(payload)
    status_number = _expect_int(_last_required(fields, 1), 1)
    try:
        status = WecomPadQrStatus(status_number)
    except ValueError as exc:
        raise ProtocolDecodeError(f"unknown WeCom Pad QR status: {status_number}") from exc

    _validate_optional_types(fields, (2, 6, 8), int)
    _validate_optional_types(fields, (3, 4, 5, 7, 9, 10, 11, 12, 13), bytes)
    bind_value = _optional_int(fields, 6)
    if bind_value not in (None, 0, 1):
        raise ProtocolDecodeError("protobuf field 6 is not a valid bool")

    return WecomPadQrCheck(
        status=status,
        vid=_optional_int(fields, 2),
        nickname=_optional_text(fields, 3),
        icon_url=_optional_text(fields, 4),
        is_bind_wechat=None if bind_value is None else bool(bind_value),
        gid=_optional_int(fields, 8),
        corp_info_present=bool(fields.get(11)),
        session_material_present=any(
            fields.get(number) for number in (9, 10, 12, 13)
        ),
    )


def encode_wecom_pad_verification_request(verification_value: str) -> bytes:
    if any(
        ord(character) < 32 or ord(character) == 127
        for character in verification_value
    ):
        raise ValueError("verification_value contains control characters")
    normalized = verification_value.strip()
    if not normalized:
        raise ValueError("verification_value must not be empty")
    if len(normalized) > 64:
        raise ValueError("verification_value exceeds 64 character limit")
    return _field_bytes(3, normalized.encode("utf-8"))


def encode_wecom_pad_gap_push_check_request() -> bytes:
    return b""


def _decode_fields(payload: bytes) -> dict[int, list[int | bytes]]:
    if len(payload) > 1024 * 1024:
        raise ProtocolDecodeError("protobuf payload exceeds 1 MiB limit")
    fields: dict[int, list[int | bytes]] = {}
    offset = 0
    while offset < len(payload):
        key, offset = _read_varint(payload, offset)
        field_number = key >> 3
        wire_type = key & 7
        if field_number <= 0:
            raise ProtocolDecodeError("invalid protobuf field number")
        if wire_type == 0:
            value, offset = _read_varint(payload, offset)
        elif wire_type == 1:
            offset = _require_available(payload, offset, 8)
            value = payload[offset - 8 : offset]
        elif wire_type == 2:
            length, offset = _read_varint(payload, offset)
            offset = _require_available(payload, offset, length)
            value = payload[offset - length : offset]
        elif wire_type == 5:
            offset = _require_available(payload, offset, 4)
            value = payload[offset - 4 : offset]
        else:
            raise ProtocolDecodeError(f"unsupported protobuf wire type: {wire_type}")
        fields.setdefault(field_number, []).append(value)
    return fields


def _read_varint(payload: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(payload):
            raise ProtocolDecodeError("truncated protobuf varint")
        current = payload[offset]
        offset += 1
        value |= (current & 0x7F) << shift
        if not current & 0x80:
            return value, offset
    raise ProtocolDecodeError("protobuf varint is too long")


def _require_available(payload: bytes, offset: int, length: int) -> int:
    if length < 0 or length > len(payload) - offset:
        raise ProtocolDecodeError("truncated protobuf field")
    return offset + length


def _varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("protobuf varint must be non-negative")
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _field_varint(field_number: int, value: int) -> bytes:
    return _varint(field_number << 3) + _varint(value)


def _field_bytes(field_number: int, value: bytes) -> bytes:
    return _varint((field_number << 3) | 2) + _varint(len(value)) + value


def _last_required(
    fields: dict[int, list[int | bytes]], field_number: int
) -> int | bytes:
    values = fields.get(field_number, [])
    if not values:
        raise ProtocolDecodeError(f"missing protobuf field {field_number}")
    return values[-1]


def _expect_int(value: int | bytes, field_number: int) -> int:
    if not isinstance(value, int):
        raise ProtocolDecodeError(f"protobuf field {field_number} has wrong wire type")
    return value


def _expect_bytes(value: int | bytes, field_number: int) -> bytes:
    if not isinstance(value, bytes):
        raise ProtocolDecodeError(f"protobuf field {field_number} has wrong wire type")
    return value


def _decode_text(value: bytes, field_number: int) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolDecodeError(
            f"protobuf field {field_number} is not valid UTF-8"
        ) from exc


def _optional_int(fields: dict[int, list[int | bytes]], field_number: int) -> int | None:
    values = fields.get(field_number, [])
    return _expect_int(values[-1], field_number) if values else None


def _optional_bytes(
    fields: dict[int, list[int | bytes]], field_number: int
) -> bytes | None:
    values = fields.get(field_number, [])
    return _expect_bytes(values[-1], field_number) if values else None


def _optional_text(
    fields: dict[int, list[int | bytes]], field_number: int
) -> str | None:
    value = _optional_bytes(fields, field_number)
    return _decode_text(value, field_number) if value is not None else None


def _validate_optional_types(
    fields: dict[int, list[int | bytes]],
    field_numbers: tuple[int, ...],
    expected_type: type[int] | type[bytes],
) -> None:
    for field_number in field_numbers:
        for value in fields.get(field_number, []):
            if not isinstance(value, expected_type):
                raise ProtocolDecodeError(
                    f"protobuf field {field_number} has wrong wire type"
                )
