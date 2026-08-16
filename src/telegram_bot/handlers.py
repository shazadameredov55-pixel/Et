"""
Command/callback handlers. Every function here is a plain Python function
taking the repository + dispatcher + parsed input and returning the text
to send back — no Telegram or GitHub HTTP calls happen inside this
module, so every handler is directly unit-testable (see
tests/test_telegram_bot.py). bot.py is the thin adapter that calls these
from the polling loop and actually sends the responses.

Commands implemented: /start /help /status /research /product /create
/approve /reject /details /stop /history /report, plus the Turkish
free-text equivalents ONAY/RED/DETAY/DURDUR (requirement #12/#16).
"""

from __future__ import annotations

from src.core.models import ProductState
from src.core.state_machine import StaleApprovalError
from src.memory.product_repository import ProductRepository, ProductNotFoundError
from src.telegram_bot.github_dispatch import GitHubDispatcher, GitHubDispatchError

_HELP_TEXT = (
    "<b>Commands</b>\n"
    "/status — current in-progress product, if any\n"
    "/research — trigger a new research run\n"
    "/product — alias for /status\n"
    "/create — alias for /research\n"
    "/approve &lt;product_id&gt; — approve the currently pending product\n"
    "/reject &lt;product_id&gt; — reject the currently pending product\n"
    "/details &lt;product_id&gt; — full detail on a product\n"
    "/stop — stop the agent safely (no new runs; in-progress work is not killed)\n"
    "/history — recent products and their status\n"
    "/report — aggregate stats\n\n"
    "You can also just send ONAY / RED / DETAY / DURDUR in reply to a product message."
)


def handle_start(repo: ProductRepository) -> str:
    return "AI Digital Product Agent is connected. Send /help to see available commands."


def handle_help(repo: ProductRepository) -> str:
    return _HELP_TEXT


def handle_status(repo: ProductRepository) -> str:
    pending = repo.list_by_state(ProductState.WAITING_APPROVAL, limit=1)
    in_progress = [
        s for s in (
            ProductState.STRATEGIZING, ProductState.GENERATING,
            ProductState.QUALITY_CHECK, ProductState.REVISION, ProductState.PACKAGING,
        )
    ]
    active = []
    for state in in_progress:
        active += repo.list_by_state(state, limit=5)

    if not pending and not active:
        return "No product is currently pending approval or in progress."

    lines = []
    if pending:
        p = pending[0]
        lines.append(f"⏳ Awaiting approval: <b>{p.title}</b> (id: {p.product_id})")
    for p in active:
        lines.append(f"⚙️ In progress ({p.current_state.value}): <b>{p.title}</b> (id: {p.product_id})")
    return "\n".join(lines)


def handle_research(repo: ProductRepository, dispatcher: GitHubDispatcher) -> str:
    if not dispatcher.is_configured():
        return "Cannot trigger research: GitHub dispatch is not configured on the bot host (missing GITHUB_TOKEN/GITHUB_REPOSITORY)."
    try:
        dispatcher.dispatch(mode="research")
        return "Research run triggered. You'll get a message here once an opportunity is found."
    except GitHubDispatchError as e:
        return f"Failed to trigger research: {e}"


def handle_stop(repo: ProductRepository) -> str:
    # "Stop safely" (requirement #16): this does not kill an in-progress
    # GitHub Actions run (that's outside the bot's control), but it marks
    # every currently-pending-approval product as STOPPED so no approval
    # can accidentally start production on it, and instructs the operator
    # not to trigger new research until they're ready.
    pending = repo.list_by_state(ProductState.WAITING_APPROVAL, limit=20)
    stopped = []
    for p in pending:
        try:
            repo.reject(p.product_id, expected_run_id=p.run_id, actor="telegram_stop")
            stopped.append(p.title)
        except StaleApprovalError:
            continue
    if stopped:
        return "Stopped. The following pending products were marked STOPPED:\n" + "\n".join(f"- {t}" for t in stopped)
    return "Stopped. No pending products were awaiting approval."


def handle_history(repo: ProductRepository, limit: int = 10) -> str:
    records = repo.recent(limit=limit)
    if not records:
        return "No products yet."
    lines = ["<b>Recent products</b>"]
    for r in records:
        quality = f"{r.quality_score:.1f}" if r.quality_score is not None else "—"
        lines.append(f"- {r.title or '(untitled)'} — {r.current_state.value} (quality: {quality})")
    return "\n".join(lines)


def handle_report(repo: ProductRepository) -> str:
    stats = repo.stats()
    return (
        "<b>Report</b>\n"
        f"Total products: {stats['total_products']}\n"
        f"Research runs: {stats['research_runs']}\n"
        f"Successful products (READY): {stats['successful_products']}\n"
        f"Failed runs: {stats['failed_runs']}\n"
        f"Total revisions across all products: {stats['total_revisions']}\n"
        f"Average quality score: {stats['average_quality_score']}\n"
        f"Best opportunity score: {stats['best_opportunity_score']}\n"
    )


def handle_details(repo: ProductRepository, product_id: str) -> str:
    try:
        p = repo.get(product_id)
    except ProductNotFoundError:
        return f"No product found with id {product_id}"
    return (
        f"<b>{p.title}</b>\n"
        f"State: {p.current_state.value}\n"
        f"Niche: {p.niche}\n"
        f"Target customer: {p.target_customer}\n"
        f"Design profile: {p.design_profile}\n"
        f"Features: {', '.join(p.features) if p.features else '—'}\n"
        f"Opportunity score: {p.opportunity_score}\n"
        f"Quality score: {p.quality_score if p.quality_score is not None else '—'}\n"
        f"Revisions: {p.revision_count}\n"
        f"Price suggestion: {p.price_suggestion if p.price_suggestion is not None else '—'}"
    )


def handle_approve_callback(repo: ProductRepository, dispatcher: GitHubDispatcher, product_id: str, run_id: str, actor: str) -> str:
    try:
        record = repo.approve(product_id, expected_run_id=run_id, actor=actor)
    except StaleApprovalError:
        return "This approval no longer applies (the product has moved on, or this is a stale/duplicate button press). No action taken."
    except ProductNotFoundError:
        return f"No product found with id {product_id}"

    if not dispatcher.is_configured():
        return (
            f"Approved: {record.title}. NOTE: GitHub dispatch is not configured on the bot host, "
            f"so the production run was NOT automatically triggered — trigger it manually with "
            f"mode=produce, product_id={product_id}, run_id={run_id}."
        )
    try:
        dispatcher.dispatch(mode="produce", product_id=product_id, run_id=run_id)
        return f"Approved: {record.title}. Production run triggered."
    except GitHubDispatchError as e:
        return f"Approved: {record.title}, but failed to trigger the production run: {e}"


def handle_reject_callback(repo: ProductRepository, product_id: str, run_id: str, actor: str) -> str:
    try:
        record = repo.reject(product_id, expected_run_id=run_id, actor=actor)
    except StaleApprovalError:
        return "This rejection no longer applies (the product has moved on, or this is a stale/duplicate button press). No action taken."
    except ProductNotFoundError:
        return f"No product found with id {product_id}"
    return f"Rejected: {record.title}."


# ------------------------------------------------------------------
# Command dispatch table used by bot.py
# ------------------------------------------------------------------

TEXT_COMMAND_ALIASES = {
    "onay": "approve", "red": "reject", "detay": "details", "durdur": "stop",
}
