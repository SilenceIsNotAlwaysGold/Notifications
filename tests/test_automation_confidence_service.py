from app.core.config import Settings
from app.services.automation_confidence_service import AutomationConfidenceService


def _service() -> AutomationConfidenceService:
    return AutomationConfidenceService(
        Settings(
            _env_file=None,
            LEGAL_AUTO_WRITE_MIN_CONFIDENCE=0.9,
            LEGAL_AUTO_REMIND_MIN_CONFIDENCE=0.85,
        )
    )


def test_complete_high_confidence_summons_can_write_automatically():
    decision = _service().evaluate(
        {
            "event_type": "court_notice",
            "document_type": "开庭传票",
            "plaintiff": "甲公司",
            "defendant": "张三",
            "court_time": "2026-08-03T09:30:00+08:00",
            "extraction_confidence": 0.94,
            "metadata": {"structured_fields": {"court_name": "测试人民法院"}},
        }
    )

    assert decision.should_auto_execute is True
    assert decision.action == "write"
    assert decision.confidence == 0.94


def test_high_confidence_with_missing_critical_field_still_requires_review():
    decision = _service().evaluate(
        {
            "event_type": "court_notice",
            "plaintiff": "甲公司",
            "court_time": "2026-08-03T09:30:00+08:00",
            "extraction_confidence": 0.99,
            "metadata": {"structured_fields": {"court_name": "测试人民法院"}},
        }
    )

    assert decision.should_auto_execute is False
    assert "缺少被告" in decision.reasons


def test_low_confidence_complete_judgment_requires_review():
    decision = _service().evaluate(
        {
            "event_type": "judgment",
            "document_type": "判决书",
            "plaintiff": "甲公司",
            "defendant": "张三",
            "amount": "1000",
            "extraction_confidence": 0.78,
            "metadata": {"structured_fields": {"court_name": "测试人民法院"}},
        }
    )

    assert decision.should_auto_execute is False
    assert any("低于自动写入阈值" in reason for reason in decision.reasons)


def test_clear_rule_based_payment_notice_can_create_reminders():
    decision = _service().evaluate(
        {
            "event_type": "payment_notice",
            "defendant": "李江胜",
            "amount": "25",
            "case_no": "（2026）桂0702民初5834号",
            "extracted_text": "李江胜，案件受理费25元，请缴费",
            "metadata": {
                "parser": "regex_v2",
                "structured_fields": {"payment_type": "案件受理费"},
            },
        },
        allow_rule_confidence=True,
    )

    assert decision.should_auto_execute is True
    assert decision.action == "remind"
    assert decision.confidence_source == "deterministic_rule"


def test_ambiguous_payment_notice_without_party_waits_for_review():
    decision = _service().evaluate(
        {
            "event_type": "payment_notice",
            "amount": "25",
            "extracted_text": "案件受理费25元，请缴费",
            "metadata": {"parser": "regex_v2", "structured_fields": {"payment_type": "案件受理费"}},
        },
        allow_rule_confidence=True,
    )

    assert decision.should_auto_execute is False
    assert "缺少缴费当事人" in decision.reasons


def test_complete_repayment_agreement_uses_write_threshold():
    decision = _service().evaluate(
        {
            "event_type": "repayment_agreement",
            "plaintiff": "甲公司",
            "defendant": "张三",
            "amount": "1000",
            "extraction_confidence": 0.96,
            "metadata": {
                "structured_fields": {
                    "repayment_plan": {
                        "installments": [
                            {"sequence": 1, "due_date": "2026-08-01", "amount": "500"},
                            {"sequence": 2, "due_date": "2026-09-01", "amount": "500"},
                        ]
                    }
                }
            },
        }
    )

    assert decision.should_auto_execute is True
