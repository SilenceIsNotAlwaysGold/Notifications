import base64
import binascii
import ctypes
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


SDK_ERROR_MESSAGES = {
    10000: "参数错误",
    10001: "网络错误",
    10002: "数据解析失败",
    10003: "系统失败",
    10004: "密钥回调处理失败",
    10005: "sdkfileid 不正确",
    10006: "媒体数据拉取失败",
    10007: "找不到消息公钥版本对应的私钥",
    10008: "解析 encrypt_key 失败",
    10009: "可信 IP 校验失败",
    10010: "数据已过期",
    10011: "证书错误",
}


class WeComFinanceSdkError(RuntimeError):
    def __init__(self, operation: str, code: int, detail: str | None = None) -> None:
        message = detail or SDK_ERROR_MESSAGES.get(code, "未知错误")
        super().__init__(f"企业微信 SDK {operation} 失败：code={code}, message={message}")
        self.operation = operation
        self.code = code


class NativeSdkClient:
    def __init__(self, library_path: Path, corp_id: str, archive_secret: str) -> None:
        self.library_path = library_path
        self._lib = self._load_library(library_path)
        self._configure_functions()
        self._sdk = self._lib.NewSdk()
        if not self._sdk:
            raise RuntimeError("企业微信 SDK NewSdk 返回空指针")
        init_code = self._lib.Init(self._sdk, corp_id.encode("utf-8"), archive_secret.encode("utf-8"))
        if init_code != 0:
            self.close()
            raise WeComFinanceSdkError("Init", init_code)

    @staticmethod
    def _load_library(path: Path) -> ctypes.CDLL:
        if not path.is_file():
            raise RuntimeError(f"企业微信 SDK 动态库不存在：{path}")
        try:
            return ctypes.CDLL(str(path))
        except OSError as exc:
            raise RuntimeError(f"企业微信 SDK 动态库加载失败：{exc}") from exc

    def _configure_functions(self) -> None:
        lib = self._lib
        lib.NewSdk.argtypes = []
        lib.NewSdk.restype = ctypes.c_void_p
        lib.Init.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.Init.restype = ctypes.c_int
        lib.DestroySdk.argtypes = [ctypes.c_void_p]
        lib.DestroySdk.restype = None

        lib.NewSlice.argtypes = []
        lib.NewSlice.restype = ctypes.c_void_p
        lib.FreeSlice.argtypes = [ctypes.c_void_p]
        lib.FreeSlice.restype = None
        lib.GetContentFromSlice.argtypes = [ctypes.c_void_p]
        lib.GetContentFromSlice.restype = ctypes.c_void_p
        lib.GetSliceLen.argtypes = [ctypes.c_void_p]
        lib.GetSliceLen.restype = ctypes.c_int
        lib.GetChatData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulonglong,
            ctypes.c_uint,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        lib.GetChatData.restype = ctypes.c_int
        lib.DecryptData.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p]
        lib.DecryptData.restype = ctypes.c_int

        lib.NewMediaData.argtypes = []
        lib.NewMediaData.restype = ctypes.c_void_p
        lib.FreeMediaData.argtypes = [ctypes.c_void_p]
        lib.FreeMediaData.restype = None
        lib.GetMediaData.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        lib.GetMediaData.restype = ctypes.c_int
        lib.GetOutIndexBuf.argtypes = [ctypes.c_void_p]
        lib.GetOutIndexBuf.restype = ctypes.c_void_p
        lib.GetData.argtypes = [ctypes.c_void_p]
        lib.GetData.restype = ctypes.c_void_p
        lib.GetIndexLen.argtypes = [ctypes.c_void_p]
        lib.GetIndexLen.restype = ctypes.c_int
        lib.GetDataLen.argtypes = [ctypes.c_void_p]
        lib.GetDataLen.restype = ctypes.c_int
        lib.IsMediaDataFinish.argtypes = [ctypes.c_void_p]
        lib.IsMediaDataFinish.restype = ctypes.c_int

    def __enter__(self) -> "NativeSdkClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "_sdk", None):
            self._lib.DestroySdk(self._sdk)
            self._sdk = None

    def get_chat_data(self, seq: int, limit: int, timeout_seconds: int) -> bytes:
        output = self._lib.NewSlice()
        if not output:
            raise RuntimeError("企业微信 SDK NewSlice 返回空指针")
        try:
            code = self._lib.GetChatData(
                self._sdk,
                seq,
                limit,
                b"",
                b"",
                timeout_seconds,
                output,
            )
            if code != 0:
                raise WeComFinanceSdkError("GetChatData", code)
            return self._slice_bytes(output, "GetChatData")
        finally:
            self._lib.FreeSlice(output)

    def decrypt_data(self, random_key: bytes, encrypted_message: str) -> bytes:
        output = self._lib.NewSlice()
        if not output:
            raise RuntimeError("企业微信 SDK NewSlice 返回空指针")
        try:
            code = self._lib.DecryptData(random_key, encrypted_message.encode("utf-8"), output)
            if code != 0:
                raise WeComFinanceSdkError("DecryptData", code)
            return self._slice_bytes(output, "DecryptData")
        finally:
            self._lib.FreeSlice(output)

    def download_media(self, sdk_file_id: str, timeout_seconds: int, max_bytes: int) -> bytes:
        index_buffer = b""
        chunks: list[bytes] = []
        total_size = 0
        for _ in range(10_000):
            media_data = self._lib.NewMediaData()
            if not media_data:
                raise RuntimeError("企业微信 SDK NewMediaData 返回空指针")
            try:
                code = self._lib.GetMediaData(
                    self._sdk,
                    index_buffer,
                    sdk_file_id.encode("utf-8"),
                    b"",
                    b"",
                    timeout_seconds,
                    media_data,
                )
                if code != 0:
                    raise WeComFinanceSdkError("GetMediaData", code)

                data_length = self._non_negative_length(self._lib.GetDataLen(media_data), "媒体分片")
                data_pointer = self._lib.GetData(media_data)
                chunk = ctypes.string_at(data_pointer, data_length) if data_length else b""
                total_size += len(chunk)
                if total_size > max_bytes:
                    raise RuntimeError(f"企业微信媒体文件超过 sidecar 限制：{max_bytes} bytes")
                chunks.append(chunk)

                is_finished = self._lib.IsMediaDataFinish(media_data)
                if is_finished == 1:
                    return b"".join(chunks)

                index_length = self._non_negative_length(self._lib.GetIndexLen(media_data), "媒体索引")
                index_pointer = self._lib.GetOutIndexBuf(media_data)
                next_index = ctypes.string_at(index_pointer, index_length) if index_length else b""
                if not next_index or (next_index == index_buffer and not chunk):
                    raise RuntimeError("企业微信媒体分片下载未返回有效的下一页索引")
                index_buffer = next_index
            finally:
                self._lib.FreeMediaData(media_data)
        raise RuntimeError("企业微信媒体分片数量超过安全限制")

    def _slice_bytes(self, slice_pointer: int, operation: str) -> bytes:
        length = self._non_negative_length(self._lib.GetSliceLen(slice_pointer), operation)
        content_pointer = self._lib.GetContentFromSlice(slice_pointer)
        if length and not content_pointer:
            raise RuntimeError(f"企业微信 SDK {operation} 返回空内容指针")
        return ctypes.string_at(content_pointer, length) if length else b""

    @staticmethod
    def _non_negative_length(value: int, field_name: str) -> int:
        if value < 0:
            raise RuntimeError(f"企业微信 SDK {field_name}返回非法长度：{value}")
        return value


