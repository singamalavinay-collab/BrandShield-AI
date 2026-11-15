from datetime import datetime
from fastapi.testclient import TestClient


def test_health_check_root(client: TestClient) -> None:
    """Test GET /health returns 200 and structured health schema."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "application/json" in response.headers.get("content-type", "")

    data = response.json()
    assert data["status"] == "healthy"
    assert data["app_name"] == "BrandShield AI Backend"
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data

    # Validate that timestamp is a valid ISO format string
    parsed_time = datetime.fromisoformat(data["timestamp"])
    assert parsed_time is not None


def test_health_check_v1(client: TestClient) -> None:
    """Test GET /api/v1/health returns 200 and matches expected structure."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["app_name"] == "BrandShield AI Backend"
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data


def test_root_discovery(client: TestClient) -> None:
    """Test GET / returns service status and discovery links."""
    response = client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert data["service"] == "BrandShield AI Backend"
    assert data["status"] == "operational"
    assert data["health_check"] == "/health"
    assert data["documentation"] == "/docs"


def test_not_found_returns_structured_error(client: TestClient) -> None:
    """Test that requesting an unknown path returns a structured 404 response."""
    response = client.get("/api/v1/unregistered-route-xyz")
    assert response.status_code == 404

    data = response.json()
    assert data["error"] is True
    assert data["status_code"] == 404
    assert "message" in data


def test_openapi_docs_availability(client: TestClient) -> None:
    """Test that OpenAPI schema is properly generated and exposes /health."""
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    assert "openapi" in schema
    assert "/health" in schema["paths"]
    assert "/api/v1/health" in schema["paths"]
