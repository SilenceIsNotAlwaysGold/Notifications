def test_batch_attribution_requires_target_case(client):
    response = client.post(
        "/api/v1/legal/attribution-queue/batch-confirm",
        json={"item_ids": [1], "decision": "confirm", "case_id": None},
    )

    assert response.status_code == 422
    assert "确认归属必须选择案件" in response.json()["message"]


def test_batch_attribution_rejection_requires_reason(client):
    response = client.post(
        "/api/v1/legal/attribution-queue/batch-confirm",
        json={"item_ids": [1], "decision": "reject", "reason": ""},
    )

    assert response.status_code == 422
    assert "驳回归属必须填写原因" in response.json()["message"]


def test_query_validation_names_invalid_parameter(client):
    response = client.get("/api/v1/legal/attribution-queue?limit=201")

    assert response.status_code == 422
    assert "limit" in response.json()["message"]
