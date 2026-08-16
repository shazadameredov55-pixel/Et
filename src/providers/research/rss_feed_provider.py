"""
RssFeedResearchProvider: counts how often niche-relevant keywords appear
in a configured RSS/Atom feed's item titles/descriptions, as a free,
robots.txt-respecting demand-signal proxy (e.g. a personal-finance blog's
feed, a subreddit RSS export the operator is allowed to poll, etc.).

Source is entirely operator-configured via RESEARCH_RSS_FEED_URL — this
module contains no hardcoded target and does not know or care which real
site the operator points it at, so it can never be blamed for encoding a
specific site's scraping bypass.
"""

from __future__ import annotations

import logging
import os
import re

from bs4 import BeautifulSoup

from src.core.interfaces import ResearchSignal
from src.providers.research.base import BaseHttpResearchProvider

logger = logging.getLogger(__name__)


class RssFeedResearchProvider(BaseHttpResearchProvider):
    name = "rss_feed"

    def __init__(self, feed_url: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.feed_url = feed_url if feed_url is not None else os.environ.get("RESEARCH_RSS_FEED_URL", "").strip()

    def is_available(self) -> bool:
        return bool(self.feed_url)

    def _extract_signals(self, niche: str, subcategory_name: str) -> list[ResearchSignal]:
        if not self.feed_url:
            return []

        resp = self._fetch(self.feed_url)
        soup = BeautifulSoup(resp.content, "xml")
        items = soup.find_all(["item", "entry"])  # RSS uses <item>, Atom uses <entry>

        keywords = self._niche_keywords(subcategory_name)
        matches = 0
        titles: list[str] = []
        for item in items:
            title_tag = item.find("title")
            title = title_tag.get_text(strip=True) if title_tag else ""
            if title:
                titles.append(title)
            haystack = title.lower()
            desc_tag = item.find("description") or item.find("summary")
            if desc_tag:
                haystack += " " + desc_tag.get_text(strip=True).lower()
            if any(kw in haystack for kw in keywords):
                matches += 1

        return [
            self._signal(
                niche, "demand_proxy",
                {
                    "feed_url": self.feed_url,
                    "total_items": len(items),
                    "matching_items": matches,
                    "match_ratio": round(matches / len(items), 4) if items else 0.0,
                    "sample_titles": titles[:5],
                },
            )
        ]

    def _niche_keywords(self, subcategory_name: str) -> list[str]:
        words = re.findall(r"[a-z]+", subcategory_name.lower())
        return [w for w in words if len(w) > 2]
