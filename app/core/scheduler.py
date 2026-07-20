import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.adapters.wecom_archive import WeComArchiveAdapter
from app.services.case_lifecycle_service import CaseLifecycleService
from app.services.merchant_question_service import MerchantQuestionService
from app.services.reminder_service import ReminderService

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


def start_scheduler() -> None:
    settings = get_settings()
    if not settings.scheduler_enabled:
        logger.info("当前 APP_ENV=%s，不启动 APScheduler", settings.app_env)
        return
    if not scheduler.get_job("send_due_reminders"):
        scheduler.add_job(scan_due_reminders, "interval", minutes=1, id="send_due_reminders")
    if not scheduler.get_job("scan_merchant_questions"):
        scheduler.add_job(scan_merchant_questions, "interval", minutes=1, id="scan_merchant_questions")
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
