"""Unit tests for secure asynchronous Gemini client (Phase 0A).

All tests execute against local MockTransport fixtures.
Zero live external network requests are made.
Zero API keys or credentials are required or exposed.
"""

import asyncio
import json
import pytest
import httpx

from app.engine.gemini_client import (
    GeminiClient,
    GeminiClientError,
    GeminiErrorCode,
    SlidingWindowRateLimiter,
    sanitize_headers,
    sanitize_text,
    sanitize_url,
)
from app.engine.ai_provider import AIProvider


# ==============================================================================
# 1. Security & Redaction Unit Tests
# ==============================================================================

def test_sanitize_text_redacts_api_keys():
    """Verify Google API key patterns are scrubbed from text and logs."""
    raw_key = "AIzaSyD-fakeKeyExample1234567890abcdef"
    log_line = f"Connecting to upstream gateway with key {raw_key} at endpoint."
    sanitized = sanitize_text(log_line)
    assert raw_key not in sanitized
    assert "[REDACTED_API_KEY]" in sanitized


def test_sanitize_headers_redacts_sensitive_keys():
    """Verify sensitive HTTP header values are completely redacted."""
    headers = {
        "x-goog-api-key": "secret-api-key-value",
        "Authorization": "Bearer some-jwt-token",
        "Cookie": "session=sensitive-cookie",
        "Content-Type": "application/json",
        "User-Agent": "BrandShield-AI/1.0",
    }
    sanitized = sanitize_headers(headers)
    assert sanitized["x-goog-api-key"] == "[REDACTED]"
    assert sanitized["Authorization"] == "[REDACTED]"
    assert sanitized["Cookie"] == "[REDACTED]"
    assert sanitized["Content-Type"] == "application/json"
    assert sanitized["User-Agent"] == "BrandShield-AI/1.0"


def test_sanitize_url_scrubs_query_parameters():
    """Verify URL query parameters are scrubbed to prevent query credential leaks."""
    url_with_key = "https://generativelanguage.googleapis.com/v1beta/models?key=secret_in_url"
    sanitized = sanitize_url(url_with_key)
    assert "secret_in_url" not in sanitized
    assert "[REDACTED_QUERY]" in sanitized

    clean_url = "https://generativelanguage.googleapis.com/v1beta/models"
    assert sanitize_url(clean_url) == clean_url


# ==============================================================================
# 2. Header-Only Authentication & URL Routing Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_client_sends_x_goog_api_key_header_only():
    """Verify that requests use the x-goog-api-key header and never put keys in URL query."""
    captured_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={"displayName": "Verified Model", "supportedGenerationMethods": ["generateContent"]},
        )

    transport = httpx.MockTransport(mock_handler)
    client = GeminiClient(
        api_key="test-secure-key-12345",
        model_name="gemini-test-model",
        transport=transport,
    )

    result = await client.check_model_capabilities()
    assert result["accessible"] is True
    assert len(captured_requests) == 1

    req = captured_requests[0]
    # Header must be present
    assert req.headers.get("x-goog-api-key") == "test-secure-key-12345"
    # Query string must be completely empty (zero key in URL)
    assert "key=" not in str(req.url)
    assert req.url.query.decode("utf-8") == ""

    await client.aclose()


# ==============================================================================
# 3. Model Metadata Capability Probe Tests (Non-Fatal & Cached)
# ==============================================================================

@pytest.mark.asyncio
async def test_model_metadata_unconfigured_fails_safely():
    """Verify unconfigured client returns UNCONFIGURED status without raising or network call."""
    client = GeminiClient(api_key="", model_name="")
    result = await client.check_model_capabilities()
    assert result["accessible"] is False
    assert result["error_code"] == GeminiErrorCode.UNCONFIGURED.value
    await client.aclose()


