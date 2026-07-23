import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.media_file import MediaFile
from app.utils.datetime_utils import ensure_aware, now_tz
from app.utils.media_storage import MediaStorage


class DataRetentionService:
    """Purges configured media bytes while preserving business and audit records."""

    def __init__(self, db: Session, settings: Settings | None = None, storage: MediaStorage | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.storage = storage or MediaStorage()

    def run(self, current_time: datetime | None = None, batch_size: int = 500) -> dict[str, int | bool | str]:
        if not self.settings.legal_data_retention_enabled:
            return {"enabled": False, "checked": 0, "purged": 0, "failed": 0}
        statuses = self.settings.legal_data_retention_status_list
        if not statuses:
            return {"enabled": True, "checked": 0, "purged": 0, "failed": 0, "error": "未配置可清理的复核状态"}

        now = ensure_aware(current_time) if current_time else now_tz()
        cutoff = now - timedelta(days=self.settings.legal_data_retention_days)
        media_files = list(
            self.db.scalars(
                select(MediaFile)
                .where(MediaFile.created_at < cutoff)
                .where(MediaFile.local_path.is_not(None))
                .where(MediaFile.review_status.in_(statuses))
                .order_by(MediaFile.created_at.asc(), MediaFile.id.asc())
                .limit(batch_size)
            ).all()
        )
        purged = 0
        failed = 0
        for media_file in media_files:
            try:
                path = self.storage.resolve_local_path(media_file.local_path or "")
                if path.is_file():
                    path.unlink()
                metadata = self._metadata(media_file.metadata_json)
                metadata["retention_purged_at"] = now.isoformat()
                metadata["retention_days"] = self.settings.legal_data_retention_days
                media_file.metadata_json = json.dumps(metadata, ensure_ascii=False)
                media_file.local_path = None
                media_file.public_url = None
                media_file.download_status = "purged"
                media_file.updated_at = now_tz()
                purged += 1
            except (OSError, ValueError):
                failed += 1
        self.db.flush()
        return {"enabled": True, "checked": len(media_files), "purged": purged, "failed": failed}

    @staticmethod
    def _metadata(raw: str | None) -> dict:
        try:
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
