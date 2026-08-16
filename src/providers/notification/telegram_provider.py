"""
TelegramNotificationProvider: implements NotificationProvider using the
Telegram Bot API directly over HTTP (no heavyweight bot framework needed
just to send messages — python-telegram-bot is used separately by the
actual listening bot in src/telegram_bot/, which is a different concern:
receiving commands vs. sending notifications).

Configuration via env vars (GitHub Secrets in CI):
- TELEGRAM_BOT_TOKEN
- AUTHORIZED_USER_ID (the only chat_id this provider will ever message)

Security requirement (#17): the bot token is never logged, never written
to any file, never included in an exception message that might reach
logs/artifacts.
"""

from __future__ import annotations

import hashlib
import logging
import os

import requests

from src.core.interfaces import NotificationProvider, NotificationResult

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


def run_id_fingerprint(run_id: str) -> str:
    """Short, deterministic stand-in for a run_id inside Telegram
    callback_data.

    Telegram caps inline-keyboard callback_data at 64 bytes total. A raw
    "approve:<uuid product_id>:<run_id>" string can exceed that on its
    own once a real GitHub Actions run_id (which can run 15-20+ chars) is
    appended to a 36-char UUID, and the API then rejects the whole
    sendMessage call with BUTTON_DATA_INVALID — silently preventing every
    approval message from ever being sent. A 10-hex-char SHA-256 prefix
    is what actually goes in the button instead; src/telegram_bot/bot.py
    verifies it by recomputing this same fingerprint from the record's
    stored run_id before honoring an approve/reject callback, so a stale
    button (referencing a run_id that no longer matches the current
    record) is still rejected exactly as it would be by comparing the
    raw values.
    """
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:10]


class TelegramNotificationProvider(NotificationProvider):
    name = "telegram"

    def __init__(self, timeout_seconds: int = 10):
        self.timeout_seconds = timeout_seconds
        self._token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self._chat_id = os.environ.get("AUTHORIZED_USER_ID", "").strip()

    def is_configured(self) -> bool:
        return bool(self._token and self._chat_id)

    def send_message(self, text: str, reply_markup: dict | None = None) -> NotificationResult:
        if not self.is_configured():
            return NotificationResult(success=False, error="Telegram is not configured (missing token or chat id)")

        url = _API_BASE.format(token=self._token, method="sendMessage")
        payload: dict = {"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            resp = requests.post(url, json=payload, timeout=self.timeout_seconds)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                return NotificationResult(success=False, error=f"Telegram API error: {data.get('description')}")
            return NotificationResult(success=True)
        except requests.exceptions.RequestException as e:
            # Never interpolate the URL (contains the token) into the
            # error message — only a generic description.
            logger.warning("Telegram sendMessage failed: %s", type(e).__name__)
            return NotificationResult(success=False, error=f"Telegram request failed: {type(e).__name__}")

    def send_approval_request(self, product_id: str, summary_text: str, run_id: str = "") -> NotificationResult:
        """Approval keyboard callback_data encodes product_id plus a short
        fingerprint of run_id (format 'approve:<product_id>:<run_id_fingerprint>')
        so the bot's callback handler can validate against
        StateMachine.approve's expected_run_id check before ever touching
        the database. The full run_id is deliberately NOT embedded raw —
        see run_id_fingerprint()'s docstring for why."""
        fp = run_id_fingerprint(run_id)
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ APPROVE", "callback_data": f"approve:{product_id}:{fp}"},
                {"text": "❌ REJECT", "callback_data": f"reject:{product_id}:{fp}"},
                {"text": "🔍 DETAILS", "callback_data": f"details:{product_id}:{fp}"},
            ]]
        }
        return self.send_message(summary_text, reply_markup=keyboard)


def format_opportunity_message(
    title: str,
    target_customer: str,
    problem: str,
    opportunity_score: float,
    demand: float,
    competition: float,
    differentiation: float,
    suggested_price: float | None,
    reasoning: str,
    expected_files: list[str],
) -> str:
    """Builds the exact NEW PRODUCT OPPORTUNITY message shape requested."""
    price_str = f"${suggested_price:.2f}" if suggested_price is not None else "TBD"
    files_str = ", ".join(f.upper() for f in expected_files)
    return (
        "<b>NEW PRODUCT OPPORTUNITY</b>\n\n"
        f"<b>Product:</b> {title}\n"
        f"<b>Target Customer:</b> {target_customer}\n"
        f"<b>Problem:</b> {problem}\n\n"
        f"<b>Opportunity Score:</b> {opportunity_score:.1f}/10\n"
        f"<b>Demand:</b> {demand:.1f}/10\n"
        f"<b>Competition:</b> {competition:.1f}/10\n"
        f"<b>Differentiation:</b> {differentiation:.1f}/10\n\n"
        f"<b>Suggested Price:</b> {price_str}\n"
        f"<b>Why:</b> {reasoning}\n"
        f"<b>Expected Files:</b> {files_str}"
    )


def format_ready_message(
    title: str,
    quality_score: float,
    opportunity_score: float,
    design_profile: str,
    files: list[str],
) -> str:
    files_str = ", ".join(files)
    return (
        "<b>PRODUCT READY</b>\n\n"
        f"<b>Product:</b> {title}\n"
        f"<b>Quality:</b> {quality_score:.1f}/100\n"
        f"<b>Opportunity:</b> {opportunity_score:.1f}/10\n"
        f"<b>Design:</b> {design_profile}\n"
        f"<b>Files:</b> {files_str}\n\n"
        "<b>Status:</b> READY_FOR_MANUAL_UPLOAD"
    )
