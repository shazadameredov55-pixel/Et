"""
AIProviderRegistry: the single place that decides which concrete
AIProvider actually handles a request, based on
config/settings.yaml -> ai_provider.fallback_order.

Callers (self_critique.py, and later product_strategist.py) never
import a concrete provider directly — only this registry — so adding a
new provider later never touches business logic.
"""

from __future__ import annotations

import logging

from src.core.interfaces import AIProvider, AIRequest, AIResponse

logger = logging.getLogger(__name__)


class AIProviderRegistry:
    def __init__(self, providers: list[AIProvider]):
        if not providers:
            raise ValueError("AIProviderRegistry requires at least one provider")
        self._providers = providers

    @classmethod
    def default(cls) -> "AIProviderRegistry":
        """Build the standard registry: free/paid HTTP provider first (if
        configured), rule-based provider always last as the guaranteed
        fallback — never leaves the pipeline without a usable provider."""
        from src.providers.ai.free_api_provider import FreeApiAIProvider
        from src.providers.ai.rule_based_provider import RuleBasedAIProvider
        return cls([FreeApiAIProvider(), RuleBasedAIProvider()])

    def generate(self, request: AIRequest) -> AIResponse:
        last_response: AIResponse | None = None
        for provider in self._providers:
            if not provider.is_available():
                logger.debug("Skipping unavailable AI provider: %s", provider.name)
                continue
            response = provider.generate(request)
            if response.success:
                return response
            logger.warning("AI provider %s failed: %s", provider.name, response.error)
            last_response = response

        # Every configured provider either was unavailable or failed. This
        # should not normally happen since RuleBasedAIProvider is always
        # available and never raises, but we return the last real failure
        # rather than silently fabricating a success.
        return last_response or AIResponse(
            text="", provider_name="none", success=False,
            error="No AI provider was available",
        )