@pytest.mark.asyncio
async def test_model_metadata_probe_handles_404_non_fatally():
    """Verify that a 404 from upstream model catalog returns safe error dict without raising."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": 404, "message": "models/unknown-model is not found", "status": "NOT_FOUND"}},
        )

    transport = httpx.MockTransport(mock_handler)
    client = GeminiClient(
        api_key="test-key",
        model_name="unknown-model",
        transport=transport,
    )

    result = await client.check_model_capabilities()
    assert result["accessible"] is False
    assert result["error_code"] == GeminiErrorCode.MODEL_NOT_FOUND.value
    assert "not found" in result["message"].lower()

    await client.aclose()


@pytest.mark.asyncio
async def test_model_metadata_probe_caches_result():
    """Verify that successful metadata checks are cached to prevent repeated requests."""
    call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={"displayName": "Cached Model", "supportedGenerationMethods": ["generateContent"]},
        )

    transport = httpx.MockTransport(mock_handler)
    client = GeminiClient(
        api_key="test-key",
        model_name="cached-model",
        transport=transport,
    )

    res1 = await client.check_model_capabilities()
    res2 = await client.check_model_capabilities()

    assert res1["accessible"] is True
    assert res2["accessible"] is True
    assert call_count == 1  # Second call must hit cache!

    await client.aclose()


# ==============================================================================
# 4. Error Classification Taxonomy Tests
# ==============================================================================

def test_classify_error_taxonomy():
    """Verify structured categorization across all required HTTP error codes."""
    # 401 Unauthorized
    code, msg, ra, retryable = GeminiClient.classify_error(
        401, {"error": {"message": "API key not valid", "status": "UNAUTHENTICATED"}}
    )
    assert code == GeminiErrorCode.AUTH_FAILED
    assert retryable is False

    # 403 Standard Permission Denied
    code, msg, ra, retryable = GeminiClient.classify_error(
        403, {"error": {"message": "Caller does not have permission", "status": "PERMISSION_DENIED"}}
    )
    assert code == GeminiErrorCode.PERMISSION_DENIED
    assert retryable is False

    # 403 Billing Restriction
    code, msg, ra, retryable = GeminiClient.classify_error(
        403, {"error": {"message": "Billing must be enabled for this project", "status": "PERMISSION_DENIED"}}
    )
    assert code == GeminiErrorCode.BILLING_RESTRICTION
    assert retryable is False

    # 404 Model Not Found
    code, msg, ra, retryable = GeminiClient.classify_error(
        404, {"error": {"message": "Model not found", "status": "NOT_FOUND"}}
    )
    assert code == GeminiErrorCode.MODEL_NOT_FOUND
    assert retryable is False

    # 429 Temporary Rate Limit (with Retry-After header)
    headers = httpx.Headers({"retry-after": "5"})
    code, msg, ra, retryable = GeminiClient.classify_error(
        429, {"error": {"message": "Rate limit exceeded", "status": "RESOURCE_EXHAUSTED"}}, headers=headers
    )
    assert code == GeminiErrorCode.RATE_LIMITED
    assert ra == 5.0
    assert retryable is True

    # 429 Daily Quota Exhaustion (Permanent for the day)
    code, msg, ra, retryable = GeminiClient.classify_error(
        429, {"error": {"message": "Quota exceeded for quota metric 'Requests per day'", "status": "RESOURCE_EXHAUSTED"}}
    )
    assert code == GeminiErrorCode.DAILY_QUOTA_EXHAUSTED
    assert retryable is False

    # 503 Service Unavailable
    code, msg, ra, retryable = GeminiClient.classify_error(
        503, {"error": {"message": "The service is temporarily overloaded", "status": "UNAVAILABLE"}}
    )
    assert code == GeminiErrorCode.SERVICE_UNAVAILABLE
    assert retryable is True


# ==============================================================================
# 5. Sliding-Window Rate Limiter & Concurrency Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_sliding_window_rate_limiter_enforces_rpm():
    """Verify rate limiter blocks when maximum requests per minute is exceeded."""
    # Test limiter with max 2 requests per window
    limiter = SlidingWindowRateLimiter(max_rpm=2, window_seconds=1.0)

    # First 2 acquires should succeed immediately
    await limiter.acquire(max_wait_budget=0.1)
    await limiter.acquire(max_wait_budget=0.1)

    # Third acquire should fail if budget is less than wait needed
    with pytest.raises(GeminiClientError) as exc_info:
        await limiter.acquire(max_wait_budget=0.01)

    assert exc_info.value.error_code == GeminiErrorCode.RATE_LIMITED


# ==============================================================================
# 6. Bounded Retries with Retry-After Header Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_generate_content_retries_transient_error_and_succeeds():
    """Verify that a transient 503 is retried after backoff and succeeds on attempt 2."""
    attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={"retry-after": "0.01"}, json={"error": {"message": "Backend busy"}})
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "Synthetic response"}]}}]},
        )

    transport = httpx.MockTransport(mock_handler)
    client = GeminiClient(
        api_key="test-key",
        model_name="test-model",
        max_retries=2,
        transport=transport,
    )

    result = await client.generate_content([{"parts": [{"text": "Test prompt"}]}])
    assert "candidates" in result
    assert attempts == 2

    await client.aclose()


@pytest.mark.asyncio
async def test_generate_content_does_not_retry_unrecoverable_errors():
    """Verify that unrecoverable 401, 404, or daily quota exhaustion are NEVER retried."""
    attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            401,
            json={"error": {"message": "API key invalid", "status": "UNAUTHENTICATED"}},
        )

    transport = httpx.MockTransport(mock_handler)
    client = GeminiClient(
        api_key="invalid-key",
        model_name="test-model",
        max_retries=2,
        transport=transport,
    )

    with pytest.raises(GeminiClientError) as exc_info:
        await client.generate_content([{"parts": [{"text": "Test"}]}])

    assert exc_info.value.error_code == GeminiErrorCode.AUTH_FAILED
    # Crucial security check: must NOT retry! Exactly 1 attempt made.
    assert attempts == 1

    await client.aclose()


@pytest.mark.asyncio
async def test_generate_content_does_not_retry_daily_quota_exhaustion():
    """Verify that daily quota exhaustion (429 RPD) fails fast with zero retries."""
    attempts = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            json={"error": {"message": "Resource exhausted: Requests per day exceeded", "status": "RESOURCE_EXHAUSTED"}},
        )

    transport = httpx.MockTransport(mock_handler)
    client = GeminiClient(
        api_key="test-key",
        model_name="test-model",
        max_retries=2,
        transport=transport,
    )

    with pytest.raises(GeminiClientError) as exc_info:
        await client.generate_content([{"parts": [{"text": "Test"}]}])

    assert exc_info.value.error_code == GeminiErrorCode.DAILY_QUOTA_EXHAUSTED
    assert attempts == 1  # ZERO retries on daily exhaustion

    await client.aclose()


# ==============================================================================
# 7. AIProvider Deterministic Fallback Integration Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_ai_provider_unconfigured_model_name_falls_back_cleanly():
    """Verify AIProvider cleanly falls back to deterministic mode when model name is empty."""
    provider = AIProvider()
    # Force empty model name
    provider.model_name = ""
    status = provider.get_provider_status()
    assert status["model_configured"] is False
    assert status["is_available"] is False

    result = await provider.evaluate_semantic_nuance("Sample draft", [])
    assert result["ai_available"] is False
    assert result["reasoning_applied"] is False
    assert "API key" in result["status_note"] or "configured" in result["status_note"]


@pytest.mark.asyncio
async def test_ai_provider_gracefully_degrades_on_gemini_client_error():
    """Verify AIProvider catches GeminiClientError and returns structured fallback without raising."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "Requests per day exceeded", "status": "RESOURCE_EXHAUSTED"}},
        )

    transport = httpx.MockTransport(mock_handler)
    mock_client = GeminiClient(
        api_key="test-key",
        model_name="test-model",
        transport=transport,
    )

    provider = AIProvider(client=mock_client)
    provider.gemini_key = "test-key"
    provider.model_name = "test-model"

    result = await provider.evaluate_semantic_nuance("Sample marketing copy", [])
    assert result["available"] is False
    assert result["ai_available"] is False
    assert result["error_code"] == GeminiErrorCode.DAILY_QUOTA_EXHAUSTED.value
    assert "Fallback to deterministic rules" in result["status_note"]

    await mock_client.aclose()


