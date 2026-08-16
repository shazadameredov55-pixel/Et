"""
BaseHttpResearchProvider: shared plumbing every concrete ResearchProvider
inherits — rate limiting, timeout, retry with backoff, and robots.txt
compliance. Requirement (Phase 1 + Phase 3 #1): no research provider may
bypass CAPTCHA/anti-bot mechanisms, access login-gated content, or ignore
robots.txt. Concrete providers only implement `_extract_signals()`; they
never make an HTTP request directly.

Design note on source selection: this codebase deliberately does NOT ship
a scraper hardcoded against a specific commercial marketplace (Etsy,
Gumroad, etc.) — many such sites' terms of service and anti-bot measures
would make an automated scraper non-compliant with the "no CAPTCHA/anti-bot
bypass" requirement even with rate limiting. Instead, each concrete
provider is configured with a source URL via environment variable, so the
person operating this agent supplies sources they have the right to poll
(public APIs, RSS/Atom feeds, or pages whose robots.txt permits it). See
README.md for configuration.
"""

from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

from src.core.interfaces import ResearchProvider, ResearchResult, ResearchSignal
from src.core.models import now_iso

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple per-host minimum-interval limiter. Not a token bucket —
    intentionally simple since a single GitHub Actions run makes a small,
    bounded number of research calls."""

    def __init__(self, requests_per_minute: int):
        self._min_interval = 60.0 / max(1, requests_per_minute)
        self._last_call_at: dict[str, float] = {}

    def wait(self, host: str) -> None:
        last = self._last_call_at.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            remaining = self._min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_call_at[host] = time.monotonic()


class RobotsDisallowedError(Exception):
    """Raised when robots.txt disallows fetching the target URL."""


class BaseHttpResearchProvider(ResearchProvider):
    def __init__(
        self,
        timeout_seconds: int = 10,
        max_retries: int = 3,
        backoff_base_seconds: float = 2.0,
        rate_limiter: RateLimiter | None = None,
        user_agent: str = "AIDigitalProductAgent/1.0 (research; contact-via-telegram-bot)",
    ):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self.rate_limiter = rate_limiter or RateLimiter(requests_per_minute=20)
        self.user_agent = user_agent
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    # ------------------------------------------------------------------
    # robots.txt compliance
    # ------------------------------------------------------------------

    def _check_robots_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots_cache.get(origin)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{origin}/robots.txt")
            try:
                rp.read()
            except Exception:
                # If robots.txt is unreachable, fail closed: do not assume
                # permission. A provider that can't verify robots.txt
                # should report failure, not silently scrape anyway.
                logger.warning("Could not fetch robots.txt for %s; treating as disallowed", origin)
                return False
            self._robots_cache[origin] = rp
        return rp.can_fetch(self.user_agent, url)

    # ------------------------------------------------------------------
    # HTTP fetch with rate limit + retry + timeout
    # ------------------------------------------------------------------

    def _fetch(self, url: str) -> requests.Response:
        if not self._check_robots_allowed(url):
            raise RobotsDisallowedError(f"robots.txt disallows fetching {url}")

        host = urlparse(url).netloc
        self.rate_limiter.wait(host)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": self.user_agent},
                    timeout=self.timeout_seconds,
                )
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as e:
                last_exc = e
                logger.warning("Research fetch attempt %d/%d failed for %s: %s", attempt, self.max_retries, url, e)
                if attempt < self.max_retries:
                    time.sleep(self.backoff_base_seconds ** attempt)
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # ResearchProvider contract
    # ------------------------------------------------------------------

    def research(self, niche: str, subcategory_name: str) -> ResearchResult:
        try:
            signals = self._extract_signals(niche, subcategory_name)
            return ResearchResult(provider_name=self.name, niche=niche, signals=signals, success=True)
        except RobotsDisallowedError as e:
            logger.warning("%s: %s", self.name, e)
            return ResearchResult(provider_name=self.name, niche=niche, signals=[], success=False, error=str(e))
        except Exception as e:  # noqa: BLE001 - must never raise past this boundary
            logger.exception("%s research failed unexpectedly", self.name)
            return ResearchResult(provider_name=self.name, niche=niche, signals=[], success=False, error=str(e))

    def _extract_signals(self, niche: str, subcategory_name: str) -> list[ResearchSignal]:
        raise NotImplementedError

    def _signal(self, niche: str, signal_type: str, payload: dict) -> ResearchSignal:
        return ResearchSignal(
            source_name=self.name, niche=niche, signal_type=signal_type,
            payload=payload, fetched_at=now_iso(),
        )
