"""
Abstract provider interfaces.

These define the contract every concrete provider must satisfy. Nothing in
the orchestrator, strategist, generators, or QC engine is allowed to import
a concrete provider directly — they depend on these interfaces only, so
providers can be swapped or added without touching business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


# --------------------------------------------------------------------------
# AI provider
# --------------------------------------------------------------------------

@dataclass
class AIRequest:
    """A single request to an AI provider."""
    prompt: str
    system_prompt: Optional[str] = None
    max_tokens: int = 1000
    temperature: float = 0.7
    # Free-form context the provider may use (e.g. niche, target customer).
    context: Optional[dict[str, Any]] = None


@dataclass
class AIResponse:
    """Normalized response from any AI provider."""
    text: str
    provider_name: str
    success: bool
    error: Optional[str] = None


class AIProvider(ABC):
    """
    Contract for any AI text-generation backend used by the strategist and
    the QC self-critique step.

    Implementations must NEVER assume a paid API is available. A provider
    that requires a paid key must fail gracefully (return success=False)
    when the key is missing, so the AIProviderRegistry can fall back to
    the next provider in config/settings.yaml -> ai_provider.fallback_order.
    """

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider can currently serve requests
        (e.g. required env var is set, or no dependency needed at all)."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, request: AIRequest) -> AIResponse:
        """Generate text for the given request. Must not raise on ordinary
        failures (timeouts, missing keys, API errors) — must return an
        AIResponse with success=False and a populated error instead."""
        raise NotImplementedError


# --------------------------------------------------------------------------
# Research provider
# --------------------------------------------------------------------------

@dataclass
class ResearchSignal:
    """One piece of market-research evidence for a niche."""
    source_name: str
    niche: str
    signal_type: str          # e.g. "demand", "competition", "price_range"
    payload: dict[str, Any]
    fetched_at: str           # ISO 8601 timestamp


@dataclass
class ResearchResult:
    """Aggregated result of one provider's research pass for a niche."""
    provider_name: str
    niche: str
    signals: list[ResearchSignal]
    success: bool
    error: Optional[str] = None


class ResearchProvider(ABC):
    """
    Contract for a single market-research source. Implementations must be
    self-contained: their own rate limiting, timeout, retry, and
    robots.txt compliance. No implementation may depend on being the only
    source — the registry always aggregates across multiple providers and
    must keep working if one provider fails entirely.
    """

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this source can currently be queried (e.g. no
        outstanding circuit-breaker trip, network reachable in principle)."""
        raise NotImplementedError

    @abstractmethod
    def research(self, niche: str, subcategory_name: str) -> ResearchResult:
        """Gather signals for a single niche. Must not raise on ordinary
        failures — must return a ResearchResult with success=False and a
        populated error instead, so the registry can continue with other
        providers."""
        raise NotImplementedError


# --------------------------------------------------------------------------
# Product generator
# --------------------------------------------------------------------------

@dataclass
class GeneratedFile:
    """One output file produced by a ProductGenerator."""
    file_path: str
    file_type: str            # "xlsx" | "csv" | "pdf" | "png" | "jpg" | "zip"
    description: str


@dataclass
class GenerationResult:
    success: bool
    files: list[GeneratedFile]
    error: Optional[str] = None


class ProductGenerator(ABC):
    """
    Contract for anything that turns a (ProductSpec, DesignProfile) pair
    into a concrete output file. Each concrete file type (xlsx, csv, pdf,
    preview image) has its own generator implementing this interface, so
    the packaging step can treat them uniformly.
    """

    output_type: str = "base"

    @abstractmethod
    def generate(self, product_spec: Any, design_profile: Any, output_dir: str) -> GenerationResult:
        raise NotImplementedError


# --------------------------------------------------------------------------
# Notification provider
# --------------------------------------------------------------------------

@dataclass
class NotificationResult:
    success: bool
    error: Optional[str] = None


class NotificationProvider(ABC):
    """
    Contract for sending notifications / approval requests to the
    authorized user, and for receiving their responses. Telegram is the
    MVP implementation; this interface exists so another channel (email,
    Slack, etc.) could be added later without touching the orchestrator.
    """

    name: str = "base"

    @abstractmethod
    def send_message(self, text: str, reply_markup: Optional[dict[str, Any]] = None) -> NotificationResult:
        raise NotImplementedError

    @abstractmethod
    def send_approval_request(self, product_id: str, summary_text: str) -> NotificationResult:
        """Send a product opportunity summary with APPROVE/REJECT/DETAILS
        actions. The concrete implementation encodes product_id and run_id
        into the callback data so responses can be validated against the
        state machine (see StateMachine.approve / reject)."""
        raise NotImplementedError
