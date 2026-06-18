from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.schemas.legal import TenantCreate, TenantUpdate
from app.utils.datetime_utils import now_tz


class TenantService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_tenant(self, payload: TenantCreate) -> Tenant:
        tenant = Tenant(**payload.model_dump(exclude_unset=True), status="active")
        self.db.add(tenant)
        self.db.flush()
        return tenant

    def list_tenants(
        self,
        status: str | None = None,
        tenant_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[Tenant]]:
        query = select(Tenant)
        if status:
            query = query.where(Tenant.status == status)
        if tenant_id:
            query = query.where(Tenant.tenant_id == tenant_id)
        items = list(self.db.scalars(query.order_by(Tenant.id.desc())).all())
        start = (page - 1) * page_size
        return len(items), items[start : start + page_size]

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self.db.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))

    def update_tenant(self, tenant_id: str, payload: TenantUpdate) -> Tenant:
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            raise ValueError("租户不存在")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(tenant, field, value)
        tenant.updated_at = now_tz()
        self.db.flush()
        return tenant

    def disable_tenant(self, tenant_id: str) -> Tenant:
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            raise ValueError("租户不存在")
        tenant.status = "disabled"
        tenant.updated_at = now_tz()
        self.db.flush()
        return tenant

    def ensure_default_tenant(self) -> Tenant:
        tenant = self.get_tenant("tenant_default")
        if tenant:
            return tenant
        tenant = Tenant(tenant_id="tenant_default", tenant_name="默认租户", status="active")
        self.db.add(tenant)
        self.db.flush()
        return tenant
