# AI Digital Product Production Agent

Researches, scores, and (after your Telegram approval) generates
Personal-Finance / Budget digital products — a working Excel spreadsheet,
a printable PDF, a preview image, usage instructions, and a suggested
marketplace listing — packaged as a ZIP you upload yourself. **This
system never uploads anything to a sales platform automatically.**

## Architecture at a glance

```
USER → GitHub Actions (workflow_dispatch, mode=research)
      → Research providers → Opportunity scoring → Similarity check
      → Telegram: "NEW PRODUCT OPPORTUNITY" [APPROVE] [REJECT] [DETAILS]
      → (run ends — GitHub Actions is not a persistent server)

      ... you tap APPROVE in Telegram ...

      → Telegram bot (running separately, see below) triggers
        GitHub Actions again (workflow_dispatch, mode=produce)
      → Strategy → Design → Generate (XLSX/PDF/Preview/Instructions)
      → QC → AI self-critique → Revision (up to 3x) → Packaging
      → Telegram: "PRODUCT READY" + ZIP
      → YOU manually upload the ZIP wherever you sell
```

### Why two processes (GitHub Actions + a separate Telegram bot)?

GitHub Actions runners are short-lived — a run starts, does work, and
ends. They cannot sit and listen for your Telegram tap on APPROVE.
So this repo has two parts:

1. **GitHub Actions** (`.github/workflows/run_agent.yml`) — does the
   actual research/generation work, triggered by `workflow_dispatch`.
   This is the core pipeline described in this project's phase-by-phase
   design docs.
2. **The Telegram bot** (`src/telegram_bot/bot.py`) — a small
   long-polling process **you run somewhere that stays on** (your own
   machine, a Raspberry Pi, a free-tier Railway/Render/Fly.io instance,
   etc.). It listens for your commands and button taps, and when you
   approve something, it calls the GitHub API to trigger the Actions
   workflow in `produce` mode. It does not do any product generation
   itself — it only reads/writes `data/products.db` and calls two HTTP
   APIs (Telegram, GitHub).

If you don't want to run a second process at all, you can skip the bot
and just run `mode=produce` manually from the Actions UI once you decide
(from the Telegram message alone) that you want to approve — see
"Manual approval without the bot" below.

## Setup

### 1. GitHub Secrets

Repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Required | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | From @BotFather |
| `AUTHORIZED_USER_ID` | Yes | Your numeric Telegram user id (e.g. from @userinfobot) — the bot ignores everyone else |
| `AI_API_URL` | No | OpenAI-chat-completions-compatible endpoint for a real language model. Omit to run entirely on the free, local `RuleBasedAIProvider` heuristic. |
| `AI_API_KEY` | No | Bearer token for the above, if the endpoint requires one |
| `AI_API_MODEL` | No | Model id string the endpoint expects |
| `RESEARCH_RSS_FEED_URL` | No | An RSS/Atom feed URL you have the right to poll, used as a demand-signal proxy |
| `RESEARCH_PAGE_URL` | No | A public webpage URL you have the right to poll, used as a competition-signal proxy |

**Without `AI_API_URL`/`RESEARCH_*`, the agent still runs end-to-end** —
it falls back to `RuleBasedAIProvider` (deterministic heuristics, zero
cost) and `NullResearchProvider` (neutral baseline scores, zero
network calls). See "Cost & data-source limitations" below for what
this means in practice.

### 2. The Telegram bot host

Also needs, wherever you run it (its own `.env` or host's secret manager
— **never commit these**):

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Same bot token as above |
| `AUTHORIZED_USER_ID` | Same as above |
| `GITHUB_TOKEN` | A PAT (classic or fine-grained) with `actions: write` on this repo — **different from the auto-injected token inside a workflow run**, which cannot trigger other workflow runs |
| `GITHUB_REPOSITORY` | `your-username/your-repo` |

Run it with:
```bash
pip install -r requirements.txt
python -m src.telegram_bot.bot
```

### 3. First run

GitHub → Actions → "AI Digital Product Agent" → Run workflow →
`mode=research`. Watch for a Telegram message. If nothing arrives, check
the Actions run logs — every failure is logged and (if Telegram secrets
are set) reported to you directly, never silent.

## Manual approval without the bot

If you don't want to host the bot: read the Telegram opportunity
message, then manually run the workflow again with `mode=produce`,
`product_id` = the id in the message, `run_id` = the run that sent it
(visible in the Actions run that sent the Telegram message). The state
machine validates both — a mismatched pair is rejected, not silently
processed.

