from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.group_message import GroupMessage
from app.models.media_file import MediaFile
from app.models.wecom_archive_group import WeComArchiveGroup
from app.utils.repayment_annotation import parse_repayment_annotation


class GroupContextService:
    """Build a relevant, size-bounded conversation segment around a material."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def around_message(
        self,
        message_id: int | None,
        *,
        before_count: int = 40,
        after_count: int = 20,
        window_hours: int = 72,
        max_total_chars: int = 12000,
    ) -> list[dict[str, Any]]:
        if message_id is None:
            return []
        anchor = self.db.get(GroupMessage, message_id)
        if anchor is None:
            return []

        lower_bound = anchor.received_at - timedelta(hours=window_hours)
        upper_bound = anchor.received_at + timedelta(hours=window_hours)
        base_conditions = (
            GroupMessage.group_id == anchor.group_id,
            GroupMessage.received_at >= lower_bound,
            GroupMessage.received_at <= upper_bound,
        )
        before = list(
            self.db.scalars(
                select(GroupMessage)
                .where(*base_conditions)
                .where(
                    or_(
                        GroupMessage.received_at < anchor.received_at,
                        and_(GroupMessage.received_at == anchor.received_at, GroupMessage.id < anchor.id),
                    )
                )
                .order_by(GroupMessage.received_at.desc(), GroupMessage.id.desc())
                .limit(before_count)
            ).all()
        )
        after = list(
            self.db.scalars(
                select(GroupMessage)
                .where(*base_conditions)
                .where(
                    or_(
                        GroupMessage.received_at > anchor.received_at,
                        and_(GroupMessage.received_at == anchor.received_at, GroupMessage.id > anchor.id),
                    )
                )
                .order_by(GroupMessage.received_at.asc(), GroupMessage.id.asc())
                .limit(after_count)
            ).all()
        )
        messages = [*before, *after]
        media_by_message = self._media_by_message([item.id for item in messages])
        before_ids = {item.id for item in before}
        entries: list[dict[str, Any]] = []
        for message in messages:
            content = (message.content or "").strip()
            if not content:
                media = media_by_message.get(message.id)
                content = (media.extracted_text or "").strip() if media else ""
                if content:
                    content = f"[相邻{self._media_label(media.media_type)} OCR摘要] {content}"
            if not content:
                continue
            entries.append(
                {
                    "message_id": message.id,
                    "sender_id": message.sender_id,
                    "msg_type": message.msg_type,
                    "content": content[:2000],
                    "received_at": message.received_at.isoformat(),
                    "position": "before" if message.id in before_ids else "after",
                    "_distance": abs((message.received_at - anchor.received_at).total_seconds()),
                }
            )

        metadata = self._group_metadata(anchor)
        return self._fit_budget(metadata, entries, max_total_chars)

    def for_extraction(
        self,
        message_id: int | None,
        *,
        preferred_message_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return nearby evidence only; distant same-group cases must not influence extraction."""
        if preferred_message_id is not None:
            preferred = self._preferred_evidence(message_id, preferred_message_id)
            return preferred if preferred is not None else []
        context = self.around_message(
            message_id,
            before_count=12,
            after_count=12,
            window_hours=1,
            max_total_chars=6000,
        )
        nearby = [
            item
            for item in context
            if item.get("position") == "metadata" or float(item.get("distance_seconds") or 0) <= 30 * 60
        ]
        repayment = [
            item
            for item in nearby
            if item.get("position") != "metadata"
            and float(item.get("distance_seconds") or 0) <= 10 * 60
            and parse_repayment_annotation(str(item.get("content") or ""))
        ]
        if repayment:
            nearest_ids = {item.get("message_id") for item in sorted(repayment, key=self._context_distance)[:3]}
            nearby = [
                item
                for item in nearby
                if item.get("position") == "metadata" or item.get("message_id") in nearest_ids
            ]
        return nearby[:12]

    def _preferred_evidence(self, anchor_id: int | None, preferred_id: int) -> list[dict[str, Any]] | None:
        if anchor_id is None:
            return None
        anchor = self.db.get(GroupMessage, anchor_id)
        preferred = self.db.get(GroupMessage, preferred_id)
        if (
            anchor is None
            or preferred is None
            or preferred.group_id != anchor.group_id
            or preferred.msg_type != "text"
            or not parse_repayment_annotation(preferred.content)
        ):
            return None
        distance = abs((preferred.received_at - anchor.received_at).total_seconds())
        if distance > 10 * 60:
            return None
        position = "before" if (preferred.received_at, preferred.id) < (anchor.received_at, anchor.id) else "after"
        evidence = {
            "message_id": preferred.id,
            "sender_id": preferred.sender_id,
            "msg_type": preferred.msg_type,
            "content": (preferred.content or "")[:2000],
            "received_at": preferred.received_at.isoformat(),
            "position": position,
            "distance_seconds": round(distance, 3),
        }
        metadata = self._group_metadata(anchor)
        return [*([metadata] if metadata else []), evidence]

    def _media_by_message(self, message_ids: list[int]) -> dict[int, MediaFile]:
        if not message_ids:
            return {}
        media_files = self.db.scalars(
            select(MediaFile)
            .where(MediaFile.group_message_id.in_(message_ids))
            .where(MediaFile.extracted_text.is_not(None))
            .order_by(MediaFile.id.desc())
        ).all()
        result: dict[int, MediaFile] = {}
        for media in media_files:
            if media.group_message_id is not None:
                result.setdefault(media.group_message_id, media)
        return result

    def _group_metadata(self, anchor: GroupMessage) -> dict[str, Any] | None:
        group = self.db.scalar(
            select(WeComArchiveGroup).where(WeComArchiveGroup.room_id == anchor.group_id)
        )
        lines: list[str] = []
        if group and group.display_name:
            lines.append(f"群名称：{group.display_name}")
        if not lines:
            return None
        return {
            "message_id": None,
            "sender_id": "system:group-context",
            "msg_type": "group_metadata",
            "content": "\n".join(lines),
            "received_at": anchor.received_at.isoformat(),
            "position": "metadata",
        }

    @staticmethod
    def _fit_budget(
        metadata: dict[str, Any] | None,
        entries: list[dict[str, Any]],
        max_total_chars: int,
    ) -> list[dict[str, Any]]:
        remaining = max(1, max_total_chars)
        selected: list[dict[str, Any]] = []
        if metadata:
            metadata = dict(metadata)
            metadata["content"] = metadata["content"][:remaining]
            remaining -= len(metadata["content"])
            selected.append(metadata)
        for entry in sorted(entries, key=lambda item: (item["_distance"], item["received_at"], item["message_id"])):
            if remaining <= 0:
                break
            selected_entry = {key: value for key, value in entry.items() if key != "_distance"}
            selected_entry["distance_seconds"] = round(float(entry["_distance"]), 3)
            selected_entry["content"] = selected_entry["content"][:remaining]
            remaining -= len(selected_entry["content"])
            selected.append(selected_entry)
        metadata_entries = [item for item in selected if item["position"] == "metadata"]
        message_entries = sorted(
            (item for item in selected if item["position"] != "metadata"),
            key=lambda item: (item["received_at"], item["message_id"]),
        )
        return [*metadata_entries, *message_entries]

    @staticmethod
    def _context_distance(item: dict[str, Any]) -> tuple[float, int]:
        return float(item.get("distance_seconds") or 0), int(item.get("message_id") or 0)

    @staticmethod
    def _media_label(media_type: str) -> str:
        return {"image": "图片", "pdf": "PDF", "file": "文件"}.get(media_type, "附件")
