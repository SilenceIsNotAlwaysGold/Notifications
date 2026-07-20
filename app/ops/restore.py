import argparse
import json
import os
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ops.backup import BackupError, check_sqlite_integrity, sha256_file, sqlite_path_from_url


class BackupValidationError(BackupError):
    pass


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    backup_dir = backup_dir.expanduser().resolve()
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        raise BackupValidationError("备份清单 manifest.json 不存在")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise BackupValidationError(f"备份清单无法读取：{exc}") from exc
    if manifest.get("version") != 1:
        raise BackupValidationError("不支持的备份清单版本")

    for label in ("database", "media"):
        item = (manifest.get("files") or {}).get(label) or {}
        relative_path = item.get("path")
        if not relative_path:
            raise BackupValidationError(f"备份清单缺少 {label} 文件")
        path = (backup_dir / relative_path).resolve()
        if backup_dir not in path.parents or not path.is_file():
            raise BackupValidationError(f"备份文件路径非法或不存在：{label}")
        if path.stat().st_size != item.get("size") or sha256_file(path) != item.get("sha256"):
            raise BackupValidationError(f"备份文件校验失败：{label}")
    database_path = backup_dir / manifest["files"]["database"]["path"]
    check_sqlite_integrity(database_path)
    return manifest


def restore_backup(
    *,
    backup_dir: Path,
    database_path: Path,
    media_dir: Path,
    force: bool = False,
) -> dict[str, str]:
    backup_dir = backup_dir.expanduser().resolve()
    database_path = database_path.expanduser().resolve()
    media_dir = media_dir.expanduser().resolve()
    manifest = verify_backup(backup_dir)
    if not force and (database_path.exists() or media_dir.exists()):
        raise BackupValidationError("目标数据库或媒体目录已存在；确认停机后使用 --force 恢复")

    restore_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    database_source = backup_dir / manifest["files"]["database"]["path"]
    media_source = backup_dir / manifest["files"]["media"]["path"]
    database_path.parent.mkdir(parents=True, exist_ok=True)
    media_dir.parent.mkdir(parents=True, exist_ok=True)
    database_staging = database_path.with_name(f".{database_path.name}.restore-{restore_id}")
    media_staging_root = media_dir.parent / f".{media_dir.name}.restore-{restore_id}"
    shutil.copy2(database_source, database_staging)
    check_sqlite_integrity(database_staging)
    media_staging_root.mkdir(parents=True, exist_ok=False)
    previous_database = database_path.with_name(f"{database_path.name}.pre-restore-{restore_id}")
    previous_media = media_dir.with_name(f"{media_dir.name}.pre-restore-{restore_id}")
    database_replaced = False
    media_replaced = False
    try:
        _safe_extract(media_source, media_staging_root)
        extracted_media = media_staging_root / "media"
        if not extracted_media.is_dir():
            raise BackupValidationError("媒体备份中缺少 media 目录")

        if previous_database.exists() or previous_media.exists():
            raise BackupValidationError("同名 pre-restore 回滚文件已存在，请稍后重试")
        if database_path.exists():
            os.replace(database_path, previous_database)
        os.replace(database_staging, database_path)
        database_replaced = True
        if media_dir.exists():
            os.replace(media_dir, previous_media)
        os.replace(extracted_media, media_dir)
        media_replaced = True
    except Exception:
        database_staging.unlink(missing_ok=True)
        if media_replaced and media_dir.exists():
            shutil.rmtree(media_dir, ignore_errors=True)
        if previous_media.exists():
            os.replace(previous_media, media_dir)
        if database_replaced and database_path.exists():
            database_path.unlink(missing_ok=True)
        if previous_database.exists():
            os.replace(previous_database, database_path)
        raise
    finally:
        shutil.rmtree(media_staging_root, ignore_errors=True)

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {
        "status": "ok",
        "backup_id": str(manifest.get("backup_id")),
        "database": str(database_path),
        "media": str(media_dir),
    }


def _safe_extract(archive_path: Path, target_dir: Path) -> None:
    target_root = target_dir.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            destination = (target_root / member.name).resolve()
            if target_root != destination and target_root not in destination.parents:
                raise BackupValidationError("媒体备份包含路径穿越条目")
            if member.issym() or member.islnk():
                raise BackupValidationError("媒体备份不允许符号链接或硬链接")
        archive.extractall(target_root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="校验并恢复法务自动化备份")
    parser.add_argument("backup_dir", type=Path, help="包含 manifest.json 的备份目录")
    parser.add_argument("--database", type=Path, help="SQLite 恢复目标")
    parser.add_argument("--media", type=Path, help="媒体恢复目标")
    parser.add_argument("--force", action="store_true", help="允许替换现有数据库和媒体目录")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    database_path = args.database or sqlite_path_from_url(os.getenv("DATABASE_URL", "sqlite:///./legal_wecom.db"))
    media_dir = args.media or Path(os.getenv("MEDIA_STORAGE_DIR", "./storage/media"))
    result = restore_backup(
        backup_dir=args.backup_dir,
        database_path=database_path,
        media_dir=media_dir,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