ClientFactory = Callable[[Path, str, str], NativeSdkClient]


class WeComFinanceSdkBackend:
    def __init__(
        self,
        client_factory: ClientFactory | None = None,
        library_path: Path | None = None,
    ) -> None:
        self.client_factory = client_factory or NativeSdkClient
        self.library_path = library_path or _configured_library_path()
        self.timeout_seconds = _positive_env_int("WECOM_FINANCE_SDK_TIMEOUT_SECONDS", 10)
        self.max_media_bytes = _positive_env_int("WECOM_ARCHIVE_MEDIA_MAX_BYTES", 50 * 1024 * 1024)

    def fetch_messages(self, request: Any) -> list[dict[str, Any]]:
        private_key = _load_private_key(request.private_key_pem())
        expected_key_version = str(request.public_key_ver)
        with self.client_factory(self.library_path, request.corp_id, request.archive_secret) as client:
            response = _decode_json(client.get_chat_data(request.seq, request.limit, self.timeout_seconds), "GetChatData")
            error_code = int(response.get("errcode") or 0)
            if error_code != 0:
                raise WeComFinanceSdkError("GetChatData", error_code, str(response.get("errmsg") or ""))
            encrypted_messages = response.get("chatdata") or []
            if not isinstance(encrypted_messages, list):
                raise RuntimeError("企业微信 SDK GetChatData 响应缺少 chatdata 列表")

            messages: list[dict[str, Any]] = []
            for encrypted in encrypted_messages:
                if not isinstance(encrypted, dict):
                    raise RuntimeError("企业微信 SDK chatdata 包含非对象数据")
                actual_key_version = str(encrypted.get("publickey_ver") or "")
                if actual_key_version != expected_key_version:
                    raise RuntimeError(
                        "企业微信消息公钥版本不匹配："
                        f"消息使用版本 {actual_key_version or 'unknown'}，当前配置版本 {expected_key_version}"
                    )
                random_key = _decrypt_random_key(private_key, str(encrypted.get("encrypt_random_key") or ""))
                encrypted_message = str(encrypted.get("encrypt_chat_msg") or "")
                if not encrypted_message:
                    raise RuntimeError("企业微信 SDK chatdata 缺少 encrypt_chat_msg")
                message = _decode_json(client.decrypt_data(random_key, encrypted_message), "DecryptData")
                message.setdefault("seq", encrypted.get("seq"))
                message.setdefault("publickey_ver", encrypted.get("publickey_ver"))
                messages.append(message)
            return messages

    def download_media(self, request: Any) -> bytes:
        sdk_file_id = _extract_sdk_file_id(request.raw_message)
        with self.client_factory(self.library_path, request.corp_id, request.archive_secret) as client:
            content = client.download_media(sdk_file_id, self.timeout_seconds, self.max_media_bytes)
        _verify_media_integrity(request.raw_message, content)
        return content