# ==============================================================================
# 8. In-Flight Concurrency Lease & Semaphore Safety Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrency_semaphore_limits_in_flight_to_one():
    """Prove that no more than one Gemini HTTP request is in-flight simultaneously."""
    active_in_flight = 0
    max_in_flight_seen = 0
    lock = asyncio.Lock()

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_in_flight, max_in_flight_seen
        async with lock:
            active_in_flight += 1
            if active_in_flight > max_in_flight_seen:
                max_in_flight_seen = active_in_flight

        # Simulate in-flight HTTP request duration
        await asyncio.sleep(0.03)

        async with lock:
            active_in_flight -= 1

        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "OK"}]}}]},
        )

    transport = httpx.MockTransport(mock_handler)
    # Set high max_rpm so sliding-window doesn't throttle, isolating the concurrency semaphore
    client = GeminiClient(
        api_key="test-key",
        model_name="test-model",
        max_rpm=60,
        transport=transport,
    )

    # Launch 4 simultaneous requests
    tasks = [
        client.generate_content([{"parts": [{"text": f"Prompt {i}"}]}])
        for i in range(4)
    ]
    results = await asyncio.gather(*tasks)

    assert len(results) == 4
    # The crucial concurrency invariant: at no point were > 1 requests in-flight simultaneously!
    assert max_in_flight_seen == 1
    assert active_in_flight == 0

    await client.aclose()


@pytest.mark.asyncio
async def test_semaphore_released_on_request_failure_and_timeout():
    """Prove semaphore is safely released even when request raises exception or times out."""
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Simulated read timeout")

    transport = httpx.MockTransport(timeout_handler)
    client = GeminiClient(
        api_key="test-key",
        model_name="test-model",
        max_retries=0,
        timeout_seconds=0.5,
        transport=transport,
    )

    with pytest.raises(GeminiClientError) as exc_info:
        await client.generate_content([{"parts": [{"text": "Test"}]}])

    assert exc_info.value.error_code == GeminiErrorCode.SERVICE_UNAVAILABLE

    # Critical check: semaphore must be 1 (unlocked/available), NOT 0 (locked)
    assert client.rate_limiter._semaphore._value == 1

    await client.aclose()
