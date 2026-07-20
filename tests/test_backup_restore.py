import sqlite3
from datetime import datetime, timezone

import pytest

from app.ops.backup import create_backup
from app.ops.restore import BackupValidationError, restore_backup, verify_backup


def create_database(path, value="original"):
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample (value) VALUES (?)", (value,))


def read_database(path):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT value FROM sample").fetchone()[0]


def test_backup_and_force_restore_database_and_media(tmp_path):
    database = tmp_path / "legal.db"
    media = tmp_path / "media"
    media.mkdir()
    (media / "evidence.txt").write_text("original media", encoding="utf-8")
    create_database(database)

    backup_dir = create_backup(
        database_path=database,
        media_dir=media,
        backup_root=tmp_path / "backups",
        retention_days=14,
    )
    verify_backup(backup_dir)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE sample SET value = 'changed'")
    (media / "evidence.txt").write_text("changed media", encoding="utf-8")

    result = restore_backup(
        backup_dir=backup_dir,
        database_path=database,
        media_dir=media,
        force=True,
    )

    assert result["status"] == "ok"
    assert read_database(database) == "original"
    assert (media / "evidence.txt").read_text(encoding="utf-8") == "original media"


def test_corrupt_backup_is_rejected_before_restore(tmp_path):
    database = tmp_path / "legal.db"
    media = tmp_path / "media"
    media.mkdir()
    (media / "evidence.txt").write_text("original media", encoding="utf-8")
    create_database(database)
    backup_dir = create_backup(
        database_path=database,
        media_dir=media,
        backup_root=tmp_path / "backups",
        retention_days=14,
    )
    (backup_dir / "media.tar.gz").write_bytes(b"corrupt")

    with pytest.raises(BackupValidationError, match="校验失败"):
        restore_backup(
            backup_dir=backup_dir,
            database_path=database,
            media_dir=media,
            force=True,
        )

    assert read_database(database) == "original"
    assert (media / "evidence.txt").read_text(encoding="utf-8") == "original media"


def test_backup_retention_removes_expired_complete_backup(tmp_path):
    database = tmp_path / "legal.db"
    media = tmp_path / "media"
    media.mkdir()
    create_database(database)
    backup_root = tmp_path / "backups"
    old_backup = create_backup(
        database_path=database,
        media_dir=media,
        backup_root=backup_root,
        retention_days=30,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    old_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    (old_backup / "manifest.json").touch()
    import os

    os.utime(old_backup / "manifest.json", (old_timestamp, old_timestamp))

    create_backup(
        database_path=database,
        media_dir=media,
        backup_root=backup_root,
        retention_days=1,
        created_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )

    assert not old_backup.exists()
