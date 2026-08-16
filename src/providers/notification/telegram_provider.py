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

import logging
import os

import requests

from src.core.interfaces import NotificationProvider, NotificationResult

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


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
        """Approval keyboard callback_data encodes both product_id and
        run_id (format 'approve:<product_id>:<run_id>') so the bot's
        callback handler can validate against StateMachine.approve's
        expected_run_id check before ever touching the database."""
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ APPROVE", "callback_data": f"approve:{product_id}:{run_id}"},
                {"text": "❌ REJECT", "callback_data": f"reject:{product_id}:{run_id}"},
                {"text": "🔍 DETAILS", "callback_data": f"details:{product_id}:{run_id}"},
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
