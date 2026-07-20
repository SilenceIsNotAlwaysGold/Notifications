from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps_auth import get_current_operator
from app.api.v1.response import ok, raise_fail
from app.core.resource_permissions import filter_by_case_or_group, has_group_access
from app.db.session import get_db
from app.models.merchant_question import MerchantQuestion
from app.schemas.legal import MerchantQuestionClose, MerchantQuestionListOut, MerchantQuestionOut
from app.services.merchant_question_service import MerchantQuestionService

router = APIRouter(prefix="/legal/merchant-questions", tags=["legal-merchant-questions"])


@router.get("")
def list_merchant_questions(
    status: str | None = None,
    group_id: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    _total, items = MerchantQuestionService(db).list_questions(status=status, group_id=group_id, offset=offset, limit=limit)
    items = filter_by_case_or_group(db, items, operator_info)
    return ok(
        "商家提问查询成功",
        MerchantQuestionListOut(total=len(items), items=[MerchantQuestionOut.model_validate(item) for item in items]),
    )


@router.post("/{question_id}/close")
def close_merchant_question(
    question_id: int,
    payload: MerchantQuestionClose,
    db: Session = Depends(get_db),
    operator_info: dict[str, object] = Depends(get_current_operator),
):
    question = db.get(MerchantQuestion, question_id)
    if not question:
        raise_fail("商家提问不存在", code=1404, status_code=404)
    if not has_group_access(operator_info, question.group_id, question.tenant_id):
        raise_fail("无权限访问该资源", code=403, status_code=403)
    result = MerchantQuestionService(db).close_question(question_id, str(operator_info["operator"]), payload.reason)
    db.commit()
    return ok("商家提问已关闭", MerchantQuestionOut.model_validate(result))


@router.post("/scan-timeouts")
def scan_merchant_question_timeouts(db: Session = Depends(get_db)):
    result = MerchantQuestionService(db).scan_timeouts()
    db.commit()
    return ok("商家提问超时扫描完成", result)
