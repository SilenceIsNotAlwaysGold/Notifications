import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.kdocs import KDocsAdapter
from app.models.document_sync_log import DocumentSyncLog
from app.models.kdocs_reconciliation import KDocsReconciliation
from app.utils.datetime_utils import now_tz


class KDocsReconciliationService:
    TARGET_BY_SYNC_TYPE = {
        "status": "enforcement",
        "paid_amount": "enforcement",
        "case_snapshot": "enforcement",
        "enforcement_progress": "enforcement",
        "court_time": "court",
        "payment_registration": "payment",
    }

    def __init__(self, db: Session, adapter: KDocsAdapter | None = None) -> None:
        self.db = db
        self.adapter = adapter or KDocsAdapter()

    def reconcile(self, *, case_id: int | None = None, limit: int = 200) -> dict[str, int]:
        query = select(DocumentSyncLog).where(DocumentSyncLog.outcome == "applied", DocumentSyncLog.external_row_index.is_not(None))
        if case_id is not None:
            query = query.where(DocumentSyncLog.case_id == case_id)
        logs = list(self.db.scalars(query.order_by(DocumentSyncLog.id.desc()).limit(limit)).all())
        matched = drifted = unreadable = 0
        for log in logs:
            target = self.TARGET_BY_SYNC_TYPE.get(log.sync_type)
            if not target:
                continue
            response = self._json(log.response_payload_json)
            file_id = response.get("file_id")
            worksheet_id = response.get("worksheet_id")
            expected = self._json(log.request_payload_json).get("payload") or {}
            status = "unreadable"
            actual: dict = {}
            differences: dict = {}
            try:
                if not file_id or worksheet_id is None or log.external_row_index is None:
                    raise ValueError("同步日志缺少外部行定位信息")
                actual = self.adapter.read_row(target=target, file_id=str(file_id), worksheet_id=int(worksheet_id), row_index=log.external_row_index)
                if not actual.get("verified"):
                    differences = {"readback": "目标行为空或不可验证"}
                else:
                    expected_values = self.adapter.expected_row_values(target, expected)
                    actual_values = actual.get("values") or {}
                    for column, expected_value in enumerate(expected_values):
                        if expected_value is None or str(expected_value).strip() == "":
                            continue
                        actual_value = actual_values.get(str(column))
                        if self._normalize(actual_value) != self._normalize(expected_value):
                            differences[str(column)] = {
                                "expected": expected_value,
                                "actual": actual_value,
                            }
                status = "drifted" if differences else "matched"
            except Exception as exc:
                differences = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
            record = KDocsReconciliation(
                tenant_id=log.tenant_id,
                case_id=log.case_id,
                sync_log_id=log.id,
                target=target,
                external_row_index=log.external_row_index,
                status=status,
                expected_json=json.dumps(expected, ensure_ascii=False, default=str),
                actual_json=json.dumps(actual, ensure_ascii=False, default=str),
                differences_json=json.dumps(differences, ensure_ascii=False),
                checked_at=now_tz(),
            )
            self.db.add(record)
            matched += int(status == "matched")
            drifted += int(status == "drifted")
            unreadable += int(status == "unreadable")
        self.db.flush()
        return {"checked": len(logs), "matched": matched, "drifted": drifted, "unreadable": unreadable}

    def list(self, *, status: str | None = None, case_id: int | None = None, offset: int = 0, limit: int = 50) -> tuple[int, list[KDocsReconciliation]]:
        query = select(KDocsReconciliation)
        if status:
            query = query.where(KDocsReconciliation.status == status)
        if case_id is not None:
            query = query.where(KDocsReconciliation.case_id == case_id)
        total = int(self.db.scalar(select(func.count()).select_from(query.subquery())) or 0)
        items = list(self.db.scalars(query.order_by(KDocsReconciliation.id.desc()).offset(offset).limit(limit)).all())
        return total, items

    @staticmethod
    def _json(raw: str | None) -> dict:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}

    @staticmethod
    def _normalize(value: object) -> str:
        text = str(value if value is not None else "").strip()
        try:
            number = float(text.replace(",", ""))
            return f"{number:.8f}".rstrip("0").rstrip(".")
        except ValueError:
            return text
