import logging
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings
from app.schemas.legal import MockMessageCreate
from app.services.message_service import MessageService
from app.services.system_run_log_service import SystemRunLogService
from app.services.wecom_archive_group_service import WeComArchiveGroupService
from app.utils.datetime_utils import app_timezone, ensure_aware
from app.utils.seq_store import SeqStore

logger = logging.getLogger(__name__)


class WeComArchiveAdapter:
    def __init__(self, mock_messages: list[dict[str, Any]] | None = None, seq_store: SeqStore | None = None) -> None:
        self.settings = get_settings()
        self.mock_messages = mock_messages or []
        self.seq_store = seq_store or SeqStore(self.settings.wecom_archive_seq_file)

    def fetch_messages(self, seq: int | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        if self.settings.wecom_archive_mode == "mock":
            max_limit = limit or self.settings.wecom_archive_limit
            start_seq = seq if seq is not None else 0
            return [message for message in self.mock_messages if int(message.get("seq", 0)) > start_seq][:max_limit]

        return self._fetch_messages_from_sidecar(seq=seq, limit=limit)

    def _fetch_messages_from_sidecar(self, seq: int | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.settings.wecom_archive_sidecar_url:
            raise RuntimeError("WECOM_ARCHIVE_MODE=real 时必须配置 WECOM_ARCHIVE_SIDECAR_URL")

        endpoint = urljoin(self.settings.wecom_archive_sidecar_url.rstrip("/") + "/", "messages")
        payload = {
            "seq": seq if seq is not None else 0,
            "limit": limit or self.settings.wecom_archive_limit,
            "corp_id": self.settings.wecom_corp_id,
            "archive_secret": self.settings.wecom_archive_secret,
            "private_key_path": self.settings.wecom_archive_private_key_path,
            "public_key_ver": self.settings.wecom_archive_public_key_ver,
        }
        response = httpx.post(endpoint, json=payload, timeout=self.settings.wecom_archive_timeout_seconds)
        response.raise_for_status()
        data = response.json()
        messages = data.get("messages") if isinstance(data, dict) else data
        if not isinstance(messages, list):
            raise RuntimeError("企业微信归档 sidecar 响应格式错误：缺少 messages 列表")
        return [message for message in messages if isinstance(message, dict)]

    def normalize_message(self, raw_message: dict[str, Any]) -> dict[str, Any]:
        msgtype = raw_message.get("msgtype") or "unknown"
        normalized_type = self._normalize_msg_type(msgtype, raw_message)
        content = self._normalize_content(msgtype, raw_message)
        return {
            "tenant_id": raw_message.get("tenant_id"),
            "group_id": raw_message.get("roomid") or raw_message.get("group_id") or "",
            "sender_id": raw_message.get("from") or raw_message.get("sender_id") or "",
            "msg_type": normalized_type,
            "content": content,
            "file_url": None,
            "raw_payload_json": raw_message,
            "received_at": self._normalize_received_at(raw_message.get("msgtime")),
        }

    def pull_and_process(self, db, trigger_type: str = "system", operator: str | None = None) -> dict[str, int]:
        run_service = SystemRunLogService(db)
        run_log = run_service.start_run("wecom_archive_pull", trigger_type, summary={"operator": operator} if operator else None)
        current_seq = self.seq_store.read()
        try:
            messages = self.fetch_messages(seq=current_seq, limit=self.settings.wecom_archive_limit)
            result = self.process_messages(
                db,
                messages,
                update_seq=True,
                initial_seq=current_seq,
                enforce_group_scope=self.settings.wecom_archive_mode == "real",
            )
            summary = {**result, **({"operator": operator} if operator else {})}
            status_method = run_service.finish_partial if result["failed"] else run_service.finish_success
            status_method(
                run_log,
                summary=summary,
                total_count=result["pulled"],
                success_count=result["processed"],
                failed_count=result["failed"],
            )
            return result
        except Exception as exc:
            run_service.finish_failed(run_log, str(exc), summary={"last_seq": current_seq, **({"operator": operator} if operator else {})})
            raise

    def replay_messages(self, db, messages: list[dict[str, Any]]) -> dict[str, int]:
        return self.process_messages(db, messages, update_seq=True, initial_seq=self.seq_store.read())

    def process_messages(
        self,
        db,
        messages: list[dict[str, Any]],
        update_seq: bool = True,
        initial_seq: int = 0,
        enforce_group_scope: bool = False,
    ) -> dict[str, int]:
        processed = 0
        failed = 0
        skipped = 0
        discovered = 0
        identified = 0
        last_seq = initial_seq
        message_service = MessageService(db)
        archive_group_service = WeComArchiveGroupService(db)
        for raw_message in messages:
            seq = int(raw_message.get("seq") or last_seq)
            try:
                message_to_process = raw_message
                if enforce_group_scope:
                    room_id = str(raw_message.get("roomid") or raw_message.get("group_id") or "").strip()
                    if not room_id:
                        skipped += 1
                        last_seq = max(last_seq, seq)
                        if update_seq:
                            self.seq_store.write(last_seq)
                        continue
                    seen_at = datetime.fromisoformat(self._normalize_received_at(raw_message.get("msgtime")))
                    archive_group, was_discovered = archive_group_service.discover_group(room_id, seen_at)
                    discovered += int(was_discovered)
                    identification_name = self._extract_group_identification_name(raw_message)
                    if identification_name:
                        identified += int(
                            archive_group_service.identify_group(archive_group, identification_name)
                        )
                        skipped += 1
                        last_seq = max(last_seq, seq)
                        if update_seq:
                            self.seq_store.write(last_seq)
                        continue
                    if archive_group.status != "enabled":
                        skipped += 1
                        last_seq = max(last_seq, seq)
                        if update_seq:
                            self.seq_store.write(last_seq)
                        continue
                    if archive_group.tenant_id and not raw_message.get("tenant_id"):
                        message_to_process = {**raw_message, "tenant_id": archive_group.tenant_id}

                payload = MockMessageCreate(**self.normalize_message(message_to_process))
                message_service.handle_incoming_message(payload)
                processed += 1
                last_seq = max(last_seq, seq)
                if update_seq:
                    self.seq_store.write(last_seq)
            except Exception:
                failed += 1
                logger.exception("处理企业微信归档消息失败 seq=%s", seq)
        return {
            "pulled": len(messages),
            "processed": processed,
            "failed": failed,
            "skipped": skipped,
            "discovered": discovered,
            "identified": identified,
            "last_seq": last_seq,
        }

    @staticmethod
    def _extract_group_identification_name(raw_message: dict[str, Any]) -> str | None:
        if raw_message.get("msgtype") != "text":
            return None
        content = str((raw_message.get("text") or {}).get("content") or "").strip()
        command = "#群名识别群"
        if not content.startswith(f"{command} "):
            return None
        display_name = " ".join(content[len(command) :].split())
        return display_name[:64] or None

    @staticmethod
    def _normalize_msg_type(msgtype: str, raw_message: dict[str, Any]) -> str:
        if msgtype == "text":
            return "text"
        if msgtype == "image":
            return "image"
        if msgtype == "file":
            filename = (raw_message.get("file") or {}).get("filename") or ""
            return "pdf" if filename.lower().endswith(".pdf") else "file"
        if msgtype == "link":
            return "link"
        return "unknown"

    @staticmethod
    def _normalize_content(msgtype: str, raw_message: dict[str, Any]) -> str | None:
        if msgtype == "text":
            return (raw_message.get("text") or {}).get("content")
        if msgtype == "link":
            link = raw_message.get("link") or {}
            parts = [link.get("title"), link.get("description"), link.get("link_url")]
            return "\n".join(part for part in parts if part)
        return None

    @staticmethod
    def _normalize_received_at(msgtime: Any) -> str:
        if msgtime is None:
            return ensure_aware(datetime.now()).isoformat()
        try:
            timestamp = int(msgtime)
        except (TypeError, ValueError):
            return ensure_aware(datetime.now()).isoformat()
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=app_timezone()).isoformat()
