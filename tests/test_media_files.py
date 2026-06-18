import base64
from pathlib import Path

import httpx
from sqlalchemy import select

from app.adapters.wecom_media import WeComMediaAdapter
from app.core.config import get_settings
from app.models.group_message import GroupMessage
from app.models.media_file import MediaFile


def replay_message(client, raw_message):
    response = client.post("/api/v1/legal/wecom-archive/replay", json={"messages": [raw_message]})
    assert response.status_code == 200
    assert response.json()["code"] == 0
    return response.json()["data"]


def image_message(seq=2, msgid="msg_img_001"):
    return {
        "seq": seq,
        "msgid": msgid,
        "roomid": "group_001",
        "from": "user_001",
        "msgtype": "image",
        "image": {"md5sum": "abc", "filesize": 12345},
        "msgtime": 1780300000000,
    }


def pdf_message(seq=3, msgid="msg_file_001"):
    return {
        "seq": seq,
        "msgid": msgid,
        "roomid": "group_001",
        "from": "user_001",
        "msgtype": "file",
        "file": {"filename": "判决书.pdf", "md5sum": "def", "filesize": 45678},
        "msgtime": 1780300000000,
    }


def test_replay_image_creates_media_file(client, db_session):
    result = replay_message(client, image_message())

    assert result == {"pulled": 1, "processed": 1, "failed": 0, "last_seq": 2}
    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "msg_img_001"))
    assert media_file is not None
    assert media_file.media_type == "image"
    assert media_file.group_message_id is not None
    assert media_file.download_status == "downloaded"
    assert media_file.local_path is not None
    assert Path(media_file.local_path).exists()


def test_replay_pdf_file_sets_media_type_pdf(client, db_session):
    replay_message(client, pdf_message())

    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "msg_file_001"))
    assert media_file is not None
    assert media_file.media_type == "pdf"
    assert media_file.original_filename == "判决书.pdf"
    assert media_file.file_ext == ".pdf"
    assert media_file.download_status == "downloaded"


def test_mock_download_marks_downloaded(client, db_session):
    replay_message(client, image_message(seq=4, msgid="msg_img_download"))

    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "msg_img_download"))
    assert media_file.download_status == "downloaded"
    assert media_file.file_size is not None
    assert media_file.file_size > 0


def test_ocr_mock_marks_processed_or_skipped(client, db_session):
    replay_message(client, image_message(seq=5, msgid="msg_img_ocr"))

    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "msg_img_ocr"))
    assert media_file.ocr_status in {"processed", "skipped"}
    assert media_file.ocr_status != "failed"


def test_list_media_files_api_returns_records(client):
    replay_message(client, image_message(seq=6, msgid="msg_img_list"))

    response = client.get("/api/v1/legal/media-files", params={"group_id": "group_001", "media_type": "image"})

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["total"] >= 1
    assert body["data"]["items"][0]["media_type"] == "image"


def test_manual_download_endpoint_works(client, db_session):
    replay_message(client, image_message(seq=7, msgid="msg_img_manual_download"))
    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "msg_img_manual_download"))
    media_file.download_status = "pending"
    media_file.local_path = None
    db_session.commit()

    response = client.post(f"/api/v1/legal/media-files/{media_file.id}/download")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["download_status"] == "downloaded"
    assert data["local_path"] is not None


def test_manual_ocr_endpoint_works(client, db_session):
    replay_message(client, pdf_message(seq=8, msgid="msg_pdf_manual_ocr"))
    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "msg_pdf_manual_ocr"))

    response = client.post(f"/api/v1/legal/media-files/{media_file.id}/ocr")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ocr_status"] in {"processed", "skipped"}
    assert data["ocr_status"] != "failed"


def test_media_download_failure_does_not_block_group_message(client, db_session, monkeypatch):
    def fail_download(self, raw_message, target_path):
        raise RuntimeError("mock download boom")

    monkeypatch.setattr("app.adapters.wecom_media.WeComMediaAdapter.download_media", fail_download)
    result = replay_message(client, image_message(seq=9, msgid="msg_img_fail"))

    assert result == {"pulled": 1, "processed": 1, "failed": 0, "last_seq": 9}
    group_message = db_session.scalar(select(GroupMessage).where(GroupMessage.msg_type == "image"))
    media_file = db_session.scalar(select(MediaFile).where(MediaFile.msg_id == "msg_img_fail"))
    assert group_message is not None
    assert media_file is not None
    assert media_file.download_status == "pending"


def test_real_media_download_uses_sidecar_and_writes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_DOWNLOAD_MODE", "real")
    monkeypatch.setenv("WECOM_CORP_ID", "wwxxxx")
    monkeypatch.setenv("WECOM_ARCHIVE_SECRET", "archive-secret")
    monkeypatch.setenv("WECOM_ARCHIVE_PRIVATE_KEY_PATH", "/secure/private.pem")
    monkeypatch.setenv("WECOM_ARCHIVE_PUBLIC_KEY_VER", "1")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "http://127.0.0.1:9001/wecom-archive")
    get_settings.cache_clear()
    content = b"real media bytes"

    def fake_post(url, json=None, timeout=None):
        assert url == "http://127.0.0.1:9001/wecom-archive/media/download"
        assert json["raw_message"]["msgid"] == "msg_real_media"
        assert json["target_filename"] == "msg_real_media.jpg"
        assert json["corp_id"] == "wwxxxx"
        assert json["archive_secret"] == "archive-secret"
        assert json["private_key_path"] == "/secure/private.pem"
        assert json["public_key_ver"] == "1"
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"content_base64": base64.b64encode(content).decode("ascii")}, request=request)

    monkeypatch.setattr("app.adapters.wecom_media.httpx.post", fake_post)
    target_path = tmp_path / "msg_real_media.jpg"

    result = WeComMediaAdapter().download_media({"msgid": "msg_real_media", "msgtype": "image"}, str(target_path))

    assert result["success"] is True
    assert result["local_path"] == str(target_path)
    assert result["file_size"] == len(content)
    assert target_path.read_bytes() == content
    get_settings.cache_clear()


def test_real_media_download_without_sidecar_returns_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_DOWNLOAD_MODE", "real")
    monkeypatch.setenv("WECOM_ARCHIVE_SIDECAR_URL", "")
    get_settings.cache_clear()

    result = WeComMediaAdapter().download_media({"msgid": "msg_real_media", "msgtype": "image"}, str(tmp_path / "media.jpg"))

    assert result["success"] is False
    assert "WECOM_ARCHIVE_SIDECAR_URL" in result["error"]
    get_settings.cache_clear()
