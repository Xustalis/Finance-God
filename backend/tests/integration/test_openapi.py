from fastapi.testclient import TestClient


def test_openapi_exposes_new_contract_and_hides_retired_routes(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    paths = document["paths"]

    assert "/api/v1/onboarding/sessions/{session_id}/messages" in paths
    assert "/api/v1/profiles/{profile_id}/direction-selection" in paths
    assert "/api/v1/admin/ai-settings" in paths
    assert "AITurnResult" in document["components"]["schemas"]
    assert not any(
        retired in path
        for path in paths
        for retired in ("/orders", "/target-portfolios", "/reviews", "/agents", "/risk-events")
    )
    for path, operations in paths.items():
        if not path.startswith("/api/v1/"):
            continue
        for operation in operations.values():
            success_schema = operation["responses"]["200" if "200" in operation["responses"] else "201"]["content"]["application/json"]["schema"]
            assert "$ref" in success_schema, f"{operation['operationId']} lacks a concrete response model"
            assert {"400", "401", "403", "404", "409", "422", "500", "502", "503"}.issubset(operation["responses"])

    schemas = document["components"]["schemas"]
    session_schema = schemas["SessionResponse"]
    profile_schema = schemas["ProfileResponse"]
    objective_schema = session_schema["properties"]["objective_profile"]
    objective_ref = next(item["$ref"] for item in objective_schema["anyOf"] if "$ref" in item)
    assert objective_ref.endswith("ObjectiveProfileInput")
    assert session_schema["properties"]["dimension_scores"]["$ref"].endswith("ConversationDimensionScores")
    assert session_schema["properties"]["profile_evidence"]["$ref"].endswith("ProfileEvidence")
    assert "current_question" in session_schema["properties"]
    assert "pending_profile_evidence" not in session_schema["properties"]
    assert "confirm_pending" not in schemas["MessageInput"]["properties"]
    ai_turn = schemas["AITurnResult"]
    assert {"next_question", "next_question_dimension", "retry_question"}.issubset(
        ai_turn["properties"]
    )
    assert "PendingProfileEvidence" not in schemas
    assert profile_schema["properties"]["dimension_scores"]["$ref"].endswith("ProfileDimensionScores")
    assert profile_schema["properties"]["report_summary"]["$ref"].endswith("ProfileReportSummary")
    error_code = schemas["ErrorCode"]
    assert set(error_code["enum"]) == {
        "VALIDATION_ERROR",
        "HTTP_400",
        "HTTP_401",
        "HTTP_403",
        "HTTP_404",
        "HTTP_409",
        "HTTP_500",
        "HTTP_502",
        "HTTP_503",
        "INTERNAL_ERROR",
    }
