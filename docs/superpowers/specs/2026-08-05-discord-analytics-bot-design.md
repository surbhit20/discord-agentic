# Discord Game-Analytics Bot — Design Spec

## Purpose

A single Discord bot that acts as an on-call game analyst for a mobile game's Firebase/BigQuery analytics data (GA4-for-Firebase export schema). It answers ad-hoc questions asked in Discord ("where are players quitting in the first session") and, without being asked, posts a Monday digest of what moved and the single worst leak worth looking at. The bar it's designed against: never deliver a wrong number confidently. If it can't answer, it says so and names what's missing; if it isn't sure what's being asked, it asks rather than guesses.

Target data source for v1 is the public Flood-It! Firebase Analytics export (`firebase-public-project.analytics_153293282.events_*`) — real mobile game player behavior, in exactly the GA4 schema this bot is built to handle, requiring no access beyond a free-tier personal GCP project. The BigQuery project/dataset is fixed via deploy-time config; nothing in Discord can change it.

Single-tenant: one bot, one Discord server, one data source. No multi-customer onboarding, billing, or tenant isolation.

## Architecture

One always-on Python process (needs a live Discord gateway connection for thread message listening, not just slash-command interactions), hosted on a simple host outside any GCP project (e.g. a small VM or Fly.io/Render app) — the bot never requires provisioning anything inside a GCP project beyond the read-only BigQuery service account used to query data.

```
analystbot/
  bot/            # discord.py client: on_message routing (@mention vs thread-reply), reply formatting
  schema/         # schema discovery (event names, params, date range, player count)
  query/
    backend.py    # BigQuery client: dry_run(sql) -> bytes estimate, execute(sql) -> rows
    generate.py   # question -> SQL (Claude), grounded in discovered schema
    confidence.py # self-rated confidence + query-shape risk scoring -> caution flag
  digest/         # weekly digest job: metric scan, week-over-week comparison, significance check
  memory/         # thread session state + per-user long-term preferences/history
  storage/        # SQLite — schema cache, config, digest history, user memory
  config/         # BigQuery project/dataset + credential path, Anthropic API key, cost threshold
```

External dependencies: BigQuery (read-only service account, deploy-time config) and the Anthropic API (Claude). All bot-owned state lives in one SQLite file on the host.

## Connecting to BigQuery

BigQuery has no connection string. Connecting means:

