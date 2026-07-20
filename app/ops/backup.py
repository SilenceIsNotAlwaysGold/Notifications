import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class BackupError(RuntimeError):
    pass


def sqlite_path_from_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise BackupError("当前备份工具仅支持 SQLite DATABASE_URL")
    return Path(database_url[len(prefix) :]).expanduser().resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_sqlite_integrity(path: Path) -> None:
    try:
        with sqlite3.connect(path) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"SQLite 完整性检查失败：{exc}") from exc
    if not result or result[0] != "ok":
        raise BackupError(f"SQLite 完整性检查失败：{result[0] if result else '无结果'}")


def create_backup(
    *,
    database_path: Path,
    media_dir: Path,
    backup_root: Path,
    retention_days: int = 14,
    created_at: datetime | None = None,
) -> Path:
    database_path = database_path.expanduser().resolve()
    media_dir = media_dir.expanduser().resolve()
    backup_root = backup_root.expanduser().resolve()
    if not database_path.is_file():
        raise BackupError(f"SQLite 数据库不存在：{database_path}")
    if retention_days < 1:
        raise BackupError("备份保留天数必须大于 0")

    timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    backup_id = timestamp.strftime("%Y%m%dT%H%M%SZ")
    backup_root.mkdir(parents=True, exist_ok=True)
    final_dir = backup_root / backup_id
    counter = 1
    while final_dir.exists():
        final_dir = backup_root / f"{backup_id}-{counter}"
        counter += 1
    staging_dir = backup_root / f".{final_dir.name}.tmp"
    staging_dir.mkdir(parents=True, exist_ok=False)

    try:
        database_backup = staging_dir / "legal_wecom.db"
        with sqlite3.connect(database_path) as source, sqlite3.connect(database_backup) as target:
            source.backup(target)
        check_sqlite_integrity(database_backup)

        media_archive = staging_dir / "media.tar.gz"
        with tarfile.open(media_archive, "w:gz") as archive:
            if media_dir.is_dir():
                archive.add(media_dir, arcname="media", recursive=True)
            else:
                info = tarfile.TarInfo("media")
                info.type = tarfile.DIRTYPE
                info.mode = 0o750
                archive.addfile(info)

        manifest: dict[str, Any] = {
            "version": 1,
            "backup_id": final_dir.name,
            "created_at": timestamp.isoformat(),
            "database_source": str(database_path),
            "media_source": str(media_dir),
            "files": {
                "database": {
                    "path": database_backup.name,
                    "size": database_backup.stat().st_size,
                    "sha256": sha256_file(database_backup),
                },
                "media": {
                    "path": media_archive.name,
                    "size": media_archive.stat().st_size,
                    "sha256": sha256_file(media_archive),
                },
            },
        }
        (staging_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(staging_dir, final_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    prune_backups(backup_root, retention_days=retention_days, now=timestamp)
    return final_dir


def prune_backups(backup_root: Path, *, retention_days: int, now: datetime | None = None) -> list[Path]:
    cutoff = (now or datetime.now(timezone.utc)).timestamp() - timedelta(days=retention_days).total_seconds()
    removed = []
    for candidate in backup_root.iterdir() if backup_root.exists() else []:
        if not candidate.is_dir() or candidate.name.startswith("."):
            continue
        manifest = candidate / "manifest.json"
        if manifest.exists() and manifest.stat().st_mtime < cutoff:
            shutil.rmtree(candidate)
            removed.append(candidate)
    return removed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="备份法务自动化 SQLite 数据库和媒体文件")
    parser.add_argument("--database", type=Path, help="SQLite 数据库路径")
    parser.add_argument("--media", type=Path, help="媒体目录")
    parser.add_argument("--output", type=Path, help="备份根目录")
    parser.add_argument("--retention-days", type=int, help="保留天数")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database_path = args.database or sqlite_path_from_url(os.getenv("DATABASE_URL", "sqlite:///./legal_wecom.db"))
    media_dir = args.media or Path(os.getenv("MEDIA_STORAGE_DIR", "./storage/media"))
    backup_root = args.output or Path(os.getenv("OPS_BACKUP_DIR", "./storage/backups"))
    retention_days = args.retention_days or int(os.getenv("OPS_BACKUP_RETENTION_DAYS", "14"))
    backup_dir = create_backup(
        database_path=database_path,
        media_dir=media_dir,
        backup_root=backup_root,
        retention_days=retention_days,
    )
    print(json.dumps({"status": "ok", "backup_dir": str(backup_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
