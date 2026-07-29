import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.group_message import GroupMessage
from app.models.legal_event import LegalEvent
from app.models.media_file import MediaFile
from app.models.reminder import Reminder
from app.utils.datetime_utils import now_tz


class RepaymentTrackingService:
    """Keeps case-independent repayment agreements and receipts linked through legal events."""

    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def metadata(event: LegalEvent) -> dict[str, Any]:
        try:
            value = json.loads(event.metadata_json or "{}")
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def structured(result_or_metadata: dict[str, Any]) -> dict[str, Any]:
        metadata = result_or_metadata.get("metadata")
        if isinstance(metadata, dict):
            result_or_metadata = metadata
        fields = result_or_metadata.get("structured_fields")
        return fields if isinstance(fields, dict) else {}

    @classmethod
    def valid_plan(cls, result_or_metadata: dict[str, Any]) -> dict[str, Any] | None:
        plan = cls.structured(result_or_metadata).get("repayment_plan")
        if not isinstance(plan, dict) or not isinstance(plan.get("installments"), list):
            return None
        installments = [item for item in plan["installments"] if isinstance(item, dict) and item.get("due_date")]
        return {**plan, "installments": installments} if installments else None

    def find_agreement(
        self,
        *,
        group_id: str,
        creditor: str | None,
        debtor: str | None,
        before_event_id: int | None = None,
    ) -> LegalEvent | None:
        creditor_key = self._party_key(creditor)
        debtor_key = self._party_key(debtor)
        if not creditor_key or not debtor_key:
            return None
        query = (
            select(LegalEvent)
            .join(GroupMessage, GroupMessage.id == LegalEvent.group_message_id)
            .where(GroupMessage.group_id == group_id)
            .where(LegalEvent.event_type == "repayment_agreement")
            .where(LegalEvent.business_status.in_(("approved", "applied")))
            .order_by(LegalEvent.id.desc())
        )
        if before_event_id is not None:
            query = query.where(LegalEvent.id < before_event_id)
        matches: list[LegalEvent] = []
        for event in self.db.scalars(query.limit(100)).all():
            metadata = self.metadata(event)
            if self._party_key(metadata.get("plaintiff")) != creditor_key:
                continue
            if self._party_key(metadata.get("defendant")) != debtor_key:
                continue
            if self.valid_plan(metadata):
                matches.append(event)
        return matches[0] if matches else None

    def link_payment_result(self, media_file: MediaFile, result: dict[str, Any]) -> LegalEvent | None:
        metadata = result.get("metadata")
        if not isinstance(metadata, dict) or not metadata.get("repayment_annotation"):
            return None
        agreement = self.find_agreement(
            group_id=media_file.group_id,
            creditor=result.get("plaintiff"),
            debtor=result.get("defendant"),
        )
        if not agreement:
            return None
        metadata["repayment_agreement_event_id"] = agreement.id
        metadata["repayment_payment_fingerprint"] = self.payment_fingerprint(media_file, result, agreement.id)
        return agreement

    @staticmethod
    def payment_fingerprint(media_file: MediaFile, result: dict[str, Any], agreement_event_id: int) -> str:
        structured = RepaymentTrackingService.structured(result)
        if media_file.md5sum:
            raw = f"{agreement_event_id}|md5:{media_file.md5sum}"
        else:
            raw = "|".join(
                (
                    str(agreement_event_id),
                    media_file.msg_id or f"media:{media_file.id}",
                    str(result.get("amount") or ""),
                    str(structured.get("installment_sequence") or ""),
                )
            )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def progress(self, agreement: LegalEvent) -> dict[str, Any]:
        metadata = self.metadata(agreement)
        plan = self.valid_plan(metadata) or {"installments": []}
        installments = self._normalized_installments(plan.get("installments") or [])
        payment_events = list(
            self.db.scalars(
                select(LegalEvent)
                .where(LegalEvent.event_type == "payment_screenshot")
                .where(LegalEvent.business_status.in_(("approved", "applied")))
                .order_by(LegalEvent.id.asc())
            ).all()
        )
        payments: list[dict[str, Any]] = []
        fingerprints: set[str] = set()
        for event in payment_events:
            item = self.metadata(event)
            if item.get("repayment_agreement_event_id") != agreement.id:
                continue
            fingerprint = str(item.get("repayment_payment_fingerprint") or f"event:{event.id}")
            if fingerprint in fingerprints or event.amount is None:
                continue
            fingerprints.add(fingerprint)
            structured = item.get("structured_fields") if isinstance(item.get("structured_fields"), dict) else {}
            payments.append(
                {
                    "event_id": event.id,
                    "amount": Decimal(str(event.amount)),
                    "sequence": structured.get("installment_sequence"),
                    "payment_date": event.event_time.date() if event.event_time else event.created_at.date(),
                }
            )

        paid_by_sequence: dict[int, Decimal] = {}
        unallocated = Decimal("0.00")
        for payment in payments:
            try:
                sequence = int(payment["sequence"])
            except (TypeError, ValueError):
                sequence = 0
            if sequence > 0:
                paid_by_sequence[sequence] = paid_by_sequence.get(sequence, Decimal("0.00")) + payment["amount"]
            else:
                unallocated += payment["amount"]

        today = now_tz().date()
        details: list[dict[str, Any]] = []
        for item in installments:
            amount = item["amount"]
            paid = paid_by_sequence.get(item["sequence"], Decimal("0.00"))
            if paid < amount and unallocated > 0:
                allocated = min(amount - paid, unallocated)
                paid += allocated
                unallocated -= allocated
            if paid >= amount:
                status = "paid"
            elif item["due_date"] < today:
                status = "overdue"
            elif paid > 0:
                status = "partial"
            else:
                status = "pending"
            details.append({**item, "paid": paid, "status": status})

        total_debt = self._decimal(plan.get("total_debt")) or sum(
            (item["amount"] for item in installments), Decimal("0.00")
        )
        total_paid = sum((payment["amount"] for payment in payments), Decimal("0.00"))
        effective_paid = min(total_paid, total_debt) if total_debt > 0 else total_paid
        if total_debt > 0 and effective_paid >= total_debt:
            status = "completed"
        elif any(item["status"] == "overdue" for item in details):
            status = "defaulted"
        elif effective_paid > 0:
            status = "partial"
        else:
            status = "active"
        return {
            "agreement_event_id": agreement.id,
            "status": status,
            "total_debt": total_debt,
            "total_paid": effective_paid,
            "outstanding": max(Decimal("0.00"), total_debt - effective_paid),
            "installments": details,
            "payment_event_ids": [item["event_id"] for item in payments],
        }

    def cancel_satisfied_reminders(self, agreement: LegalEvent, progress: dict[str, Any]) -> int:
        paid_sequences = {
            int(item["sequence"])
            for item in progress.get("installments") or []
            if item.get("status") == "paid"
        }
        completed = progress.get("status") == "completed"
        reminders = list(
            self.db.scalars(
                select(Reminder)
                .where(Reminder.source_event_id == agreement.id)
                .where(Reminder.reminder_type == "installment_repayment")
                .where(Reminder.status == "pending")
            ).all()
        )
        cancelled = 0
        for reminder in reminders:
            sequence = self._sequence_from_dedupe(reminder.dedupe_key)
            if completed or sequence in paid_sequences:
                reminder.status = "cancelled"
                reminder.cancelled_at = now_tz()
                reminder.cancel_reason = "对应还款已确认"
                cancelled += 1
        self.db.flush()
        return cancelled

    @staticmethod
    def plan_text(plan: dict[str, Any]) -> str:
        total = RepaymentTrackingService._decimal(plan.get("total_debt"))
        lines = [f"双方确认合计欠款人民币：{total:.2f}元" if total is not None else "分期还款方案"]
        for item in RepaymentTrackingService._normalized_installments(plan.get("installments") or []):
            lines.append(f"{item['sequence']}. {item['due_date'].isoformat()}：还款{item['amount']:.2f}元")
        return "\n".join(lines)

    @staticmethod
    def progress_text(progress: dict[str, Any]) -> str:
        labels = {"paid": "已完成", "partial": "部分还款", "pending": "待还款", "overdue": "已逾期"}
        lines = []
        for item in progress.get("installments") or []:
            lines.append(
                f"第{item['sequence']}期 {item['due_date'].isoformat()} 应还{item['amount']:.2f}元，"
                f"已还{item['paid']:.2f}元，{labels.get(item['status'], item['status'])}"
            )
        return "\n".join(lines)

    @staticmethod
    def performance_status(progress: dict[str, Any]) -> str:
        return {
            "completed": "已履约",
            "defaulted": "已违约",
            "partial": "履约中",
            "active": "履约中",
        }.get(str(progress.get("status")), "履约情况待确认")

    @staticmethod
    def _normalized_installments(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(items, start=1):
            try:
                due_date = date.fromisoformat(str(item.get("due_date") or "")[:10])
                amount = Decimal(str(item.get("amount"))).quantize(Decimal("0.01"))
                sequence = int(item.get("sequence") or index)
            except (ValueError, TypeError, InvalidOperation):
                continue
            normalized.append({"sequence": sequence, "due_date": due_date, "amount": amount})
        return sorted(normalized, key=lambda item: (item["due_date"], item["sequence"]))

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        try:
            return Decimal(str(value)).quantize(Decimal("0.01")) if value is not None else None
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _party_key(value: Any) -> str:
        return "".join(str(value or "").split()).replace("（", "(").replace("）", ")").casefold()

    @staticmethod
    def _sequence_from_dedupe(value: str | None) -> int | None:
        if not value:
            return None
        parts = value.split(":")
        try:
            return int(parts[-2])
        except (ValueError, IndexError):
            return None