1. A GCP project you control, for query billing/quota (free tier covers this; doesn't need to be the target dataset's own project — the public Flood-It! dataset is readable by anyone).
2. A service account in that project with the `BigQuery Job User` role (runs queries, billed to your project — no permission needed on the target dataset itself if it's public).
3. A downloaded JSON key for that service account. The bot's config holds its file path (`GOOGLE_APPLICATION_CREDENTIALS`); Google's Python client picks it up automatically.
4. Queries reference the fully-qualified table path directly (e.g. `` `firebase-public-project.analytics_153293282.events_*` ``), independent of which project the credentials belong to.

The project/dataset path and credential are both deploy-time config (env vars). There is no command, in Discord or otherwise, that lets a server member change the data source — only redeploying the code/config can.

## Setup & onboarding

When first @mentioned in a server, the bot runs schema discovery against the configured BigQuery dataset: distinct `event_name` values, common `event_params` keys per event, date range covered, distinct player (`user_pseudo_id`) count. It posts a report in that channel covering what's tracked, what's therefore *not* answerable (e.g. "no `level_fail` event, so I can't compute fail rates, only starts"), how far back data goes, and player count.

A human must reply to confirm the report looks right before the bot starts answering real questions — this is a sanity check on the discovery step itself. That confirmation also designates the channel as the fixed weekly-digest destination; there is no separate step for choosing it.

## Interaction model

No slash commands. A new question is asked by @mentioning the bot anywhere in the server; the bot opens a Discord thread and replies there. Follow-up messages *within that thread* are plain text, no @mention needed, and are understood in the context of that thread's prior question(s)/answer(s). This requires the bot to hold a live gateway connection with message-content access, but scoped narrowly: it only reads messages inside threads it created itself, never other channels or threads.

## Q&A pipeline

For a new question or a thread follow-up:

1. **Understand the question.** Claude interprets it using the discovered schema, the asking user's stored preferences/recent history, and (for follow-ups) the thread's prior question/answer/SQL. This step has three possible outcomes:
   - **Clear match** — a plausible event/param mapping exists → continue to step 2.
   - **Clearly unanswerable** — the schema doesn't cover this at all → honest refusal, naming the specific missing event/param, no SQL attempted.
   - **No plausible mapping** — neither of the above; the bot doesn't guess and doesn't claim data is missing either. It asks a clarifying question back, optionally naming nearby events it does see that might be what was meant.
2. **Generate SQL** — grounded in the actual discovered schema (real event/param names, not guessed), generated fresh each time. No fixed template catalog.
3. **Dry-run cost check** — BigQuery's dry-run estimates bytes scanned before execution, at no cost. Above a configured threshold, the bot replies with the estimate and asks for confirmation before running the query for real.
4. **Confidence & risk scoring** — Claude self-rates its confidence in the interpretation (ambiguous phrasing, assumptions about which event/param was meant). Independently, the generated SQL is checked for risk-correlated shape (multiple joins, window functions, combining event types not obviously designed to be combined). Either one firing adds a visible caution flag to the reply — reserved for "I have a plausible answer but I'm not fully sure," distinct from the no-mapping case in step 1.
5. **Answer** — raw rows become a sentence with the number and the "so what." For comparisons (e.g. retention before/after a build), the reply states whether the gap is large enough relative to sample size to mean something, not just the raw percentage-point difference.

## Memory & sessions

**Thread-scoped (short-term):** the thread created for a question holds that conversation's context — prior question(s), answer(s), and generated SQL — so follow-up replies within it ("what about level 5", "break that down by platform") work without restating context.

**Long-term (per Discord user, across separate threads and days):**
- **Stated preferences** — only what a user explicitly asks the bot to remember (e.g. "always show me D7, not D1"), applied as defaults on that person's future questions.
- **Recent question history** — a rolling log of that user's past questions/answers, so the bot can reference prior context ("last time you asked about the tutorial funnel...") even in a brand-new thread.

Both are stored in SQLite, keyed by Discord user ID. No expiry/pruning logic in v1.

## Weekly digest

Every Monday, an in-process scheduler (e.g. APScheduler) fires a job that:

1. Re-runs the tracked metric set (from the prior digest, or from onboarding's discovery on the first run) against the current week's data.
2. Compares each metric to the previous week using the same significance-aware comparison logic as ad-hoc questions (not raw percentage-point deltas on small samples), flagging what moved meaningfully.
3. Posts to the fixed digest channel: what moved, the single worst current leak (ranked), and one suggested thing to look at.

This week's computed values are stored as next week's comparison baseline, and are also reused by ad-hoc questions that reference "last week" (e.g. "did retention drop after last week's build") rather than recomputing it from raw data each time.

Mid-week anomaly alerts are explicitly deferred past v1.

## Storage & data model

Single SQLite file on the host:

- `schema_cache` — discovered events/params/date range/player count, refreshed on each onboarding run or re-confirmation.
- `config` — digest channel ID, set once at onboarding confirmation (the only runtime-determined setting; cost-check threshold and all other config remain deploy-time env vars, not DB-stored).
- `digest_history` — last digest's metric values, for week-over-week comparison.
- `user_memory` — per-user stated preferences and rolling recent question/answer history.
- `threads` — active thread → originating question/SQL/answer, so follow-ups can load context.

## Testing

- Schema discovery and SQL generation tested against the real public Flood-It! dataset directly — free, stable, already in the exact target schema, no fixtures needed.
- The three-way question-understanding split (clear / unanswerable / ambiguous) and confidence/risk scoring tested with a fixed set of scripted example questions and expected outcomes.
- Digest comparison logic (significance-aware week-over-week) unit tested with synthetic before/after numbers, independent of BigQuery.
- One live end-to-end sanity check (real @mention → real thread follow-up → real digest run) before considering v1 done.

## Explicitly out of scope for v1

- Mid-week anomaly alerts.
- Any in-Discord way to change the BigQuery project/dataset (fixed via deploy-time config/code only).
- Multi-server support (one Discord server, one fixed data source).
- Memory expiry/pruning.
- Any write access to BigQuery (read-only throughout).
- Multi-tenant/installable-product concerns (per-customer auth, billing, isolation).
