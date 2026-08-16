"""
The actual long-polling Telegram bot process. Run this OUTSIDE GitHub
Actions (a local machine, a small always-on host, etc.) — see README.md
for why: GitHub Actions runners are short-lived and cannot host a
persistent listener. This process only reads/writes the local
products.db and calls out to Telegram + GitHub's APIs; it never runs
generation itself (that happens in the GitHub Actions workflow, which
this process triggers via GitHubDispatcher).

Usage:
    python -m src.telegram_bot.bot
"""

from __future__ import annotations

import logging
import time

from src.memory.db import get_connection, init_db
from src.memory.product_repository import ProductRepository, ProductNotFoundError
from src.providers.notification.telegram_provider import run_id_fingerprint
from src.telegram_bot.api_client import TelegramApiClient
from src.telegram_bot.auth import is_authorized
from src.telegram_bot.github_dispatch import GitHubDispatcher
from src.telegram_bot import handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_COMMANDS = {
    "/start": lambda repo, dispatcher, args: handlers.handle_start(repo),
    "/help": lambda repo, dispatcher, args: handlers.handle_help(repo),
    "/status": lambda repo, dispatcher, args: handlers.handle_status(repo),
    "/product": lambda repo, dispatcher, args: handlers.handle_status(repo),
    "/research": lambda repo, dispatcher, args: handlers.handle_research(repo, dispatcher),
    "/create": lambda repo, dispatcher, args: handlers.handle_research(repo, dispatcher),
    "/stop": lambda repo, dispatcher, args: handlers.handle_stop(repo),
    "/history": lambda repo, dispatcher, args: handlers.handle_history(repo),
    "/report": lambda repo, dispatcher, args: handlers.handle_report(repo),
    "/details": lambda repo, dispatcher, args: handlers.handle_details(repo, args[0]) if args else "Usage: /details <product_id>",
}


def _dispatch_text(repo: ProductRepository, dispatcher: GitHubDispatcher, text: str) -> str | None:
    stripped = text.strip()
    lowered = stripped.lower()

    # Turkish free-text equivalents (requirement #12/#16). These map to
    # /stop only for DURDUR (a global action); ONAY/RED/DETAY require a
    # product_id and are documented as working via the inline buttons
    # instead, since free text alone has no reliable way to target a
    # specific pending product when more than one could exist.
    if lowered == "durdur":
        return handlers.handle_stop(repo)

    parts = stripped.split()
    command = parts[0].split("@")[0]  # strip a possible @botname suffix
    args = parts[1:]
    handler = _COMMANDS.get(command)
    if handler:
        return handler(repo, dispatcher, args)
    return None


def _handle_update(repo: ProductRepository, dispatcher: GitHubDispatcher, client: TelegramApiClient, update: dict) -> None:
    if "callback_query" in update:
        cq = update["callback_query"]
        user_id = cq["from"]["id"]
        chat_id = cq["message"]["chat"]["id"]
        if not is_authorized(user_id):
            client.answer_callback_query(cq["id"], text="Not authorized.")
            return

        data = cq.get("data", "")
        parts = data.split(":")
        if len(parts) != 3:
            client.answer_callback_query(cq["id"], text="Malformed action.")
            return
        action, product_id, run_id_fp = parts

        if action in ("approve", "reject"):
            # callback_data only carries a short fingerprint of run_id
            # (see run_id_fingerprint() docstring — the raw value doesn't
            # fit Telegram's 64-byte callback_data limit). Recompute the
            # fingerprint from the record's actual stored run_id and
            # compare, rather than trusting the button's payload directly.
            try:
                record = repo.get(product_id)
            except ProductNotFoundError:
                client.answer_callback_query(cq["id"])
                client.send_message(str(chat_id), f"No product found with id {product_id}")
                return
            if run_id_fingerprint(record.run_id) != run_id_fp:
                client.answer_callback_query(cq["id"])
                client.send_message(
                    str(chat_id),
                    "This approval no longer applies (the product has moved on, or this is a stale/duplicate button press). No action taken.",
                )
                return
            if action == "approve":
                text = handlers.handle_approve_callback(repo, dispatcher, product_id, record.run_id, actor=f"tg:{user_id}")
            else:
                text = handlers.handle_reject_callback(repo, product_id, record.run_id, actor=f"tg:{user_id}")
        elif action == "details":
            text = handlers.handle_details(repo, product_id)
        else:
            text = "Unknown action."

        client.answer_callback_query(cq["id"])
        client.send_message(str(chat_id), text)
        return

    if "message" not in update or "text" not in update["message"]:
        return

    message = update["message"]
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]

    if not is_authorized(user_id):
        logger.warning("Ignoring message from unauthorized user_id=%s", user_id)
        return

    response = _dispatch_text(repo, dispatcher, message["text"])
    if response is not None:
        client.send_message(str(chat_id), response)


def run_forever(db_path: str = "data/products.db", poll_timeout_seconds: int = 30) -> None:
    conn = get_connection(db_path)
    init_db(conn)
    repo = ProductRepository(conn)
    dispatcher = GitHubDispatcher()
    client = TelegramApiClient()

    logger.info("Telegram bot started. Polling for updates...")
    offset: int | None = None
    try:
        while True:
            try:
                updates = client.get_updates(offset=offset, timeout_seconds=poll_timeout_seconds)
            except Exception:
                logger.exception("get_updates failed; retrying in 5s")
                time.sleep(5)
                continue

            for update in updates:
                offset = update["update_id"] + 1
                try:
                    _handle_update(repo, dispatcher, client, update)
                except Exception:
                    logger.exception("Failed to handle update %s", update.get("update_id"))
    finally:
        conn.close()


if __name__ == "__main__":
    run_forever()
