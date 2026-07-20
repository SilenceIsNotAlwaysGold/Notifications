import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from wecom_archive_sidecar.sdk_backend import WeComFinanceSdkBackend


class Request:
    def __init__(self, private_key_pem: str, **values):
        self._private_key_pem = private_key_pem
        self.corp_id = values.get("corp_id", "ww-test")
        self.archive_secret = values.get("archive_secret", "archive-secret")
        self.public_key_ver = values.get("public_key_ver", "1")
        self.seq = values.get("seq", 0)
        self.limit = values.get("limit", 100)
        self.raw_message = values.get("raw_message", {})

    def private_key_pem(self) -> str:
        return self._private_key_pem


class FakeClient:
    def __init__(self, chat_response: bytes = b"", decrypted_message: bytes = b"", media: bytes = b""):
        self.chat_response = chat_response
        self.decrypted_message = decrypted_message
        self.media = media
        self.random_key = None
        self.media_args = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None

    def get_chat_data(self, seq: int, limit: int, timeout_seconds: int) -> bytes:
        assert (seq, limit, timeout_seconds) == (0, 100, 10)
        return self.chat_response

    def decrypt_data(self, random_key: bytes, encrypted_message: str) -> bytes:
        self.random_key = random_key
        assert encrypted_message == "encrypted-message"
        return self.decrypted_message

    def download_media(self, sdk_file_id: str, timeout_seconds: int, max_bytes: int) -> bytes:
        self.media_args = (sdk_file_id, timeout_seconds, max_bytes)
        return self.media


@pytest.fixture
def rsa_material():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    random_key = b"0123456789abcdef"
    encrypted_random_key = private_key.public_key().encrypt(random_key, padding.PKCS1v15())
    return private_pem, random_key, base64.b64encode(encrypted_random_key).decode("ascii")


def test_fetch_messages_decrypts_and_preserves_envelope_fields(rsa_material, tmp_path):
    private_pem, random_key, encrypted_random_key = rsa_material
    chat_response = json.dumps(
        {
            "errcode": 0,
            "errmsg": "ok",
            "chatdata": [
                {
                    "seq": 9,
                    "publickey_ver": 1,
                    "encrypt_random_key": encrypted_random_key,
                    "encrypt_chat_msg": "encrypted-message",
                }
            ],
        }
    ).encode("utf-8")
    fake_client = FakeClient(
        chat_response=chat_response,
        decrypted_message=json.dumps({"msgid": "msg-9", "msgtype": "text"}).encode("utf-8"),
    )
    backend = WeComFinanceSdkBackend(client_factory=lambda *_: fake_client, library_path=tmp_path / "fake.so")

    messages = backend.fetch_messages(Request(private_pem))

    assert messages == [{"msgid": "msg-9", "msgtype": "text", "seq": 9, "publickey_ver": 1}]
    assert fake_client.random_key == random_key


def test_fetch_messages_rejects_unconfigured_key_version(rsa_material, tmp_path):
    private_pem, _, encrypted_random_key = rsa_material
    fake_client = FakeClient(
        chat_response=json.dumps(
            {
                "errcode": 0,
                "chatdata": [
                    {
                        "seq": 10,
                        "publickey_ver": 2,
                        "encrypt_random_key": encrypted_random_key,
                        "encrypt_chat_msg": "encrypted-message",
                    }
                ],
            }
        ).encode("utf-8")
    )
    backend = WeComFinanceSdkBackend(client_factory=lambda *_: fake_client, library_path=tmp_path / "fake.so")

    with pytest.raises(RuntimeError, match="消息使用版本 2"):
        backend.fetch_messages(Request(private_pem, public_key_ver="1"))


def test_fetch_messages_surfaces_sdk_json_error(rsa_material, tmp_path):
    private_pem, _, _ = rsa_material
    fake_client = FakeClient(chat_response=b'{"errcode":10009,"errmsg":"ip not allowed"}')
    backend = WeComFinanceSdkBackend(client_factory=lambda *_: fake_client, library_path=tmp_path / "fake.so")

    with pytest.raises(RuntimeError, match="10009"):
        backend.fetch_messages(Request(private_pem))


def test_download_media_uses_sdkfileid_and_validates_integrity(rsa_material, tmp_path):
    private_pem, _, _ = rsa_material
    content = b"pdf-content"
    fake_client = FakeClient(media=content)
    backend = WeComFinanceSdkBackend(client_factory=lambda *_: fake_client, library_path=tmp_path / "fake.so")
    request = Request(
        private_pem,
        raw_message={
            "msgtype": "file",
            "file": {
                "sdkfileid": "sdk-file-1",
                "filesize": len(content),
                "md5sum": hashlib.md5(content, usedforsecurity=False).hexdigest(),
            },
        },
    )

    result = backend.download_media(request)

    assert result == content
    assert fake_client.media_args == ("sdk-file-1", 10, 50 * 1024 * 1024)


def test_download_media_requires_sdkfileid(rsa_material, tmp_path):
    private_pem, _, _ = rsa_material
    backend = WeComFinanceSdkBackend(client_factory=lambda *_: FakeClient(), library_path=tmp_path / "fake.so")

    with pytest.raises(RuntimeError, match="sdkfileid"):
        backend.download_media(Request(private_pem, raw_message={"msgtype": "image", "image": {}}))


def test_download_media_rejects_md5_mismatch(rsa_material, tmp_path):
    private_pem, _, _ = rsa_material
    backend = WeComFinanceSdkBackend(
        client_factory=lambda *_: FakeClient(media=b"actual"),
        library_path=tmp_path / "fake.so",
    )
    request = Request(
        private_pem,
        raw_message={"msgtype": "image", "image": {"sdkfileid": "sdk-image", "md5sum": "0" * 32}},
    )

    with pytest.raises(RuntimeError, match="MD5"):
        backend.download_media(request)
