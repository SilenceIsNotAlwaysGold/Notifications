import json
import logging
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.wecom_sender_status import WeComSenderStatusClient
from app.core.config import get_settings
from app.models.document_sync_log import DocumentSyncLog
from app.models.media_file import MediaFile
from app.models.system_alert import SystemAlert
from app.models.system_run_log import SystemRunLog
from app.utils.datetime_utils import ensure_aware, now_tz

logger = logging.getLogger(__name__)


class SystemAlertService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def list_alerts(
        self,
        *,
        status: str | None = None,
        alert_type: str | None = None,
        severity: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[int, list[SystemAlert]]:
        query = select(SystemAlert)
        if status:
            query = query.where(SystemAlert.status == status)
        if alert_type:
            query = query.where(SystemAlert.alert_type == alert_type)
        if severity:
            query = query.where(SystemAlert.severity == severity)
        items = list(
            self.db.scalars(
                query.order_by(SystemAlert.last_detected_at.desc(), SystemAlert.id.desc())
            ).all()
        )
        start = (page - 1) * page_size
        return len(items), items[start : start + page_size]

    def acknowledge(self, alert_id: int, operator: str) -> SystemAlert:
        alert = self.db.get(SystemAlert, alert_id)
        if not alert:
            raise ValueError("系统告警不存在")
        if alert.status == "resolved":
            return alert
        alert.status = "acknowledged"
        alert.acknowledged_at = now_tz()
        alert.acknowledged_by = operator
        self.db.flush()
        return alert

    def scan(self) -> dict[str, int]:
        checks = [
            self._archive_condition(),
            self._ocr_condition(),
            self._llm_condition(),
            self._kdocs_condition(),
            self._robot_condition(),
            self._sender_condition(),
            self._backup_condition(),
            self._disk_condition(),
        ]
        summary = {"checked": len(checks), "opened": 0, "resolved": 0, "active": 0}
        for condition in checks:
            transition, alert = self.reconcile_condition(**condition)
            if condition["active"]:
                summary["active"] += 1
            if transition == "opened":
                summary["opened"] += 1
                self._send_webhook(alert)
            elif transition == "resolved":
                summary["resolved"] += 1
        self.db.flush()
        return summary

    def reconcile_condition(
        self,
        *,
        dedupe_key: str,
        active: bool,
        alert_type: str,
        severity: str,
        source: str,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> tuple[str | None, SystemAlert | None]:
        alert = self.db.scalar(
            select(SystemAlert).where(SystemAlert.dedupe_key == dedupe_key)
        )
        now = now_tz()
        if active:
            transition = None
            if alert is None:
                alert = SystemAlert(
                    tenant_id=tenant_id,
                    alert_type=alert_type,
                    severity=severity,
                    source=source,
                    dedupe_key=dedupe_key,
                    status="open",
                    title=title,
                    message=message,
                    details_json=json.dumps(details or {}, ensure_ascii=False, default=str),
                    occurrence_count=1,
                    first_detected_at=now,
                    last_detected_at=now,
                )
                self.db.add(alert)
                transition = "opened"
            else:
                if alert.status == "resolved":
                    alert.status = "open"
                    alert.resolved_at = None
                    alert.acknowledged_at = None
                    alert.acknowledged_by = None
                    transition = "opened"
                alert.occurrence_count += 1
                alert.last_detected_at = now
                alert.alert_type = alert_type
                alert.severity = severity
                alert.source = source
                alert.title = title
                alert.message = message
                alert.details_json = json.dumps(details or {}, ensure_ascii=False, default=str)
            self.db.flush()
            return transition, alert

        if alert and alert.status != "resolved":
            alert.status = "resolved"
            alert.resolved_at = now
            alert.last_detected_at = now
            self.db.flush()
            return "resolved", alert
        return None, alert

    def _archive_condition(self) -> dict[str, Any]:
        enabled = self.settings.wecom_archive_mode == "real" and self.settings.wecom_archive_auto_pull
        latest = self.db.scalar(
            select(SystemRunLog)
            .where(SystemRunLog.run_type == "wecom_archive_pull")
            .order_by(SystemRunLog.id.desc())
        )
        stale_minutes = self.settings.ops_archive_stale_minutes
        active = False
        message = "企业微信归档拉取正常"
        details: dict[str, Any] = {"enabled": enabled, "stale_minutes": stale_minutes}
        if enabled:
            if latest is None:
                active = True
                message = "企业微信归档已启用，但尚无拉取运行记录"
            else:
                observed_at = latest.finished_at or latest.started_at
                age_minutes = (now_tz() - ensure_aware(observed_at)).total_seconds() / 60
                active = latest.status == "failed" or age_minutes > stale_minutes
                message = (
                    f"最近归档拉取状态为 {latest.status}，距今 {age_minutes:.1f} 分钟"
                    if active
                    else "企业微信归档拉取正常"
                )
                details.update({"last_run_id": latest.id, "last_status": latest.status, "age_minutes": round(age_minutes, 1)})
        return self._condition("archive_stalled", active, "critical", "wecom_archive", "企业微信归档停滞", message, details)

    def _ocr_condition(self) -> dict[str, Any]:
        threshold = self.settings.ops_failure_threshold
        latest = list(
            self.db.scalars(select(MediaFile).order_by(MediaFile.id.desc()).limit(threshold)).all()
        )
        active = len(latest) == threshold and all(item.ocr_status == "failed" for item in latest)
        return self._condition(
            "ocr_consecutive_failures",
            active,
            "critical",
            "ocr",
            "OCR 连续失败",
            f"最近 {threshold} 个媒体文件 OCR 均失败" if active else "OCR 未出现连续失败",
            {"threshold": threshold, "media_file_ids": [item.id for item in latest]},
        )

    def _llm_condition(self) -> dict[str, Any]:
        threshold = self.settings.ops_failure_threshold
        latest = list(
            self.db.scalars(
                select(MediaFile)
                .where(MediaFile.ocr_result_json.is_not(None))
                .order_by(MediaFile.id.desc())
                .limit(threshold)
            ).all()
        )
        llm_statuses = []
        for item in latest:
            try:
                result = json.loads(item.ocr_result_json or "{}")
            except ValueError:
                result = {}
            llm_statuses.append((result.get("metadata") or {}).get("llm_status") or result.get("llm_status"))
        enabled = self.settings.legal_extraction_mode == "llm"
        active = enabled and len(llm_statuses) == threshold and all(status in {"failed", "error", "fallback"} for status in llm_statuses)
        return self._condition(
            "llm_consecutive_failures",
            active,
            "warning",
            "legal_llm",
            "LLM 字段抽取连续失败",
            f"最近 {threshold} 次 LLM 字段抽取均失败" if active else "LLM 字段抽取未出现连续失败",
            {"enabled": enabled, "threshold": threshold, "statuses": llm_statuses},
        )

    def _kdocs_condition(self) -> dict[str, Any]:
        threshold = self.settings.ops_failure_threshold
        latest = list(
            self.db.scalars(
                select(DocumentSyncLog)
                .where(DocumentSyncLog.sync_target == "kdocs")
                .order_by(DocumentSyncLog.id.desc())
                .limit(threshold)
            ).all()
        )
        active = len(latest) == threshold and all(item.status == "failed" for item in latest)
        return self._condition(
            "kdocs_consecutive_failures",
            active,
            "critical",
            "kdocs",
            "金山文档同步连续失败",
            f"最近 {threshold} 次金山文档同步均失败" if active else "金山文档同步未出现连续失败",
            {"threshold": threshold, "sync_log_ids": [item.id for item in latest]},
        )

    def _robot_condition(self) -> dict[str, Any]:
        enabled = self.settings.wecom_send_mode == "wecom_bot"
        active = False
        message = "企业微信机器人未启用"
        details: dict[str, Any] = {"enabled": enabled}
        if enabled:
            if not self.settings.wecom_bot_sidecar_url:
                active = True
                message = "企业微信机器人 sidecar 地址未配置"
            else:
                try:
                    response = httpx.get(
                        urljoin(self.settings.wecom_bot_sidecar_url.rstrip("/") + "/", "health"),
                        timeout=min(self.settings.wecom_bot_timeout_seconds, 5),
                    )
                    payload = response.json()
                    active = response.status_code >= 400 or payload.get("ready") is False or payload.get("status") == "degraded"
                    message = "企业微信机器人未连接" if active else "企业微信机器人在线"
                    details.update({"status_code": response.status_code, "ready": payload.get("ready"), "status": payload.get("status")})
                except Exception as exc:
                    active = True
                    message = f"企业微信机器人健康检查失败：{exc}"
                    details["error_type"] = type(exc).__name__
        return self._condition("wecom_robot_offline", active, "critical", "wecom_bot", "企业微信机器人离线", message, details)

    def _sender_condition(self) -> dict[str, Any]:
        enabled = self.settings.wecom_send_mode == "wecomapi"
        result: dict[str, Any] = {
            "status": "disabled",
            "message": "Android 发送端未启用",
        }
        if enabled:
            result = WeComSenderStatusClient(
                base_url=self.settings.wecomapi_base_url,
                timeout_seconds=self.settings.wecom_timeout_seconds,
            ).check()
        active = enabled and result["status"] != "ok"
        details = {
            "enabled": enabled,
            **{
                key: result.get(key)
                for key in (
                    "status",
                    "backend",
                    "configured",
                    "online",
                    "connected_at",
                    "pending_commands",
                    "target_count",
                    "status_code",
                    "error_type",
                )
                if key in result
            },
        }
        return self._condition(
            "wecom_sender_offline",
            active,
            "critical" if result["status"] == "error" else "warning",
            "wecom_android_sender",
            "企业微信 Android 发送端不可用",
            result["message"] if active else "企业微信 Android 发送端在线",
            details,
        )

    def _backup_condition(self) -> dict[str, Any]:
        backup_dir = Path(self.settings.ops_backup_dir)
        manifests = sorted(backup_dir.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True) if backup_dir.exists() else []
        stale_hours = self.settings.ops_backup_stale_hours
        active = not manifests
        age_hours = None
        if manifests:
            age_hours = (now_tz().timestamp() - manifests[0].stat().st_mtime) / 3600
            active = age_hours > stale_hours
        message = "尚未发现有效备份" if not manifests else f"最近备份距今 {age_hours:.1f} 小时"
        return self._condition(
            "backup_stale",
            active,
            "warning",
            "backup",
            "备份过期",
            message if active else "备份时效正常",
            {"stale_hours": stale_hours, "age_hours": round(age_hours, 1) if age_hours is not None else None},
        )

    def _disk_condition(self) -> dict[str, Any]:
        path = Path(self.settings.media_storage_dir).resolve()
        probe = path if path.exists() else path.parent
        probe.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(probe)
        free_gb = usage.free / (1024**3)
        minimum_gb = self.settings.ops_disk_free_min_gb
        active = free_gb < minimum_gb
        return self._condition(
            "disk_space_low",
            active,
            "critical",
            "filesystem",
            "磁盘空间不足",
            f"可用磁盘空间 {free_gb:.2f} GB，阈值 {minimum_gb:.2f} GB" if active else "磁盘空间正常",
            {"free_gb": round(free_gb, 2), "minimum_gb": minimum_gb},
        )

    @staticmethod
    def _condition(
        alert_type: str,
        active: bool,
        severity: str,
        source: str,
        title: str,
        message: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "dedupe_key": f"system:{alert_type}",
            "active": active,
            "alert_type": alert_type,
            "severity": severity,
            "source": source,
            "title": title,
            "message": message,
            "details": details,
        }

    def _send_webhook(self, alert: SystemAlert | None) -> None:
        if not alert or not self.settings.ops_webhook_url:
            return
        try:
            httpx.post(
                self.settings.ops_webhook_url,
                json={
                    "event": "system_alert",
                    "id": alert.id,
                    "severity": alert.severity,
                    "type": alert.alert_type,
                    "title": alert.title,
                    "message": alert.message,
                    "detected_at": alert.last_detected_at.isoformat(),
                },
                timeout=5,
            )
        except Exception:
            logger.exception("系统告警 Webhook 发送失败 alert_id=%s", alert.id)
