"""
FreeApiAIProvider: an OPTIONAL AIProvider that calls an HTTP text-generation
API if (and only if) the user has configured one via environment variables
(which in GitHub Actions means GitHub Secrets). This satisfies the
"AIProvider abstraction must support swapping in a real provider later"
requirement without ever making one mandatory.

Configuration (all via env vars — never hardcoded):
- AI_API_URL:     full endpoint URL, OpenAI-chat-completions-compatible
                   (many free-tier providers, e.g. some OpenRouter models,
                   speak this format).
- AI_API_KEY:     bearer token. Some free endpoints don't require one —
                   in that case leave this unset and requests are sent
                   without an Authorization header.
- AI_API_MODEL:   model identifier string the endpoint expects.

If AI_API_URL is not set, is_available() returns False and
AIProviderRegistry falls through to RuleBasedAIProvider — the pipeline
never blocks on this provider being configured.

COST GUARD (Phase 3 requirement #10): every successful call is logged at
INFO level with the provider name and model, so usage is visible in
GitHub Actions logs. If the endpoint is a paid one, this is the only
place a paid API is ever touched, and it is always optional.
"""

from __future__ import annotations

import logging
import os
import time

import requests

from src.core.interfaces import AIProvider, AIRequest, AIResponse

logger = logging.getLogger(__name__)


class FreeApiAIProvider(AIProvider):
    name = "free_api"

    def __init__(self, timeout_seconds: int = 20, max_retries: int = 2):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._url = os.environ.get("AI_API_URL", "").strip()
        self._key = os.environ.get("AI_API_KEY", "").strip()
        self._model = os.environ.get("AI_API_MODEL", "").strip()

    def is_available(self) -> bool:
        return bool(self._url and self._model)

    def generate(self, request: AIRequest) -> AIResponse:
        if not self.is_available():
            return AIResponse(
                text="", provider_name=self.name, success=False,
                error="FreeApiAIProvider is not configured (AI_API_URL/AI_API_MODEL unset)",
            )

        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"

        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }

        last_error: str = "unknown error"
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(self._url, json=payload, headers=headers, timeout=self.timeout_seconds)
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                logger.info(
                    "FreeApiAIProvider call succeeded (model=%s, attempt=%d, prompt_chars=%d)",
                    self._model, attempt, len(request.prompt),
                )
                return AIResponse(text=text, provider_name=self.name, success=True)
            except requests.exceptions.Timeout:
                last_error = f"timeout after {self.timeout_seconds}s"
            except requests.exceptions.RequestException as e:
                last_error = str(e)
            except (KeyError, IndexError, ValueError) as e:
                last_error = f"unexpected response shape: {e}"

            if attempt < self.max_retries:
                time.sleep(2 ** attempt)  # exponential backoff

        logger.warning("FreeApiAIProvider failed after %d attempts: %s", self.max_retries, last_error)
        return AIResponse(text="", provider_name=self.name, success=False, error=last_error)
