"""
NullResearchProvider: always available, always succeeds with an empty
signal list. Guarantees ResearchProviderRegistry never has zero usable
providers — if the operator hasn't configured any real source, research
still "completes" (with no signals) rather than blocking the pipeline.

ResearchProviderRegistry: aggregates across every configured provider,
tolerating individual failures — requirement (Phase 1 + Phase 3 #1): "not
dependent on a single site", and a provider outage must not abort the run.
"""

from __future__ import annotations

import logging

from src.core.interfaces import ResearchProvider, ResearchResult

logger = logging.getLogger(__name__)


class NullResearchProvider(ResearchProvider):
    name = "null"

    def is_available(self) -> bool:
        return True

    def research(self, niche: str, subcategory_name: str) -> ResearchResult:
        return ResearchResult(provider_name=self.name, niche=niche, signals=[], success=True)


class ResearchProviderRegistry:
    def __init__(self, providers: list[ResearchProvider]):
        if not providers:
            raise ValueError("ResearchProviderRegistry requires at least one provider")
        self._providers = providers

    @classmethod
    def default(cls) -> "ResearchProviderRegistry":
        from src.providers.research.rss_feed_provider import RssFeedResearchProvider
        from src.providers.research.keyword_frequency_provider import KeywordFrequencyResearchProvider
        return cls([RssFeedResearchProvider(), KeywordFrequencyResearchProvider(), NullResearchProvider()])

    def research_all(self, niche: str, subcategory_name: str) -> list[ResearchResult]:
        """Query every AVAILABLE provider (not just the first one) and
        return all results, successful or not — the opportunity scorer
        decides how to weigh partial data; a single provider outage never
        aborts the whole research pass."""
        results: list[ResearchResult] = []
        for provider in self._providers:
            if not provider.is_available():
                logger.debug("Skipping unavailable research provider: %s", provider.name)
                continue
            result = provider.research(niche, subcategory_name)
            if not result.success:
                logger.warning("Research provider %s failed for niche %s: %s", provider.name, niche, result.error)
            results.append(result)
        return results
