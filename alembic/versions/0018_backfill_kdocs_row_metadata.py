"""backfill KDocs row metadata from legacy response payloads

Revision ID: 0018_kdocs_row_metadata
Revises: 0017_business_workflow_refactor
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018_kdocs_row_metadata"
down_revision: Union[str, Sequence[str], None] = "0017_business_workflow_refactor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, response_payload_json FROM document_sync_logs "
            "WHERE outcome='applied' AND external_row_index IS NULL"
        )
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row.response_payload_json or "{}")
            file_id = str(payload.get("file_id") or "").strip()
            worksheet_id = payload.get("worksheet_id")
            row_index = int(payload["row_index"])
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if not file_id or worksheet_id is None or row_index < 0:
            continue
        connection.execute(
            sa.text(
                "UPDATE document_sync_logs SET external_doc_id=:file_id, "
                "external_sheet_name=:worksheet_id, external_row_index=:row_index, "
                "transport_mode='mcp' WHERE id=:id"
            ),
            {
                "id": row.id,
                "file_id": file_id[:128],
                "worksheet_id": str(worksheet_id)[:128],
                "row_index": row_index,
            },
        )


def downgrade() -> None:
    # Historical location metadata is valid after backfill and is intentionally retained.
    pass
