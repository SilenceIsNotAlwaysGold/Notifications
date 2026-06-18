from datetime import datetime

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import AwareDateTime
from app.utils.datetime_utils import now_tz


class OperationAuditLog(Base):
    __tablename__ = "operation_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    operator: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    auth_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator_role: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    api_key_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    api_key_prefix: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(255), index=True)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(512), index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_scope_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_host: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(AwareDateTime, default=now_tz, index=True)
