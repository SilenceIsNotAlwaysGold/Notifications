import json
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.business_outbox import BusinessOutbox
from app.utils.datetime_utils import now_tz


class OutboxService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def enqueue(self, *, task_type: str, aggregate_type: str, aggregate_id: int, tenant_id: str | None, payload: dict, dedupe_key: str) -> BusinessOutbox:
        existing = self.db.scalar(select(BusinessOutbox).where(BusinessOutbox.dedupe_key == dedupe_key))
        if existing:
            return existing
        task = BusinessOutbox(
            tenant_id=tenant_id,
            task_type=task_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            dedupe_key=dedupe_key,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            status="pending",
        )
        try:
            with self.db.begin_nested():
                self.db.add(task)
                self.db.flush()
        except IntegrityError:
            return self.db.scalar(select(BusinessOutbox).where(BusinessOutbox.dedupe_key == dedupe_key))
        return task

    def enqueue_event(self, event_id: int, tenant_id: str | None, *, version: int = 1) -> BusinessOutbox:
        return self.enqueue(
            task_type="apply_event",
            aggregate_type="legal_event",
            aggregate_id=event_id,
            tenant_id=tenant_id,
            payload={"event_id": event_id},
            dedupe_key=f"apply-event:{event_id}:v{version}",
        )

    def process_pending(self, limit: int = 50) -> dict[str, int]:
        tasks = list(self.db.scalars(select(BusinessOutbox).where(
            BusinessOutbox.status.in_(("pending", "retry")),
            BusinessOutbox.available_at <= now_tz(),
        ).order_by(BusinessOutbox.id.asc()).limit(limit)).all())
        completed = failed = 0
        for task in tasks:
            task.status = "processing"
            task.locked_at = now_tz()
            task.attempts += 1
            self.db.flush()
            try:
                # Keep database changes made by a failed handler out of the retry
                # transaction while retaining the outbox attempt metadata.
                with self.db.begin_nested():
                    self._dispatch(task)
                task.status = "completed"
                task.processed_at = now_tz()
                task.last_error = None
                completed += 1
            except Exception as exc:
                task.last_error = f"{type(exc).__name__}: {str(exc)[:500]}"
                if task.attempts >= 5:
                    task.status = "failed"
                    failed += 1
                else:
                    task.status = "retry"
                    task.available_at = now_tz() + timedelta(minutes=min(30, 2**task.attempts))
            self.db.flush()
        return {"processed": len(tasks), "completed": completed, "failed": failed}

    def _dispatch(self, task: BusinessOutbox) -> None:
        if task.task_type == "apply_event":
            from app.services.business_application_service import BusinessApplicationService

            BusinessApplicationService(self.db).apply_event(task.aggregate_id)
            return
        raise ValueError(f"不支持的 outbox 任务：{task.task_type}")
