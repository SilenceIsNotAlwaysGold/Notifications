from app.services.kdocs_reconciliation_service import KDocsReconciliationService


def test_reconciliation_normalizes_boolean_display_values():
    normalize = KDocsReconciliationService._normalize

    assert normalize(False) == normalize("否") == normalize("no")
    assert normalize(True) == normalize("是") == normalize("yes")
