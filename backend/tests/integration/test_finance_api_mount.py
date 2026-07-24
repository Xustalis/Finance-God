from fastapi.testclient import TestClient


def test_finance_api_is_available_under_fastapi(client: TestClient) -> None:
    response = client.get("/api/finance/live")

    assert response.status_code == 200
    assert response.json() == {"liveness": "live"}