def create_backend() -> WeComFinanceSdkBackend:
    return WeComFinanceSdkBackend()


def _configured_library_path() -> Path:
    default_path = Path(__file__).resolve().parent / "sdk" / "libWeWorkFinanceSdk_C.so"
    configured = os.getenv("WECOM_FINANCE_SDK_LIBRARY", "").strip()
    return Path(configured).expanduser().resolve() if configured else default_path


def _positive_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} 必须是正整数") from exc
    if value <= 0:
        raise RuntimeError(f"{name} 必须是正整数")
    return value


def _load_private_key(private_key_pem: str) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("企业微信会话存档私钥格式无效") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise RuntimeError("企业微信会话存档私钥必须是 RSA 私钥")
    if key.key_size != 2048:
        raise RuntimeError("企业微信会话存档 RSA 私钥必须是 2048 bit")
    return key


def _decrypt_random_key(private_key: rsa.RSAPrivateKey, encrypted_random_key: str) -> bytes:
    if not encrypted_random_key:
        raise RuntimeError("企业微信 SDK chatdata 缺少 encrypt_random_key")
    try:
        encrypted = base64.b64decode(encrypted_random_key, validate=True)
        return private_key.decrypt(encrypted, padding.PKCS1v15())
    except (ValueError, binascii.Error) as exc:
        raise RuntimeError("企业微信消息随机密钥 RSA 解密失败") from exc


def _decode_json(content: bytes, operation: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"企业微信 SDK {operation} 返回的 JSON 无效") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"企业微信 SDK {operation} 返回的 JSON 顶层必须是对象")
    return value


def _extract_sdk_file_id(raw_message: dict[str, Any]) -> str:
    msg_type = str(raw_message.get("msgtype") or "")
    candidates = [raw_message.get(msg_type), raw_message.get("info")]
    candidates.extend(raw_message.get(key) for key in ("image", "file", "voice", "video", "emotion", "voip_doc_share"))
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("sdkfileid"):
            return str(candidate["sdkfileid"])
    raise RuntimeError("企业微信媒体消息缺少 sdkfileid")


def _verify_media_integrity(raw_message: dict[str, Any], content: bytes) -> None:
    msg_type = str(raw_message.get("msgtype") or "")
    payload = raw_message.get(msg_type)
    if not isinstance(payload, dict):
        return
    expected_size = payload.get("filesize") or payload.get("voice_size") or payload.get("imagesize")
    if expected_size is not None and int(expected_size) != len(content):
        raise RuntimeError(f"企业微信媒体文件大小校验失败：expected={expected_size}, actual={len(content)}")
    expected_md5 = str(payload.get("md5sum") or "").lower()
    if expected_md5:
        actual_md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
        if actual_md5 != expected_md5:
            raise RuntimeError("企业微信媒体文件 MD5 校验失败")
