import re
from dataclasses import dataclass

ROLES = {"admin", "legal", "auditor", "system"}


@dataclass(frozen=True)
class PermissionRule:
    method: str
    pattern: str

    def matches(self, method: str, path: str) -> bool:
        return self.method == method.upper() and re.fullmatch(self.pattern, path) is not None


ROLE_PERMISSIONS: dict[str, list[PermissionRule]] = {
    "legal": [
        PermissionRule("GET", r"/api/v1/legal/cases"),
        PermissionRule("GET", r"/api/v1/legal/cases/\d+"),
        PermissionRule("POST", r"/api/v1/legal/cases"),
        PermissionRule("PATCH", r"/api/v1/legal/cases/\d+"),
        PermissionRule("GET", r"/api/v1/legal/wecom-archive/groups"),
        PermissionRule("GET", r"/api/v1/legal/events"),
        PermissionRule("GET", r"/api/v1/legal/reminders"),
        PermissionRule("POST", r"/api/v1/legal/reminders/custom"),
        PermissionRule("GET", r"/api/v1/legal/media-files"),
        PermissionRule("POST", r"/api/v1/legal/media-files/\d+/ocr"),
        PermissionRule("GET", r"/api/v1/legal/media-files/\d+/content"),
        PermissionRule("GET", r"/api/v1/legal/ocr-reviews"),
        PermissionRule("GET", r"/api/v1/legal/ocr-reviews/\d+"),
        PermissionRule("POST", r"/api/v1/legal/ocr-reviews/\d+/decision"),
        PermissionRule("GET", r"/api/v1/legal/document-sync-logs"),
        PermissionRule("GET", r"/api/v1/legal/cases/\d+/status-histories"),
        PermissionRule("GET", r"/api/v1/legal/reminders/\d+/send-logs"),
    ],
    "auditor": [
        PermissionRule("GET", r"/api/v1/legal/cases"),
        PermissionRule("GET", r"/api/v1/legal/cases/\d+"),
        PermissionRule("GET", r"/api/v1/legal/tenants"),
        PermissionRule("GET", r"/api/v1/legal/tenants/[^/]+"),
        PermissionRule("GET", r"/api/v1/legal/tenants/[^/]+/settings"),
        PermissionRule("GET", r"/api/v1/legal/events"),
        PermissionRule("GET", r"/api/v1/legal/reminders"),
        PermissionRule("GET", r"/api/v1/legal/media-files"),
        PermissionRule("GET", r"/api/v1/legal/media-files/\d+/content"),
        PermissionRule("GET", r"/api/v1/legal/ocr-reviews"),
        PermissionRule("GET", r"/api/v1/legal/ocr-reviews/\d+"),
        PermissionRule("GET", r"/api/v1/legal/document-sync-logs"),
        PermissionRule("GET", r"/api/v1/legal/system-run-logs"),
        PermissionRule("GET", r"/api/v1/legal/operation-audit-logs"),
        PermissionRule("GET", r"/api/v1/legal/cases/\d+/status-histories"),
        PermissionRule("GET", r"/api/v1/legal/reminders/\d+/send-logs"),
    ],
    "system": [
        PermissionRule("POST", r"/api/v1/legal/reminders/run-due"),
        PermissionRule("POST", r"/api/v1/legal/cases/scan-status"),
        PermissionRule("POST", r"/api/v1/legal/wecom-archive/pull"),
        PermissionRule("POST", r"/api/v1/legal/messages/mock"),
        PermissionRule("POST", r"/api/v1/legal/media-files/\d+/ocr"),
        PermissionRule("POST", r"/api/v1/legal/document-sync-logs/\d+/retry"),
    ],
}


def has_permission(role: str, method: str, path: str) -> bool:
    if role == "admin":
        return path.startswith("/api/v1/legal/")
    return any(rule.matches(method, path) for rule in ROLE_PERMISSIONS.get(role, []))


def permission_names(role: str) -> list[str]:
    if role == "admin":
        return ["all"]
    return [f"{rule.method} {rule.pattern}" for rule in ROLE_PERMISSIONS.get(role, [])]
