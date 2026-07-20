from fastapi import APIRouter, Depends

from app.api.deps_auth import get_current_operator
from app.api.v1 import (
    cases,
    api_keys,
    document_sync_logs,
    events,
    health,
    media_files,
    merchant_questions,
    messages,
    observability,
    ocr_reviews,
    operation_audit_logs,
    reminders,
    reminder_rules,
    system_alerts,
    tenants,
    tenant_settings,
    wecom_archive,
    wecom_poc,
)

api_router = APIRouter()
api_router.include_router(health.router)
legal_dependencies = [Depends(get_current_operator)]
api_router.include_router(cases.router, dependencies=legal_dependencies)
api_router.include_router(messages.router, dependencies=legal_dependencies)
api_router.include_router(reminders.router, dependencies=legal_dependencies)
api_router.include_router(reminder_rules.router, dependencies=legal_dependencies)
api_router.include_router(merchant_questions.router, dependencies=legal_dependencies)
api_router.include_router(system_alerts.router, dependencies=legal_dependencies)
api_router.include_router(events.router, dependencies=legal_dependencies)
api_router.include_router(wecom_archive.router, dependencies=legal_dependencies)
api_router.include_router(media_files.router, dependencies=legal_dependencies)
api_router.include_router(ocr_reviews.router, dependencies=legal_dependencies)
api_router.include_router(document_sync_logs.router, dependencies=legal_dependencies)
api_router.include_router(observability.router, dependencies=legal_dependencies)
api_router.include_router(operation_audit_logs.router, dependencies=legal_dependencies)
api_router.include_router(api_keys.router, dependencies=legal_dependencies)
api_router.include_router(tenants.router, dependencies=legal_dependencies)
api_router.include_router(tenant_settings.router, dependencies=legal_dependencies)
api_router.include_router(wecom_poc.router, dependencies=legal_dependencies)
