# analystbot

A Discord bot that turns your game's Firebase/GA4 BigQuery analytics into a teammate you can talk to — ask it questions in plain English and it answers from real data, or wait for Monday and let it tell you what happened last week.

Currently pointed at the public **Flood-It!** game analytics dataset (`firebase-public-project.analytics_153293282`) as a live testbed; the data source is swappable via config.

## What it does

- **Onboarding** — the first time you `@mention` it, it discovers your BigQuery schema (event names, params, date range, player count), reports what it found *and what it can't answer yet* (e.g. "you track `session_start` but nothing that closes a session"), and waits for you to `confirm`.
- **Ask questions** — `@mention` it with a question and it opens a thread, generates SQL grounded in your real schema, and answers with a number and the "so what." Reply in the thread (no re-mention needed) to ask follow-ups with full context.
- **Honest refusals** — if the data can't answer your question, it says so and names what's missing, instead of guessing. It never uses its own general knowledge to answer anything outside your game's data — off-topic questions get a clean refusal, not an aside.
- **Cost-aware** — every query is dry-run estimated first. Expensive queries ask for confirmation before running.
- **Confidence flags** — when the model made an uncertain assumption (which event/param it picked) or the generated SQL has a risky shape, the answer comes with a visible caution note.
- **Memory** — remembers your recent questions and any preferences you explicitly ask it to keep ("always show me D7, not D1") across separate conversations.
- **Weekly digest** — every Monday, posts what moved (with actual statistical significance testing, not just raw percentage deltas) and the single worst funnel drop-off (e.g. `level_start → level_complete`), to a channel set during onboarding.

## Architecture

```
analystbot/
  config.py           # env-var config loading
  main.py              # process entrypoint: Discord client + weekly scheduler
  bot/
    client.py           # AnalystBot (discord.py Client), on_message routing
    routing.py           # @mention vs thread-follow-up classification
    onboarding.py         # schema discovery report + gap detection
    pipeline.py            # question -> SQL -> cost check -> confidence -> answer
    replies.py              # refusal/clarify/caution/cost-warning formatting
  query/
    backend.py           # BigQuery client wrapper (dry-run + execute, SELECT-only)
    schema_discovery.py   # event/param/date-range discovery
    generate.py             # Claude: question -> SQL, refuse, or clarify
    confidence.py            # self-rated confidence + query-risk scoring
    cost_check.py             # dry-run threshold check
    answer.py                  # rows -> a sentence with the number and the so-what
  digest/
    compute.py            # weekly metric comparison + worst-leak ranking
    significance.py         # two-proportion significance testing
    scheduler.py              # APScheduler wiring
  schema_funnels.py    # shared start/end funnel-pair detection (onboarding + digest)
  storage/              # SQLite: schema cache, config, digest history, memory, threads
```

One always-on process: a `discord.py` gateway client plus an in-process weekly scheduler, backed by a single SQLite file for all bot state and a read-only BigQuery connection. No slash commands — interaction is entirely `@mention` (new question) and plain-text thread replies (follow-ups).

## Setup

1. **Discord bot**: create an application at the [Discord Developer Portal](https://discord.com/developers/applications), add a bot user, enable the **Message Content** privileged intent, and invite it to your server with `Send Messages`, `Create Public Threads`, and `Read Message History` permissions.
2. **Anthropic API key**: from [console.anthropic.com](https://console.anthropic.com).
3. **BigQuery access**: any GCP project with the BigQuery API enabled and a service account granted `BigQuery Job User` (no permission on the target dataset is needed if it's public, like the Flood-It! dataset).
4. Copy `.env.example` to `.env` and fill in the values.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m analystbot.main
```

## Configuration

| Env var | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | yes | Bot token |
| `ANTHROPIC_API_KEY` | yes | Claude API key |
| `BQ_BILLING_PROJECT` | yes | GCP project the queries are billed to |
| `BQ_DATASET_PATH` | yes | Fully-qualified `project.dataset` to query, e.g. `firebase-public-project.analytics_153293282` |
| `GOOGLE_APPLICATION_CREDENTIALS` | yes | Path to a service account key JSON file |
| `COST_THRESHOLD_BYTES` | no | Bytes-scanned threshold above which a query asks for confirmation (default 1 GiB) |
| `BQ_PRICE_PER_TIB_USD` | no | Price per TiB scanned, used to show an estimated dollar cost in cost warnings (default `6.25`, BigQuery's on-demand rate — override for your actual pricing tier/region) |
| `DB_PATH` | no | SQLite file path (default `analystbot.db`) |
| `LOG_LEVEL` | no | Python logging level (default `INFO`) |

The data source is fixed via these env vars only — there is no in-Discord way to change it. Once running, `@mention` the bot with `resetup` at any time to re-run schema discovery and refresh the digest channel.

## Testing

```bash
pytest -v
```

Tests hitting real BigQuery or Anthropic are marked `@pytest.mark.live` and skip cleanly when credentials aren't set — safe to run without any config.

## Design docs

- [`docs/superpowers/specs/2026-08-05-discord-analytics-bot-design.md`](docs/superpowers/specs/2026-08-05-discord-analytics-bot-design.md) — design spec
- [`docs/superpowers/plans/2026-08-05-discord-analytics-bot.md`](docs/superpowers/plans/2026-08-05-discord-analytics-bot.md) — implementation plan
