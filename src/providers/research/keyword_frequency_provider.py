"""
KeywordFrequencyResearchProvider: fetches a single operator-configured
public webpage and counts occurrences of niche keywords in its visible
text, as a lightweight competition/differentiation signal proxy (e.g. "how
much is this niche already being talked about on a page the operator
trusts"). Same operator-configured-source pattern as RssFeedResearchProvider
— no hardcoded scraping target.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter

from bs4 import BeautifulSoup

from src.core.interfaces import ResearchSignal
from src.providers.research.base import BaseHttpResearchProvider

logger = logging.getLogger(__name__)


class KeywordFrequencyResearchProvider(BaseHttpResearchProvider):
    name = "keyword_frequency"

    def __init__(self, page_url: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.page_url = page_url if page_url is not None else os.environ.get("RESEARCH_PAGE_URL", "").strip()

    def is_available(self) -> bool:
        return bool(self.page_url)

    def _extract_signals(self, niche: str, subcategory_name: str) -> list[ResearchSignal]:
        if not self.page_url:
            return []

        resp = self._fetch(self.page_url)
        soup = BeautifulSoup(resp.content, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True).lower()

        words = re.findall(r"[a-z]+", text)
        word_counts = Counter(words)

        keywords = self._niche_keywords(subcategory_name)
        keyword_counts = {kw: word_counts.get(kw, 0) for kw in keywords}
        total_mentions = sum(keyword_counts.values())

        return [
            self._signal(
                niche, "competition_proxy",
                {
                    "page_url": self.page_url,
                    "total_words_scanned": len(words),
                    "keyword_counts": keyword_counts,
                    "total_keyword_mentions": total_mentions,
                },
            )
        ]

    def _niche_keywords(self, subcategory_name: str) -> list[str]:
        words = re.findall(r"[a-z]+", subcategory_name.lower())
        return [w for w in words if len(w) > 2]