## Commands (via the Telegram bot)

`/start` `/help` `/status` `/research` `/product` `/create` `/approve`
`/reject` `/details <product_id>` `/stop` `/history` `/report`

Also understands `DURDUR` as a global stop. `ONAY`/`RED`/`DETAY` are
handled via the inline APPROVE/REJECT/DETAILS buttons on each opportunity
message (free text alone can't reliably target one product among several
pending ones).

## Product workflow states

```
RESEARCHING → WAITING_APPROVAL → STRATEGIZING → GENERATING → QUALITY_CHECK
                    │ (reject)                                    │
                    ▼                              ┌───────(fail QC/critique, revisions < 3)
                 STOPPED                            ▼
                                                  REVISION → back to GENERATING
                                                  (revisions == 3 and still failing → FAILED, "NEEDS_REVIEW" sent)
                                        (pass) → PACKAGING → READY → Telegram delivery
```

Any unhandled exception at any stage → `FAILED`, logged, and reported to
Telegram — never a silent failure.

## Adding a new product niche

1. Add the subcategory to `config/categories.yaml`.
2. Add a `_<niche>()` function in `src/generators/blueprints.py` defining
   its sheets/columns/formulas (see the three existing examples).
3. Wire its formulas into `XlsxGenerator._apply_formulas` if it needs
   cross-sheet calculations beyond simple per-row values.
4. Run `pytest tests/test_product_variation.py` to confirm the new
   blueprint doesn't structurally collide with an existing one.

## Cost & data-source limitations

- **No paid API is required.** Every component has a free/local fallback
  (`RuleBasedAIProvider`, `NullResearchProvider`) and the pipeline was
  verified end-to-end using only those fallbacks.
- **Research quality without configured sources is intentionally
  conservative.** `NullResearchProvider` alone means every niche scores
  a neutral baseline (~5.8-6.0/10) — good enough to clear the default
  notify threshold (5.5) so the pipeline isn't silently blocked, but not
  a substitute for real market signals. Configure
  `RESEARCH_RSS_FEED_URL`/`RESEARCH_PAGE_URL` with sources you have the
  right to poll for more meaningful scoring.
- **No scraper targets a specific commercial marketplace by name.** This
  is deliberate — platform-specific scraping risks violating that
  platform's terms of service and this codebase's own "no CAPTCHA/anti-bot
  bypass" requirement. Point the generic providers at sources you control
  or have permission to poll.
- If you do configure a paid `AI_API_URL`, every successful call is
  logged at INFO level in the Actions run (cost guard / requirement #10)
  so usage is always visible.

## Security

- Secrets only ever come from GitHub Secrets (Actions) or the bot host's
  own environment — never hardcoded, never committed.
- `TelegramNotificationProvider` and the bot's `api_client.py` never
  interpolate the bot token into a log line or exception message.
- `product-memory-db` (the SQLite artifact) contains no secrets and no
  personal data by schema design — safe to persist as a GitHub Actions
  artifact.
- The bot ignores every Telegram user except `AUTHORIZED_USER_ID`,
  checked on every command and every button press.

## Testing

```bash
pip install -r requirements.txt
pytest tests/ -v
```

All 150+ tests use mocked HTTP for every external service (Telegram,
GitHub API, research sources, optional AI API) — `pytest` never makes a
real network call, never spends real money, and never touches a real
marketplace. `tests/test_integration_full_pipeline.py` runs the entire
research → approval → generation → QC → packaging flow against real
generated files (a real .xlsx, real PDFs, a real PNG, a real ZIP) with
only the network-facing edges mocked.

## Troubleshooting

- **No Telegram message after a research run**: check Actions logs for
  `Failed to send Telegram approval request` — usually a missing/wrong
  `TELEGRAM_BOT_TOKEN` or `AUTHORIZED_USER_ID`, or every niche scored
  below `minimum_score_to_notify` in `config/scoring.yaml`.
- **APPROVE button says "no longer applies"**: the product already moved
  past `WAITING_APPROVAL` (e.g. you tapped it twice), or you're looking
  at a stale message from an earlier run. Use `/status` for the current
  pending product.
- **`mode=produce` fails immediately**: `--product-id`/`--run-id` are
  required and validated against the state machine — check the Actions
  run's log line for the exact mismatch reason.
- **Bot process not responding**: it must be running continuously
  somewhere (see "Setup" above) — GitHub Actions cannot host it.
