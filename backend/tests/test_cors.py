import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_application


def test_dev_cors_headers_allowed(client: TestClient) -> None:
    """Test that allowed development origin receives proper CORS response headers."""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_dev_cors_unauthorized_origin_rejected(client: TestClient) -> None:
    """Test that unauthorized origin does not receive Access-Control-Allow-Origin header."""
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://unauthorized-domain.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # When an origin is not allowed, Starlette CORSMiddleware omits the allow-origin header
    assert "access-control-allow-origin" not in response.headers


def test_cors_origins_comma_separated_parsing() -> None:
    """Test that comma-separated environment strings parse into clean list of origins."""
    s = Settings(BACKEND_CORS_ORIGINS="http://localhost:5173, http://127.0.0.1:3000")
    assert s.BACKEND_CORS_ORIGINS == [
        "http://localhost:5173",
        "http://127.0.0.1:3000",
    ]


def test_production_rejects_default_dev_origins() -> None:
    """Test that production environment refuses to run with default localhost origins."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(ENVIRONMENT="production")
    assert "BACKEND_CORS_ORIGINS must be explicitly configured" in str(exc_info.value)


def test_production_rejects_localhost_origin() -> None:
    """Test that production environment rejects explicit localhost/loopback origins."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            BACKEND_CORS_ORIGINS=["http://localhost:8080"],
        )
    assert "Insecure origin" in str(exc_info.value)


def test_production_rejects_insecure_http_scheme() -> None:
    """Test that production environment enforces HTTPS for configured origins."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            BACKEND_CORS_ORIGINS=["http://app.brandshield.ai"],
        )
    assert "Production origins must use HTTPS" in str(exc_info.value)


def test_production_rejects_default_jwt_secret() -> None:
    """Test that production environment rejects default insecure JWT secret key."""
    with pytest.raises(ValueError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            BACKEND_CORS_ORIGINS=["https://brandshield.ai"],
            JWT_SECRET_KEY="dev_secret_jwt_key_do_not_use_in_production_brandshield_ai_2026",
        )
    assert "JWT_SECRET_KEY must be overridden" in str(exc_info.value)


def test_production_valid_origins_and_restricted_methods() -> None:
    """Test that valid production config applies restricted methods and headers."""
    prod_settings = Settings(
        ENVIRONMENT="production",
        BACKEND_CORS_ORIGINS=["https://brandshield.ai", "https://app.brandshield.ai"],
        JWT_SECRET_KEY="production_secure_signing_key_brandshield_ai_2026",
        DATABASE_URL="postgresql+asyncpg://prod_user:StrongPassword987!@db.internal:5432/brandshield_ai",
    )
    assert prod_settings.BACKEND_CORS_ORIGINS == [
        "https://brandshield.ai",
        "https://app.brandshield.ai",
    ]
    assert prod_settings.cors_allow_methods == [
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ]
    assert "Authorization" in prod_settings.cors_allow_headers

    # Verify app behavior under production settings
    prod_app = create_application(app_settings=prod_settings)
    with TestClient(prod_app) as prod_client:
        response = prod_client.options(
            "/health",
            headers={
                "Origin": "https://brandshield.ai",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "https://brandshield.ai"
        assert response.headers.get("access-control-allow-credentials") == "true"


def test_production_rejects_insecure_default_database_url() -> None:
    """Test that production environment refuses to run with default postgres:postgres URL."""
    with pytest.raises(ValueError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            BACKEND_CORS_ORIGINS=["https://brandshield.ai"],
            JWT_SECRET_KEY="production_secure_signing_key_brandshield_ai_2026",
            DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/brandshield_ai",
        )
    assert "Insecure default or placeholder database credentials" in str(exc_info.value)


def test_production_rejects_sqlite_in_production() -> None:
    """Test that production environment refuses to run with SQLite database."""
    with pytest.raises(ValueError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            BACKEND_CORS_ORIGINS=["https://brandshield.ai"],
            JWT_SECRET_KEY="production_secure_signing_key_brandshield_ai_2026",
            DATABASE_URL="sqlite+aiosqlite:///brandshield_ai.db",
        )
    assert "SQLite DATABASE_URL is not permitted in production" in str(exc_info.value)


def test_production_rejects_short_jwt_secret() -> None:
    """Test that production environment enforces minimum 32 characters for JWT secret."""
    with pytest.raises(ValueError) as exc_info:
        Settings(
            ENVIRONMENT="production",
            BACKEND_CORS_ORIGINS=["https://brandshield.ai"],
            JWT_SECRET_KEY="short_key_under_32_chars",
            DATABASE_URL="postgresql+asyncpg://prod_user:StrongPassword987!@db.internal:5432/brandshield_ai",
        )
    assert "minimum 32 characters" in str(exc_info.value)
