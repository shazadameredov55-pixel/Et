"""
Minimal Telegram Bot API HTTP client, used only by the long-polling bot
(src/telegram_bot/bot.py). Sending notifications from the pipeline itself
goes through TelegramNotificationProvider instead — this client is for
the listening side: getUpdates, answering callback queries, and replying
to commands.
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}/{method}"


class TelegramApiClient:
    def __init__(self, timeout_seconds: int = 35):
        self.timeout_seconds = timeout_seconds
        self._token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not self._token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    def _url(self, method: str) -> str:
        return _API_BASE.format(token=self._token, method=method)

    def get_updates(self, offset: int | None = None, timeout_seconds: int = 30) -> list[dict]:
        params = {"timeout": timeout_seconds}
        if offset is not None:
            params["offset"] = offset
        resp = requests.get(self._url("getUpdates"), params=params, timeout=self.timeout_seconds + timeout_seconds)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"getUpdates failed: {data.get('description')}")
        return data["result"]

    def send_message(self, chat_id: str, text: str, reply_markup: dict | None = None) -> None:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(self._url("sendMessage"), json=payload, timeout=self.timeout_seconds)
        resp.raise_for_status()

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        payload = {"callback_query_id": callback_query_id, "text": text}
        resp = requests.post(self._url("answerCallbackQuery"), json=payload, timeout=self.timeout_seconds)
        resp.raise_for_status()
