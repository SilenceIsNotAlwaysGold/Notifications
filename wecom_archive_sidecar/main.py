import base64
import importlib
import os
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator


class ArchiveCredentials(BaseModel):
    corp_id: str | None = None
    archive_secret: str | None = None
    private_key_path: str | None = None
    private_key: str | None = None
    public_key_ver: str | None = None

    @model_validator(mode="after")
    def validate_private_key_source(self) -> "ArchiveCredentials":
        if os.getenv("WECOM_ARCHIVE_SIDECAR_BACKEND", "").strip() == "mock":
            return self
        missing = []
        if not self.corp_id:
            missing.append("corp_id")
        if not self.archive_secret:
            missing.append("archive_secret")
        if not self.public_key_ver:
            missing.append("public_key_ver")
        if not self.private_key and not self.private_key_path:
            missing.append("private_key 或 private_key_path")
        if missing:
            raise ValueError(f"缺少企业微信会话存档凭证：{', '.join(missing)}")
        return self

    def private_key_pem(self) -> str:
        if self.private_key:
            return self.private_key
        if not self.private_key_path:
            return ""
        assert self.private_key_path is not None
        path = Path(self.private_key_path)
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"private_key_path 不存在：{path}")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text()


class MessagesRequest(ArchiveCredentials):
    seq: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class MediaDownloadRequest(ArchiveCredentials):
    raw_message: dict[str, Any]
    target_filename: str


class ArchiveBackend(Protocol):
    def fetch_messages(self, request: MessagesRequest) -> list[dict[str, Any]]:
        ...

    def download_media(self, request: MediaDownloadRequest) -> bytes:
        ...


class NotConfiguredBackend:
    def fetch_messages(self, request: MessagesRequest) -> list[dict[str, Any]]:
        request.private_key_pem()
        raise HTTPException(
            status_code=501,
            detail="尚未配置企业微信会话内容存档 SDK backend。请设置 WECOM_ARCHIVE_SIDECAR_BACKEND=module:function",
        )

    def download_media(self, request: MediaDownloadRequest) -> bytes:
        request.private_key_pem()
        raise HTTPException(
            status_code=501,
            detail="尚未配置企业微信媒体下载 SDK backend。请设置 WECOM_ARCHIVE_SIDECAR_BACKEND=module:function",
        )


class MockBackend:
    def fetch_messages(self, request: MessagesRequest) -> list[dict[str, Any]]:
        request.private_key_pem()
        scenario = os.getenv("WECOM_ARCHIVE_SIDECAR_MOCK_SCENARIO", "").strip()
        if scenario != "legal_demo":
            return []
        return [
            message
            for message in _legal_demo_messages()
            if int(message.get("seq", 0)) > request.seq
        ][: request.limit]

    def download_media(self, request: MediaDownloadRequest) -> bytes:
        request.private_key_pem()
        filename = request.target_filename.lower()
        if filename.endswith(".pdf"):
            return b"%PDF-1.4\n% mock wecom archive pdf\n"
        if filename.endswith((".jpg", ".jpeg", ".png")):
            return b"mock wecom archive image bytes"
        return f"mock media for {request.target_filename}".encode("utf-8")


def _legal_demo_messages() -> list[dict[str, Any]]:
    return [
        {
            "seq": 3001,
            "msgid": "sidecar_demo_judgment",
            "roomid": "group_001",
            "from": "user_sidecar",
            "msgtype": "file",
            "file": {"filename": "判决书.pdf", "md5sum": "sidecar-demo", "filesize": 100},
            "msgtime": 1780300000000,
        },
        {
            "seq": 3002,
            "msgid": "sidecar_demo_court",
            "roomid": "group_001",
            "from": "user_sidecar",
            "msgtype": "file",
            "file": {"filename": "开庭传票.pdf", "md5sum": "sidecar-demo", "filesize": 100},
            "msgtime": 1780300060000,
        },
        {
            "seq": 3003,
            "msgid": "sidecar_demo_payment_notice",
            "roomid": "group_001",
            "from": "user_sidecar",
            "msgtype": "file",
            "file": {"filename": "缴费通知.pdf", "md5sum": "sidecar-demo", "filesize": 100},
            "msgtime": 1780300120000,
        },
        {
            "seq": 3004,
            "msgid": "sidecar_demo_payment_done",
            "roomid": "group_001",
            "from": "user_sidecar",
            "msgtype": "image",
            "image": {"md5sum": "sidecar-demo", "filesize": 100},
            "msgtime": 1780300180000,
        },
    ]


def load_backend() -> ArchiveBackend:
    backend_spec = os.getenv("WECOM_ARCHIVE_SIDECAR_BACKEND", "").strip()
    if not backend_spec:
        return NotConfiguredBackend()
    if backend_spec == "mock":
        return MockBackend()
    if ":" not in backend_spec:
        raise RuntimeError("WECOM_ARCHIVE_SIDECAR_BACKEND 必须是 mock 或 module:function")

    module_name, factory_name = backend_spec.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name)
    backend = factory()
    if not hasattr(backend, "fetch_messages") or not hasattr(backend, "download_media"):
        raise RuntimeError("企业微信归档 backend 必须实现 fetch_messages 和 download_media")
    return backend


app = FastAPI(title="wecom-archive-sidecar")


@app.get("/wecom-archive/health")
def health() -> dict[str, str]:
    backend = os.getenv("WECOM_ARCHIVE_SIDECAR_BACKEND", "").strip() or "not_configured"
    return {"status": "ok", "backend": backend}


@app.post("/wecom-archive/messages")
def messages(payload: MessagesRequest) -> dict[str, list[dict[str, Any]]]:
    backend = load_backend()
    return {"messages": backend.fetch_messages(payload)}


@app.post("/wecom-archive/media/download")
def media_download(payload: MediaDownloadRequest) -> dict[str, str]:
    backend = load_backend()
    content = backend.download_media(payload)
    return {"content_base64": base64.b64encode(content).decode("ascii")}
