import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.engine.gemini_client import GeminiClient, GeminiClientError, GeminiErrorCode

logger = logging.getLogger("brandshield.engine.ai_provider")


class AIProvider:
    """Manages external LLM provider connections for semantic reasoning.
    
    Guarantees:
    - Header-only authentication via 'x-goog-api-key'.
    - If no API key or model name is configured, never fabricates AI responses.
    - Accurately reports whether external AI semantic expansion is active.
    - Prevents leaking credentials in logs, diagnostics, or payloads.
    - Uses non-fatal model capability probes and lease-based rate limiting.
    """

    def __init__(self, client: Optional[GeminiClient] = None) -> None:
        self.gemini_key = settings.GEMINI_API_KEY
        self.openai_key = settings.OPENAI_API_KEY
        self.model_name = settings.AI_MODEL_NAME
        self._client = client

    @property
    def client(self) -> GeminiClient:
        """Lazy-instantiated Gemini client."""
        if self._client is None:
            self._client = GeminiClient(
                api_key=self.gemini_key,
                model_name=self.model_name,
                max_rpm=settings.GEMINI_MAX_RPM,
                timeout_seconds=settings.GEMINI_TIMEOUT_SECONDS,
                max_retries=settings.GEMINI_MAX_RETRIES,
            )
        return self._client

    @property
    def is_available(self) -> bool:
        """Indicate whether an external LLM is configured with credentials and model."""
        return bool((self.gemini_key and self.model_name) or self.openai_key)

    @property
    def provider_name(self) -> str:
        if self.gemini_key:
            return "google_gemini"
        if self.openai_key:
            return "openai"
        return "none_configured"

    def get_provider_status(self) -> Dict[str, Any]:
        """Return provider configuration status without revealing secrets."""
        return {
            "gemini_configured": bool(self.gemini_key),
            "openai_configured": bool(self.openai_key),
            "model_configured": bool(self.model_name),
            "is_available": self.is_available,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
        }

    async def check_capabilities(self) -> Dict[str, Any]:
        """Perform non-fatal model capability probe."""
        if not self.gemini_key or not self.model_name:
            return {
                "accessible": False,
                "model": self.model_name,
                "error_code": GeminiErrorCode.UNCONFIGURED.value,
                "message": "GEMINI_API_KEY or AI_MODEL_NAME is not configured.",
            }
        return await self.client.check_model_capabilities(self.model_name)

    async def evaluate_semantic_nuance(
        self,
        content: str,
        guidelines: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Optionally invoke LLM for complex semantic compliance evaluation.
        
        Returns real LLM analysis if API key and model are configured; otherwise
        returns honest status indicating that AI semantic reasoning is pending configuration.
        """
        if not self.is_available:
            reason = "External AI provider API key is not configured."
            if self.gemini_key and not self.model_name:
                reason = "External AI provider API key is present but AI_MODEL_NAME is not configured."

            return {
                "ai_available": False,
                "available": False,
                "reasoning_applied": False,
                "provider": self.provider_name,
                "status_note": (
                    f"{reason} Evaluation executed using deterministic brand rule engines."
                ),
                "message": (
                    f"{reason} Evaluation executed using deterministic brand rule engines."
                ),
                "semantic_violations": [],
            }

        # If a real Gemini key and model are configured:
        if self.gemini_key and self.model_name:
            try:
                logger.info(
                    "Executing external Gemini AI compliance evaluation using model %s",
                    self.model_name,
                )
                prompt = (
                    f"Evaluate the following marketing content against brand guidelines:\n\n"
                    f"Content: {content}\n\n"
                    f"Guidelines: {guidelines}"
                )
                contents = [{"parts": [{"text": prompt}]}]
                raw_response = await self.client.generate_content(contents)
                return {
                    "available": True,
                    "provider": "google_gemini",
                    "model": self.model_name,
                    "raw_response": raw_response,
                    "semantic_violations": [],
                }
            except GeminiClientError as gce:
                logger.warning("AI Provider invocation failed safely (%s): %s", gce.error_code.value, str(gce))
                return {
                    "available": False,
                    "ai_available": False,
                    "error": str(gce),
                    "error_code": gce.error_code.value,
                    "is_retryable": gce.is_retryable,
                    "semantic_violations": [],
                    "status_note": f"Gemini evaluation unavailable ({gce.error_code.value}). Fallback to deterministic rules.",
                }
            except Exception as e:
                logger.error("AI Provider unexpected failure: %s", str(e))
                return {
                    "available": False,
                    "ai_available": False,
                    "error": str(e),
                    "semantic_violations": [],
                    "status_note": "Gemini evaluation unexpected error. Fallback to deterministic rules.",
                }

        return {
            "available": False,
            "provider": self.provider_name,
            "semantic_violations": [],
        }


# Global singleton instance
ai_provider = AIProvider()
