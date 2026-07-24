from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import has_case_access, has_group_access
from app.db.session import get_db
from app.models.attribution_item import AttributionItem
from app.models.legal_event import LegalEvent
from app.models.payment_record import PaymentRecord
from app.schemas.workflow import (
    AttributionBatchDecision,
    AttributionListOut,
    AttributionOut,
    CaseGroupCreate,
    CaseGroupOut,
    CaseWorkspaceOut,
    ContactOut,
    EventDecision,
    GroupContactListOut,
    KDocsReconciliationListOut,
    KDocsReconciliationOut,
    PaymentCreate,
    PaymentListOut,
    PaymentOut,
    PaymentTrackingListOut,
    PaymentTrackingOut,
    PaymentUpdate,
)
from app.services.attribution_service import AttributionService
from app.services.case_group_service import CaseGroupService
from app.services.case_workspace_service import CaseWorkspaceService
from app.services.contact_service import ContactService
from app.services.kdocs_reconciliation_service import KDocsReconciliationService
from app.services.outbox_service import OutboxService
from app.services.payment_service import PaymentService
from app.services.payment_tracking_service import PaymentTrackingService
from app.utils.datetime_utils import now_tz

router = APIRouter(prefix="/legal", tags=["legal-workflow"])


@router.get("/cases/{case_id}/workspace")
def case_workspace(case_id: int, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该案件", code=403, status_code=403)
    try:
        return ok("案件工作台查询成功", CaseWorkspaceOut(**CaseWorkspaceService(db).get(case_id)))
    except ValueError as exc:
        raise_fail(str(exc), code=1404, status_code=404)


@router.post("/case-groups")
def bind_case_group(payload: CaseGroupCreate, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if not has_case_access(db, operator_info, payload.case_id) or not has_group_access(operator_info, payload.group_id):
        raise_fail("无权限访问案件或群", code=403, status_code=403)
    from app.models.legal_case import LegalCase

    legal_case = db.get(LegalCase, payload.case_id)
    if not legal_case:
        raise_fail("案件不存在", code=1404, status_code=404)
    binding = CaseGroupService(db).bind(legal_case, payload.group_id, str(operator_info["operator"]), primary=payload.is_primary)
    db.commit()
    return ok("案件群绑定成功", CaseGroupOut.model_validate(binding))


@router.delete("/case-groups/{binding_id}")
def unbind_case_group(binding_id: int, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    from app.models.case_group import CaseGroup

    binding = db.get(CaseGroup, binding_id)
    if not binding:
        raise_fail("案件群绑定不存在", code=1404, status_code=404)
    if not has_case_access(db, operator_info, binding.case_id):
        raise_fail("无权限访问该案件", code=403, status_code=403)
    try:
        binding = CaseGroupService(db).unbind(binding_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    return ok("案件群已解绑", CaseGroupOut.model_validate(binding))


@router.get("/attribution-queue")
def attribution_queue(status: str | None = "pending", group_id: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    total, items = AttributionService(db).list(
        status=status, group_id=group_id, offset=offset, limit=limit, auth_context=operator_info
    )
    return ok("待归属队列查询成功", AttributionListOut(total=total, items=[AttributionOut.model_validate(item) for item in items]))


@router.post("/attribution-queue/batch-confirm")
def decide_attribution(payload: AttributionBatchDecision, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    items = [db.get(AttributionItem, item_id) for item_id in payload.item_ids]
    if any(not item or not has_group_access(operator_info, item.group_id, item.tenant_id) for item in items):
        raise_fail("无权限访问部分待归属记录", code=403, status_code=403)
    try:
        if payload.decision == "confirm":
            if not has_case_access(db, operator_info, payload.case_id):
                raise_fail("无权限访问目标案件", code=403, status_code=403)
            result = AttributionService(db).batch_confirm(payload.item_ids, int(payload.case_id), str(operator_info["operator"]))
        else:
            result = {"rejected": AttributionService(db).batch_reject(payload.item_ids, str(operator_info["operator"]), payload.reason or "人工驳回")}
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    return ok("案件归属处理完成", result)


@router.get("/cases/{case_id}/payments")
def list_payments(case_id: int, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该案件", code=403, status_code=403)
    total, items = PaymentService(db).list_for_case(case_id, offset=offset, limit=limit)
    return ok("付款流水查询成功", PaymentListOut(total=total, items=[PaymentOut.model_validate(item) for item in items]))


@router.get("/payment-trackings")
def list_payment_trackings(
    status: str | None = Query(default=None, pattern="^(pending|partial|paid|overdue)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    from app.models.legal_case import LegalCase

    accessible_case_ids = [
        case_id
        for case_id in db.scalars(select(LegalCase.id)).all()
        if has_case_access(db, operator_info, case_id)
    ]
    total, items = PaymentTrackingService(db).list_rows(
        case_ids=accessible_case_ids,
        status=status,
        offset=offset,
        limit=limit,
    )
    return ok(
        "缴费信息跟踪查询成功",
        PaymentTrackingListOut(total=total, items=[PaymentTrackingOut(**item) for item in items]),
    )


@router.post("/cases/{case_id}/payments")
def create_payment(case_id: int, payload: PaymentCreate, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该案件", code=403, status_code=403)
    from app.models.legal_case import LegalCase

    legal_case = db.get(LegalCase, case_id)
    record, _created = PaymentService(db).create(
        legal_case,
        amount=payload.amount,
        payment_date=payload.payment_date,
        payer_name=payload.payer_name,
        status=payload.status,
        operator=str(operator_info["operator"]),
        note=payload.note,
    )
    db.commit()
    return ok("付款流水创建成功", PaymentOut.model_validate(record))


@router.patch("/cases/{case_id}/payments/{payment_id}")
def update_payment(case_id: int, payment_id: int, payload: PaymentUpdate, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该案件", code=403, status_code=403)
    record = db.get(PaymentRecord, payment_id)
    if not record or record.case_id != case_id:
        raise_fail("付款流水不存在", code=1404, status_code=404)
    service = PaymentService(db)
    try:
        result = service.approve(record, str(operator_info["operator"])) if payload.action == "approve" else service.reverse(record, str(operator_info["operator"]), payload.note or "")
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise_fail(str(exc), code=1400)
    return ok("付款流水更新成功", PaymentOut.model_validate(result))


def _event_for_action(event_id: int, db: Session, operator_info: dict[str, object]) -> LegalEvent:
    event = db.get(LegalEvent, event_id)
    if not event:
        raise_fail("事件不存在", code=1404, status_code=404)
    if event.case_id is None:
        raise_fail("事件案件归属未确认", code=1400)
    if not has_case_access(db, operator_info, event.case_id):
        raise_fail("无权限访问该事件", code=403, status_code=403)
    return event


@router.post("/events/{event_id}/approve")
def approve_event(event_id: int, payload: EventDecision, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    event = _event_for_action(event_id, db, operator_info)
    if not event.case_id or event.attribution_status != "confirmed":
        raise_fail("事件案件归属未确认", code=1400)
    event.business_status = "approved"
    event.approved_by = str(operator_info["operator"])
    event.approved_at = now_tz()
    OutboxService(db).enqueue_event(event.id, event.tenant_id)
    db.commit()
    return ok("事件已批准并进入业务队列", {"event_id": event.id})


@router.post("/events/{event_id}/reject")
def reject_event(event_id: int, payload: EventDecision, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    event = _event_for_action(event_id, db, operator_info)
    if not (payload.reason or "").strip():
        raise_fail("驳回必须填写原因", code=1400)
    event.business_status = "rejected"
    event.rejected_reason = payload.reason
    db.commit()
    return ok("事件已驳回", {"event_id": event.id})


@router.post("/events/{event_id}/replay")
def replay_event(event_id: int, payload: EventDecision, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    event = _event_for_action(event_id, db, operator_info)
    if event.business_status not in {"approved", "applied"}:
        raise_fail("仅已批准或已执行事件可以重放", code=1400)
    event.business_status = "approved"
    version = int(now_tz().timestamp())
    OutboxService(db).enqueue_event(event.id, event.tenant_id, version=version)
    db.commit()
    return ok("事件已进入重放队列", {"event_id": event.id})


@router.get("/groups/{group_id}/contacts")
def group_contacts(group_id: str, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if not has_group_access(operator_info, group_id):
        raise_fail("无权限访问该群", code=403, status_code=403)
    service = ContactService(db)
    service.sync_cached_members(group_id)
    try:
        room_id, source, warning, items = service.list_group(group_id)
    except ValueError as exc:
        raise_fail(str(exc), code=1404, status_code=404)
    db.commit()
    return ok("群联系人查询成功", GroupContactListOut(group_id=room_id, inventory_source=source, warning=warning, items=[ContactOut(**item) for item in items]))


@router.post("/kdocs/reconcile")
def reconcile_kdocs(case_id: int | None = None, db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if case_id is not None and not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该案件", code=403, status_code=403)
    result = KDocsReconciliationService(db).reconcile(case_id=case_id)
    db.commit()
    return ok("金山对账完成", result)


@router.get("/kdocs/reconciliation-results")
def reconciliation_results(status: str | None = None, case_id: int | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), operator_info: dict[str, object] = Depends(get_current_operator)):
    if case_id is not None and not has_case_access(db, operator_info, case_id):
        raise_fail("无权限访问该案件", code=403, status_code=403)
    total, items = KDocsReconciliationService(db).list(status=status, case_id=case_id, offset=offset, limit=limit)
    return ok("金山对账结果查询成功", KDocsReconciliationListOut(total=total, items=[KDocsReconciliationOut.model_validate(item) for item in items]))
