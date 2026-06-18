import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.system_run_log import SystemRunLog
from app.utils.datetime_utils import now_tz

logger = logging.getLogger(__name__)


class SystemRunLogService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def start_run(self, run_type: str, trigger_type: str, summary: dict[str, Any] | None = None) -> SystemRunLog:
        try:
            run_log = SystemRunLog(
                run_type=run_type,
                trigger_type=trigger_type,
                status="running",
                started_at=now_tz(),
                summary_json=json.dumps(summary or {}, ensure_ascii=False, default=str),
            )
            self.db.add(run_log)
            self.db.flush()
            return run_log
        except Exception:
            logger.exception("创建运行日志失败")
            raise

    def finish_success(
        self,
        run_log: SystemRunLog,
        summary: dict[str, Any] | None = None,
        total_count: int = 0,
        success_count: int = 0,
        failed_count: int = 0,
    ) -> None:
        self._finish(run_log, "success", summary, total_count, success_count, failed_count)

    def finish_failed(self, run_log: SystemRunLog, error_message: str, summary: dict[str, Any] | None = None) -> None:
        self._finish(run_log, "failed", summary, error_message=error_message)

    def finish_partial(
        self,
        run_log: SystemRunLog,
        summary: dict[str, Any] | None = None,
        total_count: int = 0,
        success_count: int = 0,
        failed_count: int = 0,
    ) -> None:
        self._finish(run_log, "partial", summary, total_count, success_count, failed_count)

    def list_run_logs(
        self,
        run_type: str | None = None,
        trigger_type: str | None = None,
        status: str | None = None,
        tenant_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[SystemRunLog]]:
        query = select(SystemRunLog)
        if run_type:
            query = query.where(SystemRunLog.run_type == run_type)
        if trigger_type:
            query = query.where(SystemRunLog.trigger_type == trigger_type)
        if status:
            query = query.where(SystemRunLog.status == status)
        if tenant_id:
            query = query.where(SystemRunLog.tenant_id == tenant_id)
        items = list(self.db.scalars(query.order_by(SystemRunLog.id.desc())).all())
        start = (page - 1) * page_size
        return len(items), items[start : start + page_size]

    def _finish(
        self,
        run_log: SystemRunLog,
        status: str,
        summary: dict[str, Any] | None = None,
        total_count: int = 0,
        success_count: int = 0,
        failed_count: int = 0,
        error_message: str | None = None,
    ) -> None:
        try:
            finished_at = now_tz()
            run_log.status = status
            run_log.finished_at = finished_at
            run_log.duration_ms = int((finished_at - run_log.started_at).total_seconds() * 1000)
            run_log.total_count = total_count
            run_log.success_count = success_count
            run_log.failed_count = failed_count
            run_log.summary_json = json.dumps(summary or {}, ensure_ascii=False, default=str)
            run_log.error_message = error_message
            self.db.flush()
        except Exception:
            logger.exception("更新运行日志失败 run_log_id=%s", getattr(run_log, "id", None))
