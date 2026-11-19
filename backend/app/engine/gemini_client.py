"""Secure, resilient asynchronous Google Gemini API client.

Security & Architectural Invariants:
1. Header-only authentication via 'x-goog-api-key'. No API keys in URL query strings.
2. Sensitive headers, query strings, and exception tracebacks are strictly redacted from logs.
3. Configurable model identifier with NO hardcoded default.
4. Non-fatal model capability probe (metadata-only; zero automatic inference on startup).
5. Dual-layer rate limiting: asyncio.Semaphore(1) for concurrency + sliding-window token bucket for RPM.
6. Structured error classification for:
   - AUTH_FAILED
   - PERMISSION_DENIED
   - MODEL_NOT_FOUND
   - RATE_LIMITED (temporary)
   - DAILY_QUOTA_EXHAUSTED
   - BILLING_RESTRICTION
   - SERVICE_UNAVAILABLE
   - INVALID_REQUEST
   - UNCONFIGURED
7. Bounded retries respecting server-specified Retry-After headers without early retries.
8. Unrecoverable errors and known exhausted quotas are NEVER retried.
9. Fully testable via dependency-injected httpx.AsyncClient or MockTransport.
"""

from collections import deque
from contextlib import asynccontextmanager
from enum import Enum
import asyncio
import logging
import random
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union

import httpx

logger = logging.getLogger("brandshield.engine.gemini_client")

# Compiled regex for detecting Google API keys in strings to ensure zero leakage
API_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z-_]{30,45}")


def sanitize_text(text: Any) -> str:
    """Scrub sensitive credentials from text strings before logging."""
    if not text:
        return ""
    return API_KEY_PATTERN.sub("[REDACTED_API_KEY]", str(text))


def sanitize_headers(headers: Union[httpx.Headers, Dict[str, str]]) -> Dict[str, str]:
    """Return a sanitized copy of HTTP headers with sensitive tokens redacted."""
    sanitized: Dict[str, str] = {}
    sensitive_keys = {
        "x-goog-api-key",
        "authorization",
        "cookie",
        "set-cookie",
        "proxy-authorization",
    }
    for k, v in headers.items():
        if k.lower() in sensitive_keys:
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = sanitize_text(v)
    return sanitized


def sanitize_url(url: Union[str, httpx.URL]) -> str:
    """Scrub query parameters from URL strings before logging."""
    parsed = httpx.URL(url)
    if parsed.query:
        return str(parsed.copy_with(query=None)) + "?[REDACTED_QUERY]"
    return str(parsed)


class GeminiErrorCode(str, Enum):
    """Structured error taxonomy for Gemini API responses."""

    AUTH_FAILED = "AUTH_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    DAILY_QUOTA_EXHAUSTED = "DAILY_QUOTA_EXHAUSTED"
    BILLING_RESTRICTION = "BILLING_RESTRICTION"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNCONFIGURED = "UNCONFIGURED"
    UNKNOWN = "UNKNOWN"


