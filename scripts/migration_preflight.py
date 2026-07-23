import argparse
import json
import sqlite3
from pathlib import Path


TABLES = {
    "cases": "legal_cases",
    "messages": "group_messages",
    "media": "legal_media_files",
    "events": "legal_events",
    "sync_logs": "document_sync_logs",
}


def report(database: Path) -> dict:
    database = database.expanduser().resolve()
    if not database.is_file():
        raise SystemExit(f"数据库不存在: {database}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {
            label: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for label, table in TABLES.items()
            if table in existing
        }
        unassigned = {}
        if "legal_media_files" in existing:
            unassigned["media"] = connection.execute("SELECT COUNT(*) FROM legal_media_files WHERE case_id IS NULL").fetchone()[0]
        if "legal_events" in existing:
            unassigned["events"] = connection.execute("SELECT COUNT(*) FROM legal_events WHERE case_id IS NULL").fetchone()[0]
        revision = None
        if "alembic_version" in existing:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = row[0] if row else None
        return {
            "database": str(database),
            "integrity": integrity,
            "revision": revision,
            "counts": counts,
            "unassigned": unassigned,
            "ready": integrity == "ok",
            "read_only": True,
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移前只读检查")
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    result = report(args.database)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
