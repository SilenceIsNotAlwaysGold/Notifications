import re
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.utils.datetime_utils import today_tz


class MediaStorage:
    def __init__(self, root_dir: str | None = None, public_base_url: str | None = None) -> None:
        settings = get_settings()
        self.root_dir = Path(root_dir or settings.media_storage_dir)
        self.public_base_url = public_base_url if public_base_url is not None else settings.media_public_base_url

    def ensure_root(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def build_local_path(
        self,
        msg_id: str | None = None,
        seq: int | None = None,
        original_filename: str | None = None,
        media_type: str = "unknown",
        current_date: date | None = None,
    ) -> str:
        self.ensure_root()
        day = current_date or today_tz()
        directory = self.root_dir / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
        directory.mkdir(parents=True, exist_ok=True)
        original_ext = Path(Path(original_filename or "").name).suffix
        ext = original_ext or self._default_ext(media_type)
        stem_source = msg_id or (f"seq_{seq}" if seq is not None else "media")
        stem = self._safe_filename(Path(stem_source).stem) or "media"
        filename = f"{stem}{ext}"
        return str(directory / filename)

    def save_bytes(self, local_path: str, content: bytes) -> int:
        path = self._assert_inside_root(local_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path.stat().st_size

    def file_exists(self, local_path: str) -> bool:
        return self._assert_inside_root(local_path).exists()

    def get_public_url(self, local_path: str) -> str | None:
        if not self.public_base_url:
            return None
        path = self._assert_inside_root(local_path)
        relative = path.relative_to(self.root_dir).as_posix()
        return f"{self.public_base_url.rstrip('/')}/{relative}"

    def _assert_inside_root(self, local_path: str) -> Path:
        self.ensure_root()
        path = Path(local_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        root = self.root_dir
        if not root.is_absolute():
            root = Path.cwd() / root
        resolved_path = path.resolve()
        resolved_root = root.resolve()
        if resolved_root != resolved_path and resolved_root not in resolved_path.parents:
            raise ValueError("媒体文件路径不允许越过存储目录")
        return resolved_path

    @staticmethod
    def _safe_filename(filename: str) -> str:
        name = Path(filename).name
        return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")

    @staticmethod
    def _default_ext(media_type: str) -> str:
        if media_type == "image":
            return ".jpg"
        if media_type == "pdf":
            return ".pdf"
        return ".bin"
