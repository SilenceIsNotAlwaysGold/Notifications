import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.adapters.wecom_archive import WeComArchiveAdapter
from app.services.case_lifecycle_service import CaseLifecycleService
from app.services.merchant_question_service import MerchantQuestionService
from app.services.reminder_service import ReminderService
from app.services.system_alert_service import SystemAlertService
from app.services.outbox_service import OutboxService
from app.services.kdocs_reconciliation_service import KDocsReconciliationService
from app.services.data_retention_service import DataRetentionService

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone=get_settings().timezone)


def scan_due_reminders() -> None:
    db = SessionLocal()
    try:
        ReminderService(db).send_due_reminders(trigger_type="scheduler")
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("定时扫描提醒失败")
    finally:
        db.close()


def pull_wecom_archive_messages() -> None:
    db = SessionLocal()
    try:
        WeComArchiveAdapter().pull_and_process(db, trigger_type="scheduler")
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("定时拉取企业微信会话内容存档失败")
    finally:
        db.close()


def scan_case_statuses() -> None:
    db = SessionLocal()
    try:
        CaseLifecycleService(db).scan_cases(trigger_type="scheduler")
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("定时扫描案件状态失败")
    finally:
        db.close()


def scan_merchant_questions() -> None:
    db = SessionLocal()
    try:
        MerchantQuestionService(db).scan_timeouts()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("定时扫描商家提问超时失败")
    finally:
        db.close()


def scan_system_alerts() -> None:
    db = SessionLocal()
    try:
        SystemAlertService(db).scan()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("定时扫描系统告警失败")
    finally:
        db.close()


def process_business_outbox() -> None:
    db = SessionLocal()
    try:
        OutboxService(db).process_pending()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("业务 outbox 处理失败")
    finally:
        db.close()


def reconcile_kdocs() -> None:
    db = SessionLocal()
    try:
        KDocsReconciliationService(db).reconcile()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("金山文档每日对账失败")
    finally:
        db.close()


def apply_data_retention() -> None:
    db = SessionLocal()
    try:
        DataRetentionService(db).run()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("法律资料留存任务失败")
    finally:
        db.close()


def start_scheduler() -> None:
    settings = get_settings()
    if not settings.scheduler_enabled:
        logger.info("当前 APP_ENV=%s，不启动 APScheduler", settings.app_env)
        return
    if not scheduler.get_job("send_due_reminders"):
        scheduler.add_job(scan_due_reminders, "interval", minutes=1, id="send_due_reminders")
    if not scheduler.get_job("process_business_outbox"):
        scheduler.add_job(process_business_outbox, "interval", seconds=10, id="process_business_outbox", max_instances=1)
    if settings.kdocs_mode == "real" and not scheduler.get_job("reconcile_kdocs"):
        scheduler.add_job(reconcile_kdocs, "cron", hour=3, minute=15, id="reconcile_kdocs", max_instances=1)
    if settings.legal_data_retention_enabled and not scheduler.get_job("apply_data_retention"):
        scheduler.add_job(apply_data_retention, "cron", hour=4, minute=10, id="apply_data_retention", max_instances=1)
    if not scheduler.get_job("scan_merchant_questions"):
        scheduler.add_job(scan_merchant_questions, "interval", minutes=1, id="scan_merchant_questions")
    if settings.ops_alerts_enabled and not scheduler.get_job("scan_system_alerts"):
        scheduler.add_job(
            scan_system_alerts,
            "interval",
            minutes=settings.ops_scan_interval_minutes,
            id="scan_system_alerts",
        )
    if settings.wecom_archive_auto_pull and not scheduler.get_job("pull_wecom_archive_messages"):
        scheduler.add_job(pull_wecom_archive_messages, "interval", minutes=1, id="pull_wecom_archive_messages")
    if settings.case_status_scan_enabled and not scheduler.get_job("scan_case_statuses"):
        scheduler.add_job(
            scan_case_statuses,
            "cron",
            hour=settings.case_status_scan_hour,
            minute=settings.case_status_scan_minute,
            id="scan_case_statuses",
        )
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler 已启动")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
