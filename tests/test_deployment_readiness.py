from pathlib import Path

from app.core.config import get_settings
from app.core.config_validator import validate_runtime_config


ROOT = Path(__file__).resolve().parents[1]


def test_production_requires_wecomapi(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WECOM_SEND_MODE", "mock")
    get_settings.cache_clear()
    result = validate_runtime_config(get_settings())
    assert any("mock 发送仅允许" in message for message in result["errors"])


def test_complete_wecomapi_config_is_accepted(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WECOM_SEND_MODE", "wecomapi")
    monkeypatch.setenv("WECOMAPI_BASE_URL", "https://manager.wecomapi.com")
    monkeypatch.setenv("WECOMAPI_TOKEN", "test-token")
    monkeypatch.setenv("WECOMAPI_GUID", "test-guid")
    get_settings.cache_clear()
    result = validate_runtime_config(get_settings())
    assert not any("WECOM_SEND_MODE=wecomapi 时缺少配置" in message for message in result["errors"])


def test_health_and_admin_are_available(client):
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health/detail").status_code == 200
    assert client.get("/admin/").status_code == 200
    assert client.get("/admin/admin.js").status_code == 200


def test_admin_queries_cases_within_api_page_limit():
    content = (ROOT / "app/static/admin/admin.js").read_text(encoding="utf-8")

    assert '/api/v1/legal/cases?limit=200' not in content
    assert '/api/v1/legal/cases?limit=100' in content


def test_admin_sync_results_have_filters_sort_and_pagination():
    content = (ROOT / "app/static/admin/admin.js").read_text(encoding="utf-8")

    assert 'id="sync-filter-form"' in content
    assert 'option("desc", "最新优先"' in content
    assert 'query.set("status", state.syncStatus)' in content
    assert 'query.set("sync_type", state.syncType)' in content
    assert 'id="sync-prev"' in content
    assert 'id="sync-next"' in content
    assert 'data-sync-retry=' in content


def test_admin_kdocs_tables_have_generic_filters_sort_and_page_jump():
    content = (ROOT / "app/static/admin/admin.js").read_text(encoding="utf-8")

    assert 'id="kdocs-table-filter"' in content
    assert 'name="filter_column"' in content
    assert 'name="filter_value"' in content
    assert 'name="sort_column"' in content
    assert 'name="sort_order"' in content
    assert 'state.kdocsTarget === "court" ? state.kdocsSortOrder' not in content
    assert 'id="kdocs-page-jump"' in content
    assert 'id="kdocs-page-size"' in content


def test_unmapped_group_test_send_explains_required_mapping():
    content = (ROOT / "app/static/admin/admin.js").read_text(encoding="utf-8")

    assert 'data-send-mapped="${row.wecomapi_room_id ? "true" : "false"}"' in content
    assert "请先选择平台群 ID，并点击保存" in content
    assert 'row.wecomapi_room_id ? "" : "disabled"' not in content


def test_admin_separates_business_workflows_and_exposes_capture_only_groups():
    html = (ROOT / "app/static/admin/index.html").read_text(encoding="utf-8")
    script = (ROOT / "app/static/admin/admin.js").read_text(encoding="utf-8")

    for label in ("缴费跟踪", "法律文书", "还款管理", "沟通提醒", "金山台账", "系统管理"):
        assert label in html
    assert "诉讼与执行" not in html
    assert 'data-view="cases"' not in html
    assert '["capture_only", "仅采集"]' in script
    assert "不识别、不提醒、不写表" in script
    assert "/api/v1/legal/ocr-reviews/enforcement-documents" in script
    assert "/api/v1/legal/ocr-reviews/repayment-agreements" in script
    assert '{ view: "repayment-ledger", label: "协议履约" }' in script
    assert '{ view: "repayment-materials", label: "资料待办" }' in script
    assert "data-repayment-mode" not in script
    assert 'repayment: ["甲方（债权人）"' in script
    overview = script[script.index("async function renderOverview()") : script.index("function wecomApiStageLabel")]
    assert "待确认案件" not in overview


def test_repayment_views_are_decoupled_and_only_load_media_after_selection():
    script = (ROOT / "app/static/admin/admin.js").read_text(encoding="utf-8")
    detail = script[script.index("function repaymentAgreementDetail") : script.index("async function renderRepaymentLedger")]
    ledger_renderer = script[script.index("async function renderRepaymentLedger") : script.index("async function renderRepaymentMaterials")]
    inbox_renderer = script[script.index("async function renderRepaymentMaterials") : script.index("function bindRepaymentLedgerActions")]
    selector = script[script.index("async function selectRepaymentInboxItem") : script.index("function repaymentAgreementDetail")]
    reminder_panel = script[script.index("function repaymentReminderPanel") : script.index("function repaymentAgreementDetail")]
    reminder_actions = script[script.index("async function bindRepaymentReminderActions") : script.index("async function renderReminders")]

    assert "data-open-repayment-agreement" in detail
    assert "review-preview" not in detail
    assert "repayment-materials?" not in ledger_renderer
    assert "repayment-agreements?" not in inbox_renderer
    assert "loadReviewPreview" not in ledger_renderer
    assert "loadReviewPreview" not in inbox_renderer
    assert "await selectRepaymentInboxItem" not in inbox_renderer
    assert "await loadReviewPreview(selected)" in selector
    assert "立即催还款" in reminder_panel
    assert "data-repayment-reminder-target" in reminder_panel
    assert "data-repayment-reminder-confirm" in reminder_panel
    assert "/repayment-agreements/${agreement.event_id}/reminders" in reminder_actions
    assert "wecomapi-settings/group-members" in reminder_actions


def test_compose_contains_only_current_runtime_services():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for service in ("api:", "ocr-sidecar:", "archive-sidecar:", "migrate:", "backup:"):
        assert service in compose
    for legacy in ("wecom-bot:", "wecom-android:", "wecom-sender:", "wecom-protocol-gateway:"):
        assert legacy not in compose
    assert compose.count("ports:") == 1
    assert 'profiles: ["operations"]' in compose


def test_release_and_recovery_artifacts_exist():
    for relative in (
        "Dockerfile",
        "scripts/release_check.sh",
        "scripts/backup.py",
        "scripts/restore.py",
        "scripts/migration_preflight.py",
        "deploy/legal-wecom-backup.service",
        "deploy/legal-wecom-backup.timer",
        "docs/operations-refactor.md",
    ):
        assert (ROOT / relative).exists()

    backup_service = (ROOT / "deploy/legal-wecom-backup.service").read_text(encoding="utf-8")
    assert "EnvironmentFile=/opt/legal-wecom-automation/.env" in backup_service
    assert ".venv/bin/python /opt/legal-wecom-automation/scripts/backup.py" in backup_service
    assert "docker compose" not in backup_service


def test_legacy_sender_implementations_are_removed():
    for relative in (
        "android_sender_client",
        "wecom_sender_sidecar",
        "wecom_native_lab",
        "wecom_protocol_gateway",
        "wecom_bot_sidecar",
        "Dockerfile.protocol-gateway",
        "docker-compose.android.yml",
    ):
        assert not (ROOT / relative).exists(), relative


def test_gitignore_and_dockerignore_protect_runtime_secrets():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert ".env" in dockerignore
    assert "*.db" in gitignore
