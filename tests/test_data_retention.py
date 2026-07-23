from datetime import timedelta

from app.core.config import Settings
from app.models.media_file import MediaFile
from app.services.data_retention_service import DataRetentionService
from app.utils.datetime_utils import now_tz
from app.utils.media_storage import MediaStorage


def _media(db_session, path, *, status="rejected", age_days=100):
    item = MediaFile(
        group_id="group-retention",
        media_type="image",
        local_path=str(path),
        download_status="downloaded",
        ocr_status="processed",
        review_status=status,
        created_at=now_tz() - timedelta(days=age_days),
    )
    db_session.add(item)
    db_session.flush()
    return item


def test_retention_is_disabled_by_default(db_session, tmp_path):
    media_root = tmp_path / "media"
    path = media_root / "old.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old")
    item = _media(db_session, path)

    result = DataRetentionService(db_session, Settings(), MediaStorage(str(media_root))).run()

    assert result["enabled"] is False
    assert path.exists()
    assert item.local_path == str(path)


def test_explicit_retention_policy_purges_only_selected_status(db_session, tmp_path):
    media_root = tmp_path / "media"
    rejected_path = media_root / "rejected.jpg"
    approved_path = media_root / "approved.jpg"
    media_root.mkdir(parents=True)
    rejected_path.write_bytes(b"rejected")
    approved_path.write_bytes(b"approved")
    rejected = _media(db_session, rejected_path, status="rejected")
    approved = _media(db_session, approved_path, status="approved")
    settings = Settings(
        LEGAL_DATA_RETENTION_ENABLED=True,
        LEGAL_DATA_RETENTION_DAYS=30,
        LEGAL_DATA_RETENTION_REVIEW_STATUSES="rejected",
    )

    result = DataRetentionService(db_session, settings, MediaStorage(str(media_root))).run()

    assert result == {"enabled": True, "checked": 1, "purged": 1, "failed": 0}
    assert not rejected_path.exists()
    assert rejected.local_path is None
    assert rejected.download_status == "purged"
    assert approved_path.exists()
    assert approved.local_path == str(approved_path)
