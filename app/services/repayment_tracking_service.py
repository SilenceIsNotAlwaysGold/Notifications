import hashlib
import json
from collections import defaultdict
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
        raw_installments = plan["installments"]
        installments = cls._normalized_installments(raw_installments)
        sequences = [item["sequence"] for item in installments]
        if not installments or len(installments) != len(raw_installments) or len(sequences) != len(set(sequences)):
            return None
        return {
            **plan,
            "installment_count": len(installments),
            "installments": [
                {
                    "sequence": item["sequence"],
                    "due_date": item["due_date"].isoformat(),
                    "amount": item["amount"],
                }
                for item in installments
            ],
        }

    @classmethod
    def plan_total(cls, result_or_metadata: dict[str, Any]) -> Decimal | None:
        plan = cls.valid_plan(result_or_metadata)
        if not plan:
            return None
        return sum((Decimal(str(item["amount"])) for item in plan["installments"]), Decimal("0.00"))

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
        if not isinstance(metadata, dict):
            return None
        explicit_event_id = metadata.get("repayment_agreement_event_id")
        if not metadata.get("repayment_annotation") and not explicit_event_id:
            return None
        agreement = self.db.get(LegalEvent, int(explicit_event_id)) if explicit_event_id else None
        if explicit_event_id and agreement is None:
            raise ValueError("所选还款协议不存在")
        if agreement:
            if agreement.event_type != "repayment_agreement" or agreement.business_status not in {"approved", "applied"}:
                raise ValueError("所选还款协议尚未批准")
            agreement_group_id = agreement.group_message.group_id if agreement.group_message else None
            if agreement_group_id != media_file.group_id:
                raise ValueError("回款凭证只能关联同一群内的还款协议")
        else:
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

    def progress(
        self,
        agreement: LegalEvent,
        payment_events: list[LegalEvent] | None = None,
    ) -> dict[str, Any]:
        metadata = self.metadata(agreement)
        plan = self.valid_plan(metadata) or {"installments": []}
        installments = self._normalized_installments(plan.get("installments") or [])
        if payment_events is None:
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
                    "media_file_id": item.get("media_file_id"),
                }
            )

        valid_sequences = {item["sequence"] for item in installments}
        paid_by_sequence: dict[int, Decimal] = {}
        unallocated = Decimal("0.00")
        for payment in payments:
            try:
                sequence = int(payment["sequence"])
            except (TypeError, ValueError):
                sequence = 0
            if sequence in valid_sequences:
                paid_by_sequence[sequence] = paid_by_sequence.get(sequence, Decimal("0.00")) + payment["amount"]
            else:
                unallocated += payment["amount"]

        today = now_tz().date()
        details: list[dict[str, Any]] = []
        carry_forward = unallocated
        for item in installments:
            amount = item["amount"]
            available = paid_by_sequence.get(item["sequence"], Decimal("0.00")) + carry_forward
            paid = min(amount, available)
            carry_forward = max(Decimal("0.00"), available - amount)
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
        applied_paid = min(total_paid, total_debt) if total_debt > 0 else total_paid
        overpayment = max(Decimal("0.00"), total_paid - total_debt) if total_debt > 0 else Decimal("0.00")
        if total_debt > 0 and total_paid >= total_debt:
            status = "completed"
        elif any(item["status"] == "overdue" for item in details):
            status = "defaulted"
        elif total_paid > 0:
            status = "partial"
        else:
            status = "active"
        return {
            "agreement_event_id": agreement.id,
            "status": status,
            "total_debt": total_debt,
            "total_paid": total_paid,
            "applied_paid": applied_paid,
            "outstanding": max(Decimal("0.00"), total_debt - total_paid),
            "overpayment": overpayment,
            "installments": details,
            "payment_event_ids": [item["event_id"] for item in payments],
            "payments": payments,
        }

    def agreement_summaries(self) -> list[dict[str, Any]]:
        agreements = list(
            self.db.scalars(
                select(LegalEvent)
                .where(LegalEvent.event_type == "repayment_agreement")
                .where(LegalEvent.business_status.in_(("approved", "applied")))
                .order_by(LegalEvent.created_at.desc(), LegalEvent.id.desc())
            ).all()
        )
        if not agreements:
            return []
        agreement_ids = [item.id for item in agreements]
        payment_events = list(
            self.db.scalars(
                select(LegalEvent)
                .where(LegalEvent.event_type == "payment_screenshot")
                .where(LegalEvent.business_status.in_(("approved", "applied")))
                .order_by(LegalEvent.id.asc())
            ).all()
        )
        payments_by_agreement: dict[int, list[LegalEvent]] = defaultdict(list)
        agreement_id_set = set(agreement_ids)
        for payment_event in payment_events:
            payment_metadata = self.metadata(payment_event)
            raw_agreement_id = payment_metadata.get("repayment_agreement_event_id")
            try:
                agreement_id = int(raw_agreement_id)
            except (TypeError, ValueError):
                continue
            if agreement_id in agreement_id_set:
                payments_by_agreement[agreement_id].append(payment_event)
        media_by_event_id = {
            item.review_event_id: item
            for item in self.db.scalars(
                select(MediaFile).where(MediaFile.review_event_id.in_(agreement_ids))
            ).all()
            if item.review_event_id is not None
        }
        pending_reminders: dict[int, list[Reminder]] = {}
        for reminder in self.db.scalars(
            select(Reminder)
            .where(Reminder.source_event_id.in_(agreement_ids))
            .where(Reminder.reminder_type == "installment_repayment")
            .where(Reminder.status == "pending")
            .order_by(Reminder.remind_at.asc(), Reminder.id.asc())
        ).all():
            if reminder.source_event_id is not None:
                pending_reminders.setdefault(reminder.source_event_id, []).append(reminder)

        summaries: list[dict[str, Any]] = []
        for agreement in agreements:
            metadata = self.metadata(agreement)
            structured = metadata.get("structured_fields") if isinstance(metadata.get("structured_fields"), dict) else {}
            progress = self.progress(agreement, payments_by_agreement.get(agreement.id, []))
            open_installments = [
                item for item in progress["installments"] if item["status"] != "paid"
            ]
            next_installment = min(
                open_installments,
                key=lambda item: (item["due_date"], item["sequence"]),
                default=None,
            )
            reminders = pending_reminders.get(agreement.id, [])
            media_file = media_by_event_id.get(agreement.id)
            group_message = agreement.group_message
            summaries.append(
                {
                    "event_id": agreement.id,
                    "media_file_id": media_file.id if media_file else metadata.get("media_file_id"),
                    "tenant_id": agreement.tenant_id,
                    "group_id": group_message.group_id if group_message else "",
                    "creditor": str(metadata.get("plaintiff") or ""),
                    "debtor": str(metadata.get("defendant") or ""),
                    "original_filename": media_file.original_filename if media_file else None,
                    "mime_type": media_file.mime_type if media_file else None,
                    "progress": progress,
                    "next_due_date": next_installment["due_date"] if next_installment else None,
                    "next_due_amount": (
                        max(Decimal("0.00"), next_installment["amount"] - next_installment["paid"])
                        if next_installment
                        else None
                    ),
                    "overdue_count": sum(item["status"] == "overdue" for item in progress["installments"]),
                    "pending_reminder_count": len(reminders),
                    "next_remind_at": reminders[0].remind_at if reminders else None,
                    "arbitration_institution": structured.get("arbitration_institution"),
                    "arbitration_case_no": structured.get("arbitration_case_no"),
                    "created_at": agreement.created_at,
                }
            )
        return summaries

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
            if not isinstance(item, dict):
                continue
            try:
                due_date = date.fromisoformat(str(item.get("due_date") or "")[:10])
                amount = Decimal(str(item.get("amount"))).quantize(Decimal("0.01"))
                sequence = int(item.get("sequence") or index)
            except (ValueError, TypeError, InvalidOperation):
                continue
            if amount <= 0 or sequence < 1 or sequence > 100:
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
