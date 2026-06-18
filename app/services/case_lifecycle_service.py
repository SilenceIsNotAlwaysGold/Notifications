from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.resource_permissions import allowed_case_ids, allowed_group_ids, allowed_tenant_ids, resource_scope_enabled, tenant_scope_enabled
from app.models.legal_case import LegalCase
from app.services.case_service import CaseService
from app.services.document_sync_service import DocumentSyncService
from app.services.reminder_service import ReminderService
from app.services.system_run_log_service import SystemRunLogService
from app.services.tenant_settings_service import TenantSettingsService
from app.utils.datetime_utils import app_timezone, ensure_aware, now_tz


class CaseLifecycleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.reminder_service = ReminderService(db)
        self.case_service = CaseService(db)
        self.document_sync = DocumentSyncService(db)

    def scan_cases(
        self,
        today: date | None = None,
        trigger_type: str = "system",
        operator: str | None = None,
        auth_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        run_service = SystemRunLogService(self.db)
        run_log = run_service.start_run("case_status_scan", trigger_type, summary={"operator": operator} if operator else None)
        scan_date = today or now_tz().date()
        scoped = bool(auth_context and resource_scope_enabled(auth_context) and auth_context.get("role") != "admin")
        tenant_scoped = bool(auth_context and tenant_scope_enabled(auth_context) and allowed_tenant_ids(auth_context) and not (auth_context.get("role") == "admin" and not allowed_tenant_ids(auth_context)))
        scope_case_ids = allowed_case_ids(auth_context or {})
        scope_group_ids = allowed_group_ids(auth_context or {})
        scope_tenant_ids = allowed_tenant_ids(auth_context or {})
        stats = {
            "checked": 0,
            "created_repayment_reminders": 0,
            "marked_overdue": 0,
            "marked_defaulted": 0,
            "marked_paid": 0,
            "created_default_upgrade_reminders": 0,
            "synced_status": 0,
            "scoped": scoped,
            "allowed_group_count": len(scope_group_ids),
            "allowed_case_count": len(scope_case_ids),
            "allowed_tenant_count": len(scope_tenant_ids),
        }
        try:
            query = select(LegalCase).where(LegalCase.status != "closed").where(LegalCase.due_date.is_not(None))
            if tenant_scoped:
                query = query.where(or_(LegalCase.tenant_id.in_(scope_tenant_ids), LegalCase.tenant_id.is_(None)))
            if scoped and (scope_case_ids or scope_group_ids):
                filters = []
                if scope_case_ids:
                    filters.append(LegalCase.id.in_(scope_case_ids))
                if scope_group_ids:
                    filters.append(LegalCase.group_id.in_(scope_group_ids))
                query = query.where(or_(*filters))
            cases = list(self.db.scalars(query.order_by(LegalCase.id.asc())).all())
            for legal_case in cases:
                effective = TenantSettingsService(self.db).get_effective_settings(legal_case.tenant_id)
                if not effective["feature_flags"].get("enable_case_lifecycle_scan", True):
                    continue
                if not effective["reminder"].get("case_status_scan_enabled", True):
                    continue
                stats["checked"] += 1
                legal_case.last_status_checked_at = now_tz()
                if self.mark_paid_if_fully_paid(legal_case):
                    stats["marked_paid"] += 1
                    stats["synced_status"] += 1
                    continue

                if self.ensure_repayment_reminder(legal_case, scan_date, effective):
                    stats["created_repayment_reminders"] += 1
                if self.mark_overdue_if_needed(legal_case, scan_date):
                    stats["marked_overdue"] += 1
                    stats["synced_status"] += 1
                if self.mark_defaulted_if_needed(legal_case, scan_date, effective):
                    stats["marked_defaulted"] += 1
                    stats["synced_status"] += 1
                if self.ensure_default_upgrade_reminder(legal_case):
                    stats["created_default_upgrade_reminders"] += 1
            run_service.finish_success(
                run_log,
                summary={**stats, **({"operator": operator} if operator else {})},
                total_count=stats["checked"],
                success_count=stats["checked"],
                failed_count=0,
            )
            self.db.flush()
            return stats
        except Exception as exc:
            run_service.finish_failed(run_log, str(exc), summary={**stats, **({"operator": operator} if operator else {})})
            raise

    def ensure_repayment_reminder(self, legal_case: LegalCase, today: date | None = None, effective_settings: dict[str, object] | None = None) -> bool:
        scan_date = today or now_tz().date()
        effective = effective_settings or TenantSettingsService(self.db).get_effective_settings(legal_case.tenant_id)
        days_before = int(effective["reminder"].get("repayment_reminder_days_before") or self.settings.repayment_reminder_days_before)
        if legal_case.repayment_reminder_created_at is not None:
            return False
        if self._is_fully_paid(legal_case):
            return False
        if (legal_case.due_date - scan_date).days != days_before:
            return False
        self.reminder_service.create_repayment_reminder(legal_case.id, days_before)
        legal_case.repayment_reminder_created_at = now_tz()
        self.db.flush()
        return True

    def mark_paid_if_fully_paid(self, legal_case: LegalCase) -> bool:
        if legal_case.status in {"paid", "closed"}:
            return False
        if not self._is_fully_paid(legal_case):
            return False
        legal_case.paid_at = now_tz()
        self.case_service.update_status(legal_case, "paid", reason="fully_paid")
        self.db.flush()
        return True

    def mark_overdue_if_needed(self, legal_case: LegalCase, today: date | None = None) -> bool:
        scan_date = today or now_tz().date()
        if legal_case.status != "normal":
            return False
        if self._is_fully_paid(legal_case):
            return False
        if legal_case.due_date >= scan_date:
            return False
        legal_case.overdue_at = self._at_scan_date(scan_date)
        self.case_service.update_status(legal_case, "overdue", reason="overdue_scan")
        self.db.flush()
        return True

    def mark_defaulted_if_needed(self, legal_case: LegalCase, today: date | None = None, effective_settings: dict[str, object] | None = None) -> bool:
        scan_date = today or now_tz().date()
        effective = effective_settings or TenantSettingsService(self.db).get_effective_settings(legal_case.tenant_id)
        upgrade_days = int(effective["reminder"].get("default_upgrade_days_after_overdue") or self.settings.default_upgrade_days_after_overdue)
        if legal_case.status != "overdue":
            return False
        if legal_case.overdue_at is None:
            return False
        overdue_date = ensure_aware(legal_case.overdue_at).date()
        if (scan_date - overdue_date).days < upgrade_days:
            return False
        legal_case.defaulted_at = self._at_scan_date(scan_date)
        self.case_service.update_status(legal_case, "defaulted", reason="default_upgrade")
        self.db.flush()
        return True

    def ensure_default_upgrade_reminder(self, legal_case: LegalCase) -> bool:
        if legal_case.status != "defaulted":
            return False
        if legal_case.default_upgrade_reminder_created_at is not None:
            return False
        self.reminder_service.create_default_upgrade_reminder(legal_case.id)
        legal_case.default_upgrade_reminder_created_at = now_tz()
        self.db.flush()
        return True

    @staticmethod
    def _is_fully_paid(legal_case: LegalCase) -> bool:
        total_amount = legal_case.total_amount or Decimal("0.00")
        paid_amount = legal_case.paid_amount or Decimal("0.00")
        return total_amount > 0 and paid_amount >= total_amount

    @staticmethod
    def _at_scan_date(scan_date: date) -> datetime:
        now = now_tz()
        return datetime(scan_date.year, scan_date.month, scan_date.day, now.hour, now.minute, now.second, tzinfo=app_timezone())