class GeminiClientError(Exception):
    """Structured exception raised on unrecoverable Gemini API failures."""

    def __init__(
        self,
        message: str,
        error_code: GeminiErrorCode,
        status_code: Optional[int] = None,
        retry_after: Optional[float] = None,
        is_retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(sanitize_text(message))
        self.error_code = error_code
        self.status_code = status_code
        self.retry_after = retry_after
        self.is_retryable = is_retryable
        self.details = details or {}


class SlidingWindowRateLimiter:
    """In-process concurrency serializer and sliding-window RPM rate limiter.
    
    Guarantees:
    - Semaphore(1) serializes outbound requests, holding the lease for the entire
      duration of the outbound HTTP request.
    - Sliding window bounds completed requests within a 60-second rolling window.
    """

    def __init__(self, max_rpm: int = 5, window_seconds: float = 60.0) -> None:
        self.max_rpm = max(1, max_rpm)
        self.window_seconds = max(1.0, window_seconds)
        self._timestamps: deque[float] = deque()
        self._semaphore = asyncio.Semaphore(1)
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def lease(self, max_wait_budget: float = 15.0) -> AsyncGenerator[None, None]:
        """Acquire in-flight concurrency lease and hold semaphore for entire request duration."""
        await self._semaphore.acquire()
        try:
            async with self._lock:
                now = time.monotonic()
                # Purge timestamps outside the rolling window
                while self._timestamps and (now - self._timestamps[0]) > self.window_seconds:
                    self._timestamps.popleft()

                if len(self._timestamps) >= self.max_rpm:
                    wait_needed = self._timestamps[0] + self.window_seconds - now
                    if wait_needed > max_wait_budget:
                        raise GeminiClientError(
                            message=f"Rate limit wait of {wait_needed:.1f}s exceeds budget of {max_wait_budget:.1f}s",
                            error_code=GeminiErrorCode.RATE_LIMITED,
                            status_code=429,
                            retry_after=wait_needed,
                            is_retryable=True,
                        )
                    if wait_needed > 0:
                        logger.info("Sliding window saturated; throttling for %.2fs", wait_needed)
                        await asyncio.sleep(wait_needed)

                self._timestamps.append(time.monotonic())
            yield
        finally:
            self._semaphore.release()

    async def acquire(self, max_wait_budget: float = 15.0) -> None:
        """Convenience method for assertions on the rate limiter window."""
        async with self.lease(max_wait_budget=max_wait_budget):
            pass


class GeminiClient:
    """Secure, resilient asynchronous Gemini client using httpx.
    
    Guarantees:
    - x-goog-api-key header authentication exclusively.
    - Zero API key presence in URLs or query strings.
    - Non-fatal model capability probe with TTL caching.
    - No automatic inference executed at startup.
    - Bounded retries strictly respecting Retry-After.
    - Unrecoverable 429s (daily quotas) and auth/permission errors are never retried.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        base_url: str = "https://generativelanguage.googleapis.com",
        max_rpm: int = 5,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        client: Optional[httpx.AsyncClient] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.api_key = api_key or ""
        self.model_name = (model_name or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)
        self.rate_limiter = SlidingWindowRateLimiter(max_rpm=max_rpm)
        self._metadata_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

        # Allow injected client or transport for unit testing without live network calls
        self._injected_client = client
        self._injected_transport = transport
        self._owned_client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Provide or instantiate the underlying httpx client."""
        if self._injected_client is not None:
            return self._injected_client
        if self._owned_client is None:
            self._owned_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                transport=self._injected_transport,
            )
        return self._owned_client

    async def aclose(self) -> None:
        """Safely close owned HTTP resources."""
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None

    @staticmethod
    def classify_error(
        status_code: int,
        body: Optional[Dict[str, Any]],
        headers: Optional[httpx.Headers] = None,
    ) -> Tuple[GeminiErrorCode, str, Optional[float], bool]:
        """Classify HTTP responses into structured error taxonomy with retry guidance."""
        retry_after = None
        if headers:
            raw_ra = headers.get("retry-after")
            if raw_ra:
                try:
                    retry_after = max(0.0, float(raw_ra))
                except (ValueError, TypeError):
                    retry_after = None

        err_dict = (body or {}).get("error", {})
        message = err_dict.get("message", f"HTTP {status_code} error from Gemini API")
        msg_lower = message.lower()
        status_str = str(err_dict.get("status", "")).upper()
        details = err_dict.get("details", [])
        details_str = str(details).lower()

        # 401 Unauthorized
        if status_code == 401 or status_str == "UNAUTHENTICATED":
            return GeminiErrorCode.AUTH_FAILED, message, None, False

        # 403 Forbidden
        if status_code == 403 or status_str == "PERMISSION_DENIED":
            if "billing" in msg_lower or "billing" in details_str:
                return GeminiErrorCode.BILLING_RESTRICTION, message, None, False
            return GeminiErrorCode.PERMISSION_DENIED, message, None, False

        # 404 Not Found
        if status_code == 404 or status_str == "NOT_FOUND":
            return GeminiErrorCode.MODEL_NOT_FOUND, message, None, False

        # 429 Too Many Requests / Resource Exhausted
        if status_code == 429 or status_str == "RESOURCE_EXHAUSTED":
            # Detect daily quota exhaustion vs temporary short-term rate limit
            is_daily = (
                "daily" in msg_lower
                or "per day" in msg_lower
                or "perday" in details_str
                or "day" in details_str
                or any("quota" in str(d).lower() and "day" in str(d).lower() for d in details)
            )
            if is_daily:
                return GeminiErrorCode.DAILY_QUOTA_EXHAUSTED, message, None, False

            # Temporary short-term rate limit (recoverable with backoff)
            return GeminiErrorCode.RATE_LIMITED, message, retry_after, True

        # 400 Bad Request
        if status_code == 400 or status_str == "INVALID_ARGUMENT":
            if "billing" in msg_lower or "billing" in details_str:
                return GeminiErrorCode.BILLING_RESTRICTION, message, None, False
            return GeminiErrorCode.INVALID_REQUEST, message, None, False

        # 500, 502, 503, 504 Upstream Server Errors
        if status_code in (500, 502, 503, 504) or status_str == "UNAVAILABLE":
            return GeminiErrorCode.SERVICE_UNAVAILABLE, message, retry_after, True

        return GeminiErrorCode.UNKNOWN, message, retry_after, False

    async def check_model_capabilities(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        """Perform a passive, non-fatal model metadata check.
        
        Guarantees:
        - Metadata-only (GET /v1beta/models/{model}).
        - Zero inference performed. Zero token quota consumed.
        - Non-fatal: returns structured dictionary; never raises or blocks application boot.
        - Caches successful responses in-memory for 6 hours.
        """
        target_model = (model_name or self.model_name or "").strip()
        if not self.api_key or not target_model:
            return {
                "accessible": False,
                "model": target_model,
                "error_code": GeminiErrorCode.UNCONFIGURED.value,
                "message": "GEMINI_API_KEY or AI_MODEL_NAME is not configured.",
            }

        clean_model = target_model.replace("models/", "")
        cache_key = clean_model
        now = time.monotonic()

        # Check in-memory probe cache (6-hour TTL)
        if cache_key in self._metadata_cache:
            cached_time, cached_res = self._metadata_cache[cache_key]
            if (now - cached_time) < 21600.0:
                return cached_res

        url = f"{self.base_url}/v1beta/models/{clean_model}"
        headers = {
            "x-goog-api-key": self.api_key,
            "User-Agent": "BrandShield-AI/1.0",
        }

        try:
            client = self._get_client()
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                result = {
                    "accessible": True,
                    "model": clean_model,
                    "display_name": data.get("displayName", clean_model),
                    "supported_generation_methods": data.get("supportedGenerationMethods", []),
                    "input_token_limit": data.get("inputTokenLimit"),
                    "output_token_limit": data.get("outputTokenLimit"),
                    "description": data.get("description", ""),
                }
                self._metadata_cache[cache_key] = (now, result)
                logger.info("Successfully probed metadata for model: %s", clean_model)
                return result

            resp_data = None
            try:
                resp_data = resp.json()
            except Exception:
                pass
            err_code, err_msg, _, _ = self.classify_error(resp.status_code, resp_data, resp.headers)
            safe_res = {
                "accessible": False,
                "model": clean_model,
                "error_code": err_code.value,
                "status_code": resp.status_code,
                "message": sanitize_text(err_msg),
            }
            logger.warning(
                "Model metadata probe returned non-200 (%s): %s",
                err_code.value,
                safe_res["message"],
            )
            return safe_res

        except Exception as e:
            logger.warning("Model capability probe failed non-fatally: %s", sanitize_text(str(e)))
            return {
                "accessible": False,
                "model": clean_model,
                "error_code": GeminiErrorCode.SERVICE_UNAVAILABLE.value,
                "message": sanitize_text(str(e)),
            }

    async def generate_content(
        self,
        contents: List[Dict[str, Any]],
        generation_config: Optional[Dict[str, Any]] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute text or multimodal content generation with rate-limiting and bounded backoff.
        
        Guarantees:
        - Uses x-goog-api-key header exclusively.
        - Enforces rate-limiting via sliding-window lease.
        - Respects Retry-After headers strictly without retrying prematurely.
        - Unrecoverable errors (401, 403, 404, daily quota limits) fail fast without retrying.
        """
        target_model = (model_name or self.model_name or "").strip()
        if not self.api_key or not target_model:
            raise GeminiClientError(
                message="Cannot execute Gemini inference: GEMINI_API_KEY or AI_MODEL_NAME is not configured.",
                error_code=GeminiErrorCode.UNCONFIGURED,
            )

        clean_model = target_model.replace("models/", "")
        url = f"{self.base_url}/v1beta/models/{clean_model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "BrandShield-AI/1.0",
        }
        body: Dict[str, Any] = {"contents": contents}
        if generation_config:
            body["generationConfig"] = generation_config

        client = self._get_client()

        for attempt in range(self.max_retries + 1):
            should_retry = False
            backoff = 0.0

            try:
                # Hold the concurrency lease for the full duration of the HTTP post request
                async with self.rate_limiter.lease(max_wait_budget=self.timeout_seconds):
                    resp = await client.post(url, json=body, headers=headers)

                if resp.status_code == 200:
                    return resp.json()

                resp_data = None
                try:
                    resp_data = resp.json()
                except Exception:
                    pass

                err_code, err_msg, retry_after, is_retryable = self.classify_error(
                    resp.status_code, resp_data, resp.headers
                )

                # Abort immediately if non-retryable or retries exhausted
                if not is_retryable or attempt >= self.max_retries:
                    logger.warning(
                        "Gemini API request failed permanently (%s, HTTP %s): %s",
                        err_code.value,
                        resp.status_code,
                        sanitize_text(err_msg),
                    )
                    raise GeminiClientError(
                        message=err_msg,
                        error_code=err_code,
                        status_code=resp.status_code,
                        retry_after=retry_after,
                        is_retryable=is_retryable,
                        details=resp_data or {},
                    )

                # Determine backoff duration
                if retry_after is not None:
                    if retry_after > 15.0:  # Beyond maximum retry budget
                        raise GeminiClientError(
                            message=f"Upstream Retry-After of {retry_after:.1f}s exceeds retry budget",
                            error_code=err_code,
                            status_code=resp.status_code,
                            retry_after=retry_after,
                            is_retryable=False,
                        )
                    backoff = retry_after
                else:
                    backoff = min(8.0, 1.5 * (2 ** attempt)) * random.uniform(0.8, 1.2)

                logger.info(
                    "Transient Gemini error (%s, attempt %d/%d). Sleeping %.2fs before retry",
                    err_code.value,
                    attempt + 1,
                    self.max_retries,
                    backoff,
                )
                should_retry = True

            except httpx.TimeoutException as te:
                if attempt >= self.max_retries:
                    logger.warning(
                        "Gemini API timed out after %d attempts: %s",
                        attempt + 1,
                        sanitize_text(str(te)),
                    )
                    raise GeminiClientError(
                        message=f"Request timed out after {self.timeout_seconds}s",
                        error_code=GeminiErrorCode.SERVICE_UNAVAILABLE,
                        is_retryable=False,
                    )
                backoff = min(8.0, 1.5 * (2 ** attempt)) * random.uniform(0.8, 1.2)
                should_retry = True

            except GeminiClientError:
                raise

            except Exception as e:
                if attempt >= self.max_retries:
                    logger.error("Unexpected Gemini client error: %s", sanitize_text(str(e)))
                    raise GeminiClientError(
                        message=str(e),
                        error_code=GeminiErrorCode.SERVICE_UNAVAILABLE,
                        is_retryable=False,
                    )
                backoff = min(8.0, 1.5 * (2 ** attempt)) * random.uniform(0.8, 1.2)
                should_retry = True

            if should_retry:
                await asyncio.sleep(backoff)

        raise GeminiClientError(
            message="Exceeded maximum retries for Gemini API request",
            error_code=GeminiErrorCode.SERVICE_UNAVAILABLE,
            is_retryable=False,
        )
