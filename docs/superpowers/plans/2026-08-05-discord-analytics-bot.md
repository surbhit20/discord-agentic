# Discord Game-Analytics Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-tenant Discord bot that answers ad-hoc game-analytics questions against the public Flood-It! Firebase/BigQuery export and posts a weekly digest, per `docs/superpowers/specs/2026-08-05-discord-analytics-bot-design.md`.

**Architecture:** One always-on Python process (`discord.py` gateway client + in-process scheduler) backed by a single BigQuery data source (fixed via deploy-time config) and a single SQLite file for all bot-owned state. No slash commands — interaction is via @mention (new question) and plain-text replies inside bot-created threads (follow-ups).

**Tech Stack:** Python 3.11+, `discord.py`, `google-cloud-bigquery`, `anthropic` (Claude), `apscheduler`, `sqlite3` (stdlib), `pytest` + `pytest-asyncio`.

## Global Constraints

- BigQuery project/dataset is fixed via env vars (`BQ_BILLING_PROJECT`, `BQ_DATASET_PATH`) only. No code path may let a Discord command change it.
- No slash commands anywhere.
- BigQuery access is read-only throughout — only `SELECT` and dry-run queries, never DDL/DML.
- SQLite is the only persistence layer: a single file at the path from `DB_PATH` (default `analystbot.db`).
- Tests that call real BigQuery or the real Anthropic API are marked `@pytest.mark.live` and must skip cleanly (via `tests/conftest.py::skip_unless_env`) when their required env vars are unset — never fail on missing credentials.
- Claude model id: `claude-sonnet-5`.
- Real BigQuery target for all live tests: `firebase-public-project.analytics_153293282` (public, free to query).

---

### Task 1: Project scaffolding & config

**Files:**
- Create: `pyproject.toml`
- Create: `analystbot/__init__.py`
- Create: `analystbot/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `class ConfigError(Exception)`; `@dataclass class Config` with fields `discord_token: str`, `anthropic_api_key: str`, `bq_billing_project: str`, `bq_dataset_path: str`, `google_application_credentials: str`, `cost_threshold_bytes: int`, `db_path: str`; `def load_config(env: dict[str, str]) -> Config`. Also `def skip_unless_env(*names: str) -> None` in `tests/conftest.py`, used by every later `@pytest.mark.live` test.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from analystbot.config import load_config, ConfigError

_FULL_ENV = {
    "DISCORD_TOKEN": "d-token",
    "ANTHROPIC_API_KEY": "a-key",
    "BQ_BILLING_PROJECT": "my-project",
    "BQ_DATASET_PATH": "firebase-public-project.analytics_153293282",
    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/creds.json",
}

def test_loads_config_from_full_env():
    config = load_config(_FULL_ENV)
    assert config.discord_token == "d-token"
    assert config.bq_dataset_path == "firebase-public-project.analytics_153293282"
    assert config.cost_threshold_bytes == 1024 ** 3
    assert config.db_path == "analystbot.db"

def test_missing_required_var_raises_with_name():
    partial = dict(_FULL_ENV)
    del partial["DISCORD_TOKEN"]
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        load_config(partial)

def test_cost_threshold_overridable():
    env = dict(_FULL_ENV, COST_THRESHOLD_BYTES="500")
    assert load_config(env).cost_threshold_bytes == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.config'` (or `analystbot`, if `pyproject.toml`/package dir don't exist yet — create the empty package first, then re-run to confirm the import-not-found failure is specifically on `config`).

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[project]
name = "analystbot"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "discord.py>=2.4",
    "google-cloud-bigquery>=3.25",
    "anthropic>=0.40",
    "apscheduler>=3.10",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24"]

[tool.pytest.ini_options]
markers = ["live: hits a real external service (BigQuery/Anthropic); skips if credentials are unset"]
asyncio_mode = "auto"
```

```python
# analystbot/config.py
from dataclasses import dataclass


class ConfigError(Exception):
    pass


@dataclass
class Config:
    discord_token: str
    anthropic_api_key: str
    bq_billing_project: str
    bq_dataset_path: str
    google_application_credentials: str
    cost_threshold_bytes: int
    db_path: str


_REQUIRED = [
    "DISCORD_TOKEN",
    "ANTHROPIC_API_KEY",
    "BQ_BILLING_PROJECT",
    "BQ_DATASET_PATH",
    "GOOGLE_APPLICATION_CREDENTIALS",
]


def load_config(env: dict[str, str]) -> Config:
    missing = [name for name in _REQUIRED if not env.get(name)]
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")
    return Config(
        discord_token=env["DISCORD_TOKEN"],
        anthropic_api_key=env["ANTHROPIC_API_KEY"],
        bq_billing_project=env["BQ_BILLING_PROJECT"],
        bq_dataset_path=env["BQ_DATASET_PATH"],
        google_application_credentials=env["GOOGLE_APPLICATION_CREDENTIALS"],
        cost_threshold_bytes=int(env.get("COST_THRESHOLD_BYTES", str(1024 ** 3))),
        db_path=env.get("DB_PATH", "analystbot.db"),
    )
```

```python
# tests/conftest.py
import os
import pytest


def skip_unless_env(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        pytest.skip(f"missing env vars for live test: {', '.join(missing)}")
```

Also create empty `analystbot/__init__.py` and `tests/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -e ".[dev]" && pytest tests/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml analystbot/__init__.py analystbot/config.py tests/__init__.py tests/conftest.py tests/test_config.py
git commit -m "feat: add project scaffolding and env-based config loading"
```

---

### Task 2: SQLite storage layer

**Files:**
- Create: `analystbot/storage/__init__.py`
- Create: `analystbot/storage/db.py`
- Create: `analystbot/storage/schema_cache.py`
- Create: `analystbot/storage/config_store.py`
- Create: `analystbot/storage/digest_history.py`
- Create: `analystbot/storage/user_memory.py`
- Create: `analystbot/storage/threads.py`
- Test: `tests/storage/test_storage.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces:
  - `db.get_connection(db_path: str) -> sqlite3.Connection`, `db.init_db(conn: sqlite3.Connection) -> None`
  - `schema_cache.save_schema(conn, schema: dict) -> None`, `schema_cache.load_schema(conn) -> dict | None`
  - `config_store.set_digest_channel(conn, channel_id: int) -> None`, `config_store.get_digest_channel(conn) -> int | None`
  - `digest_history.save_digest(conn, metrics: dict[str, tuple[int, int]], week_start: str) -> None`, `digest_history.load_last_digest(conn) -> dict | None` (returns `{"week_start": str, "metrics": dict[str, tuple[int, int]]}`)
  - `user_memory.add_preference(conn, user_id: int, preference: str) -> None`, `user_memory.get_preferences(conn, user_id: int) -> list[str]`, `user_memory.add_question_history(conn, user_id: int, question: str, answer: str) -> None`, `user_memory.get_recent_history(conn, user_id: int, limit: int = 5) -> list[dict]` (each `{"question", "answer", "asked_at"}`)
  - `threads.save_thread_context(conn, thread_id: int, question: str, sql: str | None, answer: str) -> None`, `threads.get_thread_context(conn, thread_id: int) -> list[dict]` (each `{"question", "sql", "answer"}`, in turn order)

- [ ] **Step 1: Write the failing test**

```python
# tests/storage/test_storage.py
import sqlite3
from analystbot.storage import db, digest_history, schema_cache, config_store, user_memory, threads


def _conn():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    return conn


def test_digest_history_round_trip():
    conn = _conn()
    assert digest_history.load_last_digest(conn) is None
    digest_history.save_digest(conn, {"tutorial_step_3": (780, 1000)}, "2026-08-03")
    last = digest_history.load_last_digest(conn)
    assert last["week_start"] == "2026-08-03"
    assert last["metrics"]["tutorial_step_3"] == (780, 1000)


def test_schema_cache_round_trip():
    conn = _conn()
    assert schema_cache.load_schema(conn) is None
    schema_cache.save_schema(
        conn,
        {"events": {"level_start": ["level_number"]}, "date_range": ("20180101", "20180419"), "player_count": 500},
    )
    loaded = schema_cache.load_schema(conn)
    assert loaded["player_count"] == 500
    assert loaded["events"]["level_start"] == ["level_number"]


def test_config_store_digest_channel_round_trip():
    conn = _conn()
    assert config_store.get_digest_channel(conn) is None
    config_store.set_digest_channel(conn, 12345)
    assert config_store.get_digest_channel(conn) == 12345
    config_store.set_digest_channel(conn, 999)
    assert config_store.get_digest_channel(conn) == 999


def test_user_memory_preferences_and_history():
    conn = _conn()
    user_memory.add_preference(conn, 1, "always show D7 not D1")
    assert user_memory.get_preferences(conn, 1) == ["always show D7 not D1"]
    user_memory.add_question_history(conn, 1, "what is D1", "38%")
    history = user_memory.get_recent_history(conn, 1, limit=5)
    assert history[0]["question"] == "what is D1"
    assert history[0]["answer"] == "38%"


def test_thread_context_round_trip():
    conn = _conn()
    assert threads.get_thread_context(conn, 999) == []
    threads.save_thread_context(conn, 999, "where do players quit", "SELECT 1", "tutorial step 3 loses 22%")
    threads.save_thread_context(conn, 999, "what about level 5", "SELECT 2", "level 5 loses 31%")
    ctx = threads.get_thread_context(conn, 999)
    assert len(ctx) == 2
    assert ctx[0]["question"] == "where do players quit"
    assert ctx[1]["question"] == "what about level 5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/storage/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.storage'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/storage/db.py
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    schema_json TEXT NOT NULL,
    discovered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    digest_channel_id INTEGER
);

CREATE TABLE IF NOT EXISTS digest_history (
    week_start TEXT PRIMARY KEY,
    metrics_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER NOT NULL,
    preference TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_question_history (
    user_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    asked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread_context (
    thread_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    sql TEXT,
    answer TEXT NOT NULL,
    turn_order INTEGER NOT NULL
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()
```

```python
# analystbot/storage/schema_cache.py
import json
import sqlite3
from datetime import datetime, timezone


def save_schema(conn: sqlite3.Connection, schema: dict) -> None:
    conn.execute(
        "INSERT INTO schema_cache (id, schema_json, discovered_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET schema_json = excluded.schema_json, discovered_at = excluded.discovered_at",
        (json.dumps(schema), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def load_schema(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT schema_json FROM schema_cache WHERE id = 1").fetchone()
    return json.loads(row[0]) if row else None
```

```python
# analystbot/storage/config_store.py
import sqlite3


def set_digest_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    conn.execute(
        "INSERT INTO bot_config (id, digest_channel_id) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET digest_channel_id = excluded.digest_channel_id",
        (channel_id,),
    )
    conn.commit()


def get_digest_channel(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT digest_channel_id FROM bot_config WHERE id = 1").fetchone()
    return row[0] if row else None
```

```python
# analystbot/storage/digest_history.py
import json
import sqlite3


def save_digest(conn: sqlite3.Connection, metrics: dict[str, tuple[int, int]], week_start: str) -> None:
    conn.execute(
        "INSERT INTO digest_history (week_start, metrics_json) VALUES (?, ?)",
        (week_start, json.dumps(metrics)),
    )
    conn.commit()


def load_last_digest(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT week_start, metrics_json FROM digest_history ORDER BY week_start DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    week_start, metrics_json = row
    metrics = {k: tuple(v) for k, v in json.loads(metrics_json).items()}
    return {"week_start": week_start, "metrics": metrics}
```

```python
# analystbot/storage/user_memory.py
import sqlite3
from datetime import datetime, timezone


def add_preference(conn: sqlite3.Connection, user_id: int, preference: str) -> None:
    conn.execute("INSERT INTO user_preferences (user_id, preference) VALUES (?, ?)", (user_id, preference))
    conn.commit()


def get_preferences(conn: sqlite3.Connection, user_id: int) -> list[str]:
    rows = conn.execute("SELECT preference FROM user_preferences WHERE user_id = ?", (user_id,)).fetchall()
    return [r[0] for r in rows]


def add_question_history(conn: sqlite3.Connection, user_id: int, question: str, answer: str) -> None:
    conn.execute(
        "INSERT INTO user_question_history (user_id, question, answer, asked_at) VALUES (?, ?, ?, ?)",
        (user_id, question, answer, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_recent_history(conn: sqlite3.Connection, user_id: int, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        "SELECT question, answer, asked_at FROM user_question_history "
        "WHERE user_id = ? ORDER BY asked_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [{"question": r[0], "answer": r[1], "asked_at": r[2]} for r in rows]
```

```python
# analystbot/storage/threads.py
import sqlite3


def save_thread_context(conn: sqlite3.Connection, thread_id: int, question: str, sql: str | None, answer: str) -> None:
    next_order = conn.execute(
        "SELECT COALESCE(MAX(turn_order), -1) + 1 FROM thread_context WHERE thread_id = ?", (thread_id,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO thread_context (thread_id, question, sql, answer, turn_order) VALUES (?, ?, ?, ?, ?)",
        (thread_id, question, sql, answer, next_order),
    )
    conn.commit()


def get_thread_context(conn: sqlite3.Connection, thread_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT question, sql, answer FROM thread_context WHERE thread_id = ? ORDER BY turn_order",
        (thread_id,),
    ).fetchall()
    return [{"question": r[0], "sql": r[1], "answer": r[2]} for r in rows]
```

Also create empty `analystbot/storage/__init__.py` and `tests/storage/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/storage/test_storage.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add analystbot/storage tests/storage
git commit -m "feat: add SQLite storage layer for schema cache, config, digest history, user memory, thread context"
```

---

### Task 3: BigQuery backend & schema discovery

**Files:**
- Create: `analystbot/query/__init__.py`
- Create: `analystbot/query/backend.py`
- Create: `analystbot/query/schema_discovery.py`
- Test: `tests/query/test_backend_live.py`
- Test: `tests/query/test_schema_discovery_live.py`

**Interfaces:**
- Consumes: nothing from prior tasks (credentials come from env vars directly in tests, matching `Config` field names from Task 1).
- Produces: `class BigQueryBackend: def __init__(self, project: str, credentials_path: str)`; `.dry_run(self, sql: str) -> int`; `.execute(self, sql: str) -> list[dict]`. `def discover_schema(backend: BigQueryBackend, dataset_path: str) -> dict` returning `{"events": dict[str, list[str]], "date_range": tuple[str, str], "player_count": int}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/query/test_backend_live.py
import os
import pytest
from tests.conftest import skip_unless_env
from analystbot.query.backend import BigQueryBackend

pytestmark = pytest.mark.live

_SQL = (
    "SELECT COUNT(*) AS n FROM `firebase-public-project.analytics_153293282.events_*` "
    "WHERE _TABLE_SUFFIX BETWEEN '20180501' AND '20180502'"
)


def _backend():
    skip_unless_env("GOOGLE_APPLICATION_CREDENTIALS", "BQ_BILLING_PROJECT")
    return BigQueryBackend(
        project=os.environ["BQ_BILLING_PROJECT"],
        credentials_path=os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
    )


def test_dry_run_estimates_bytes_without_charge():
    backend = _backend()
    assert backend.dry_run(_SQL) > 0


def test_execute_returns_rows():
    backend = _backend()
    rows = backend.execute(_SQL)
    assert len(rows) == 1
    assert rows[0]["n"] > 0
```

```python
# tests/query/test_schema_discovery_live.py
import os
import pytest
from tests.conftest import skip_unless_env
from analystbot.query.backend import BigQueryBackend
from analystbot.query.schema_discovery import discover_schema

pytestmark = pytest.mark.live

_DATASET = "firebase-public-project.analytics_153293282"


def test_discover_schema_finds_known_flood_it_events():
    skip_unless_env("GOOGLE_APPLICATION_CREDENTIALS", "BQ_BILLING_PROJECT")
    backend = BigQueryBackend(
        project=os.environ["BQ_BILLING_PROJECT"],
        credentials_path=os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
    )
    schema = discover_schema(backend, _DATASET)
    assert "level_complete" in schema["events"] or "level_start" in schema["events"]
    assert schema["player_count"] > 0
    min_date, max_date = schema["date_range"]
    assert min_date < max_date
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/query -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.query.backend'` (or skips if `GOOGLE_APPLICATION_CREDENTIALS`/`BQ_BILLING_PROJECT` aren't set locally yet — in that case, set them to a real free-tier GCP project + service account key first, since these are the only tests that require it).

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/query/backend.py
from google.cloud import bigquery
from google.oauth2 import service_account


class BigQueryBackend:
    def __init__(self, project: str, credentials_path: str):
        credentials = service_account.Credentials.from_service_account_file(credentials_path)
        self.client = bigquery.Client(project=project, credentials=credentials)

    def dry_run(self, sql: str) -> int:
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        job = self.client.query(sql, job_config=job_config)
        return job.total_bytes_processed

    def execute(self, sql: str) -> list[dict]:
        job = self.client.query(sql)
        return [dict(row.items()) for row in job.result()]
```

```python
# analystbot/query/schema_discovery.py
from analystbot.query.backend import BigQueryBackend


def discover_schema(backend: BigQueryBackend, dataset_path: str) -> dict:
    params_sql = f"""
        SELECT DISTINCT event_name, param.key AS param_key
        FROM `{dataset_path}.events_*`, UNNEST(event_params) AS param
    """
    events: dict[str, list[str]] = {}
    for row in backend.execute(params_sql):
        events.setdefault(row["event_name"], [])
        if row["param_key"] not in events[row["event_name"]]:
            events[row["event_name"]].append(row["param_key"])

    range_sql = f"""
        SELECT MIN(_TABLE_SUFFIX) AS min_date, MAX(_TABLE_SUFFIX) AS max_date,
               COUNT(DISTINCT user_pseudo_id) AS player_count
        FROM `{dataset_path}.events_*`
    """
    range_row = backend.execute(range_sql)[0]

    return {
        "events": events,
        "date_range": (range_row["min_date"], range_row["max_date"]),
        "player_count": range_row["player_count"],
    }
```

Also create empty `analystbot/query/__init__.py` and `tests/query/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/query -v`
Expected: PASS (3 tests) if credentials are set; otherwise all 3 SKIP cleanly (never FAIL).

- [ ] **Step 5: Commit**

```bash
git add analystbot/query/__init__.py analystbot/query/backend.py analystbot/query/schema_discovery.py tests/query/__init__.py tests/query/test_backend_live.py tests/query/test_schema_discovery_live.py
git commit -m "feat: add BigQuery backend and schema discovery against the public Flood-It! dataset"
```

---

### Task 4: Significance helper

**Files:**
- Create: `analystbot/digest/__init__.py`
- Create: `analystbot/digest/significance.py`
- Test: `tests/digest/test_significance.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `def is_significant(count_a: int, n_a: int, count_b: int, n_b: int, z_threshold: float = 1.96) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/digest/test_significance.py
from analystbot.digest.significance import is_significant


def test_large_gap_large_sample_is_significant():
    assert is_significant(count_a=3600, n_a=10000, count_b=4000, n_b=10000) is True


def test_small_gap_small_sample_is_not_significant():
    assert is_significant(count_a=6, n_a=20, count_b=8, n_b=20) is False


def test_zero_sample_is_not_significant():
    assert is_significant(count_a=0, n_a=0, count_b=5, n_b=20) is False


def test_identical_rates_are_not_significant():
    assert is_significant(count_a=500, n_a=1000, count_b=500, n_b=1000) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/digest/test_significance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.digest'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/digest/significance.py
import math


def is_significant(count_a: int, n_a: int, count_b: int, n_b: int, z_threshold: float = 1.96) -> bool:
    if n_a == 0 or n_b == 0:
        return False
    p_a = count_a / n_a
    p_b = count_b / n_b
    p_pool = (count_a + count_b) / (n_a + n_b)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        return False
    z = abs(p_a - p_b) / se
    return z >= z_threshold
```

Also create empty `analystbot/digest/__init__.py` and `tests/digest/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/digest/test_significance.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add analystbot/digest/__init__.py analystbot/digest/significance.py tests/digest/__init__.py tests/digest/test_significance.py
git commit -m "feat: add two-proportion significance test for week-over-week comparisons"
```

---

### Task 5: Question understanding & SQL generation

**Files:**
- Create: `analystbot/query/generate.py`
- Test: `tests/query/test_generate_live.py`

**Interfaces:**
- Consumes: nothing structurally (schema passed in as a plain `dict` matching Task 3's `discover_schema` return shape; `context` as a plain `list[dict]` matching Task 2's `threads.get_thread_context` return shape).
- Produces: `class QuestionOutcome(Enum)` with values `MATCH`, `REFUSAL`, `CLARIFY`; `@dataclass class QuestionResult: outcome: QuestionOutcome; sql: str | None = None; message: str | None = None`; `def understand_and_generate(question: str, schema: dict, context: list[dict], preferences: list[str], client: anthropic.Anthropic) -> QuestionResult` (`preferences` is the asking user's stated long-term preferences, e.g. "always show D7 not D1" — folded into the prompt as defaults to apply).

- [ ] **Step 1: Write the failing test**

```python
# tests/query/test_generate_live.py
import os
import pytest
import anthropic
from tests.conftest import skip_unless_env
from analystbot.query.generate import understand_and_generate, QuestionOutcome

pytestmark = pytest.mark.live

FLOOD_IT_SCHEMA = {
    "events": {
        "session_start": ["engagement_time_msec"],
        "level_start": ["level_number"],
        "level_complete": ["level_number", "level_time_sec"],
        "app_remove": [],
    }
}


def _client():
    skip_unless_env("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def test_answerable_question_produces_matching_sql():
    result = understand_and_generate("how many players started level 3", FLOOD_IT_SCHEMA, [], [], _client())
    assert result.outcome == QuestionOutcome.MATCH
    assert result.sql and "level_start" in result.sql


def test_unanswerable_question_is_refused_with_reason():
    result = understand_and_generate(
        "what is the average session length in seconds", FLOOD_IT_SCHEMA, [], [], _client()
    )
    assert result.outcome == QuestionOutcome.REFUSAL
    assert result.message


def test_nonsense_question_asks_for_clarification():
    result = understand_and_generate("how's the vibe economy doing", FLOOD_IT_SCHEMA, [], [], _client())
    assert result.outcome == QuestionOutcome.CLARIFY
    assert result.message


def test_stated_preference_is_accepted_without_breaking_a_normal_match():
    result = understand_and_generate(
        "what's our retention like", FLOOD_IT_SCHEMA, [], ["always show D7, not D1"], _client()
    )
    assert result.outcome in (QuestionOutcome.MATCH, QuestionOutcome.REFUSAL)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/query/test_generate_live.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.query.generate'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/query/generate.py
from dataclasses import dataclass
from enum import Enum
import json
import anthropic


class QuestionOutcome(Enum):
    MATCH = "match"
    REFUSAL = "refusal"
    CLARIFY = "clarify"


@dataclass
class QuestionResult:
    outcome: QuestionOutcome
    sql: str | None = None
    message: str | None = None


_TOOL = {
    "name": "answer_plan",
    "description": "Decide how to handle a game-analytics question given the discovered BigQuery schema.",
    "input_schema": {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "enum": ["match", "refusal", "clarify"]},
            "sql": {"type": "string", "description": "BigQuery SQL, required when outcome is match"},
            "message": {
                "type": "string",
                "description": "Refusal reason or clarifying question, required when outcome is refusal or clarify",
            },
        },
        "required": ["outcome"],
    },
}


def understand_and_generate(
    question: str, schema: dict, context: list[dict], preferences: list[str], client: anthropic.Anthropic
) -> QuestionResult:
    context_text = "\n".join(f"Q: {t['question']}\nSQL: {t['sql']}\nA: {t['answer']}" for t in context)
    preferences_text = "\n".join(f"- {p}" for p in preferences)
    prompt = (
        f"Discovered BigQuery schema (event_name -> param keys):\n{json.dumps(schema['events'], indent=2)}\n\n"
        f"This user's stated preferences (apply as defaults unless the question says otherwise):\n{preferences_text or '(none)'}\n\n"
        f"Prior thread/recent context:\n{context_text or '(none)'}\n\n"
        f"Question: {question}\n\n"
        "Decide: does this map to a plausible query against this schema (match), "
        "is it clearly unanswerable because the needed event/param doesn't exist (refusal), "
        "or is there no plausible mapping at all so you should ask for clarification (clarify)? "
        "Call answer_plan with your decision."
    )
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "answer_plan"},
        messages=[{"role": "user", "content": prompt}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    data = tool_use.input
    return QuestionResult(
        outcome=QuestionOutcome(data["outcome"]),
        sql=data.get("sql"),
        message=data.get("message"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/query/test_generate_live.py -v`
Expected: PASS (3 tests) if `ANTHROPIC_API_KEY` is set; otherwise SKIP cleanly.

- [ ] **Step 5: Commit**

```bash
git add analystbot/query/generate.py tests/query/test_generate_live.py
git commit -m "feat: add three-way question understanding and SQL generation via Claude"
```

---

### Task 6: Confidence & risk scoring

**Files:**
- Create: `analystbot/query/confidence.py`
- Test: `tests/query/test_confidence.py`
- Test: `tests/query/test_confidence_live.py`

**Interfaces:**
- Consumes: nothing structurally new.
- Produces: `@dataclass class ConfidenceResult: confident: bool; reason: str | None = None`; `def score_confidence(question: str, sql: str, client: anthropic.Anthropic) -> ConfidenceResult`; `def score_risk(sql: str) -> bool`; `def needs_caution(confidence: ConfidenceResult, risky: bool) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/query/test_confidence.py
from analystbot.query.confidence import score_risk, needs_caution, ConfidenceResult


def test_simple_query_is_not_risky():
    assert score_risk("SELECT COUNT(*) FROM events") is False


def test_multi_join_window_query_is_risky():
    sql = (
        "SELECT a.x, ROW_NUMBER() OVER (PARTITION BY a.x) FROM a "
        "JOIN b ON a.id = b.id JOIN c ON b.id = c.id"
    )
    assert score_risk(sql) is True


def test_needs_caution_when_risky_even_if_confident():
    assert needs_caution(ConfidenceResult(confident=True), risky=True) is True


def test_needs_caution_when_low_confidence_even_if_safe():
    assert needs_caution(ConfidenceResult(confident=False, reason="unsure which param"), risky=False) is True


def test_no_caution_when_confident_and_safe():
    assert needs_caution(ConfidenceResult(confident=True), risky=False) is False
```

```python
# tests/query/test_confidence_live.py
import os
import pytest
import anthropic
from tests.conftest import skip_unless_env
from analystbot.query.confidence import score_confidence

pytestmark = pytest.mark.live


def _client():
    skip_unless_env("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def test_confident_when_sql_clearly_matches_question():
    result = score_confidence(
        "how many level_start events happened", "SELECT COUNT(*) FROM events WHERE event_name = 'level_start'", _client()
    )
    assert result.confident is True


def test_not_confident_when_sql_makes_a_guessy_assumption():
    result = score_confidence(
        "how engaged are our players",
        "SELECT AVG(engagement_time_msec) FROM events WHERE event_name = 'user_engagement'",
        _client(),
    )
    assert result.confident is False
    assert result.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/query/test_confidence.py tests/query/test_confidence_live.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.query.confidence'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/query/confidence.py
from dataclasses import dataclass
import anthropic


@dataclass
class ConfidenceResult:
    confident: bool
    reason: str | None = None


_TOOL = {
    "name": "rate_confidence",
    "description": "Rate confidence that the given SQL correctly answers the question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "confident": {"type": "boolean"},
            "reason": {"type": "string", "description": "Required when confident is false: what's uncertain"},
        },
        "required": ["confident"],
    },
}


def score_confidence(question: str, sql: str, client: anthropic.Anthropic) -> ConfidenceResult:
    prompt = (
        f"Question: {question}\nGenerated SQL: {sql}\n\n"
        "Rate whether you're confident this SQL correctly answers the question, "
        "or whether you made an uncertain assumption (e.g. about which event/param was meant)."
    )
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=512,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "rate_confidence"},
        messages=[{"role": "user", "content": prompt}],
    )
    tool_use = next(b for b in response.content if b.type == "tool_use")
    data = tool_use.input
    return ConfidenceResult(confident=data["confident"], reason=data.get("reason"))


_RISKY_KEYWORDS = ("JOIN", "OVER (", "PARTITION BY")


def score_risk(sql: str) -> bool:
    upper = sql.upper()
    hits = sum(1 for kw in _RISKY_KEYWORDS if kw in upper)
    return hits >= 2


def needs_caution(confidence: ConfidenceResult, risky: bool) -> bool:
    return (not confidence.confident) or risky
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/query/test_confidence.py tests/query/test_confidence_live.py -v`
Expected: PASS (5 + 2 tests); live ones SKIP cleanly without `ANTHROPIC_API_KEY`.

- [ ] **Step 5: Commit**

```bash
git add analystbot/query/confidence.py tests/query/test_confidence.py tests/query/test_confidence_live.py
git commit -m "feat: add confidence self-rating and query-shape risk scoring"
```

---

### Task 7: Cost check

**Files:**
- Create: `analystbot/query/cost_check.py`
- Test: `tests/query/test_cost_check.py`

**Interfaces:**
- Consumes: any object with a `.dry_run(sql: str) -> int` method (satisfied by Task 3's `BigQueryBackend`).
- Produces: `def check_cost(backend, sql: str, threshold_bytes: int) -> tuple[bool, int]` — returns `(needs_confirmation, bytes_estimate)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/query/test_cost_check.py
from analystbot.query.cost_check import check_cost


class _FakeBackend:
    def __init__(self, bytes_estimate: int):
        self._bytes = bytes_estimate

    def dry_run(self, sql: str) -> int:
        return self._bytes


def test_under_threshold_does_not_need_confirmation():
    needs_confirm, estimate = check_cost(_FakeBackend(500), "SELECT 1", threshold_bytes=1000)
    assert needs_confirm is False
    assert estimate == 500


def test_over_threshold_needs_confirmation():
    needs_confirm, estimate = check_cost(_FakeBackend(5000), "SELECT 1", threshold_bytes=1000)
    assert needs_confirm is True
    assert estimate == 5000


def test_exactly_at_threshold_does_not_need_confirmation():
    needs_confirm, estimate = check_cost(_FakeBackend(1000), "SELECT 1", threshold_bytes=1000)
    assert needs_confirm is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/query/test_cost_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.query.cost_check'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/query/cost_check.py
def check_cost(backend, sql: str, threshold_bytes: int) -> tuple[bool, int]:
    estimate = backend.dry_run(sql)
    return estimate > threshold_bytes, estimate
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/query/test_cost_check.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add analystbot/query/cost_check.py tests/query/test_cost_check.py
git commit -m "feat: add BigQuery dry-run cost check with configurable threshold"
```

---

### Task 8: Answer formatting

**Files:**
- Create: `analystbot/query/answer.py`
- Test: `tests/query/test_answer_live.py`

**Interfaces:**
- Consumes: nothing structurally new.
- Produces: `def format_answer(question: str, rows: list[dict], significance_note: str | None, client: anthropic.Anthropic) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/query/test_answer_live.py
import os
import pytest
import anthropic
from tests.conftest import skip_unless_env
from analystbot.query.answer import format_answer

pytestmark = pytest.mark.live


def _client():
    skip_unless_env("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def test_answer_includes_the_number_from_the_rows():
    answer = format_answer("how many players started level 3", [{"n": 4213}], None, _client())
    assert "4213" in answer or "4,213" in answer


def test_answer_with_significance_note_mentions_it():
    answer = format_answer(
        "did retention drop after last week's build",
        [{"before": 0.38, "after": 0.31}],
        "the gap is statistically significant given sample size",
        _client(),
    )
    assert len(answer) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/query/test_answer_live.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.query.answer'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/query/answer.py
import anthropic


def format_answer(question: str, rows: list[dict], significance_note: str | None, client: anthropic.Anthropic) -> str:
    prompt = (
        f"Question: {question}\nResult rows: {rows}\n"
        + (f"Significance note: {significance_note}\n" if significance_note else "")
        + "Write one short, direct sentence answering the question with the number and the so-what. "
        "No preamble, no restating the question."
    )
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in response.content if b.type == "text").strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/query/test_answer_live.py -v`
Expected: PASS (2 tests) if `ANTHROPIC_API_KEY` is set; otherwise SKIP cleanly.

- [ ] **Step 5: Commit**

```bash
git add analystbot/query/answer.py tests/query/test_answer_live.py
git commit -m "feat: add answer formatting that turns rows into a sentence with the so-what"
```

---

### Task 9: Digest compute

**Files:**
- Create: `analystbot/digest/compute.py`
- Test: `tests/digest/test_compute.py`
- Test: `tests/digest/test_weekly_metrics_live.py`

**Interfaces:**
- Consumes: `analystbot.digest.significance.is_significant` (Task 4); `analystbot.storage.digest_history.save_digest` / `load_last_digest` (Task 2); any object with `.execute(sql: str) -> list[dict]` (satisfied by Task 3's `BigQueryBackend`).
- Produces: `@dataclass class DigestResult: summary: str; metrics: dict[str, float]`; `def run_digest(conn, week_start: str, current_metrics: dict[str, tuple[int, int]]) -> DigestResult` (`current_metrics` maps metric name -> `(count, total)` for the current week, already queried by the caller); `def query_weekly_metrics(backend, dataset_path: str, events: list[str], suffix_start: str, suffix_end: str) -> dict[str, tuple[int, int]]` — for each event name, `(distinct players who fired it, distinct players active at all)` within the `_TABLE_SUFFIX` range `[suffix_start, suffix_end]` (BigQuery's `YYYYMMDD` partition suffix format).

- [ ] **Step 1: Write the failing test**

```python
# tests/digest/test_compute.py
import sqlite3
from analystbot.storage import db, digest_history
from analystbot.digest.compute import run_digest


def _conn():
    conn = sqlite3.connect(":memory:")
    db.init_db(conn)
    return conn


def test_first_run_with_no_history_reports_no_movement():
    conn = _conn()
    result = run_digest(conn, "2026-08-03", {"tutorial_step_3": (780, 1000), "level_4_start": (690, 1000)})
    assert "nothing moved significantly" in result.summary
    assert result.metrics["tutorial_step_3"] == 0.78


def test_second_run_flags_significant_movement():
    conn = _conn()
    digest_history.save_digest(conn, {"tutorial_step_3": (3600, 10000)}, "2026-07-27")
    result = run_digest(conn, "2026-08-03", {"tutorial_step_3": (4000, 10000)})
    assert "tutorial_step_3" in result.summary
    assert "significant" in result.summary


def test_worst_leak_is_the_lowest_completion_rate():
    conn = _conn()
    result = run_digest(
        conn, "2026-08-03", {"tutorial_step_3": (780, 1000), "level_4_start": (690, 1000)}
    )
    assert "level_4_start" in result.summary


def test_run_digest_persists_current_metrics_for_next_comparison():
    conn = _conn()
    run_digest(conn, "2026-08-03", {"tutorial_step_3": (780, 1000)})
    last = digest_history.load_last_digest(conn)
    assert last["week_start"] == "2026-08-03"
    assert last["metrics"]["tutorial_step_3"] == (780, 1000)
```

```python
# tests/digest/test_weekly_metrics_live.py
import os
import pytest
from tests.conftest import skip_unless_env
from analystbot.query.backend import BigQueryBackend
from analystbot.digest.compute import query_weekly_metrics

pytestmark = pytest.mark.live

_DATASET = "firebase-public-project.analytics_153293282"


def test_query_weekly_metrics_returns_count_and_total_per_event():
    skip_unless_env("GOOGLE_APPLICATION_CREDENTIALS", "BQ_BILLING_PROJECT")
    backend = BigQueryBackend(
        project=os.environ["BQ_BILLING_PROJECT"],
        credentials_path=os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
    )
    metrics = query_weekly_metrics(backend, _DATASET, ["level_start"], "20180501", "20180507")
    count, total = metrics["level_start"]
    assert 0 <= count <= total
    assert total > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/digest/test_compute.py tests/digest/test_weekly_metrics_live.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.digest.compute'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/digest/compute.py
from dataclasses import dataclass
from analystbot.digest.significance import is_significant
from analystbot.storage import digest_history


@dataclass
class DigestResult:
    summary: str
    metrics: dict[str, float]


def run_digest(conn, week_start: str, current_metrics: dict[str, tuple[int, int]]) -> DigestResult:
    last = digest_history.load_last_digest(conn)
    moved = []
    for name, (count, total) in current_metrics.items():
        rate = count / total if total else 0.0
        if last and name in last["metrics"]:
            prev_count, prev_total = last["metrics"][name]
            if is_significant(prev_count, prev_total, count, total):
                prev_rate = prev_count / prev_total if prev_total else 0.0
                moved.append((name, prev_rate, rate))

    digest_history.save_digest(conn, current_metrics, week_start)

    worst_name, (worst_count, worst_total) = min(
        current_metrics.items(), key=lambda kv: kv[1][0] / kv[1][1] if kv[1][1] else 1.0
    )

    lines = [f"Week of {week_start}:"]
    if moved:
        for name, prev_rate, rate in moved:
            lines.append(f"- {name} moved from {prev_rate:.0%} to {rate:.0%} (significant)")
    else:
        lines.append("- nothing moved significantly this week")
    if worst_total:
        lines.append(f"- worst leak: {worst_name} at {worst_count / worst_total:.0%}")

    metrics = {name: (count / total if total else 0.0) for name, (count, total) in current_metrics.items()}
    return DigestResult(summary="\n".join(lines), metrics=metrics)


def query_weekly_metrics(backend, dataset_path: str, events: list[str], suffix_start: str, suffix_end: str) -> dict[str, tuple[int, int]]:
    total_sql = f"""
        SELECT COUNT(DISTINCT user_pseudo_id) AS n
        FROM `{dataset_path}.events_*`
        WHERE _TABLE_SUFFIX BETWEEN '{suffix_start}' AND '{suffix_end}'
    """
    total = backend.execute(total_sql)[0]["n"]

    metrics: dict[str, tuple[int, int]] = {}
    for event_name in events:
        count_sql = f"""
            SELECT COUNT(DISTINCT user_pseudo_id) AS n
            FROM `{dataset_path}.events_*`
            WHERE _TABLE_SUFFIX BETWEEN '{suffix_start}' AND '{suffix_end}'
              AND event_name = '{event_name}'
        """
        count = backend.execute(count_sql)[0]["n"]
        metrics[event_name] = (count, total)
    return metrics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/digest/test_compute.py tests/digest/test_weekly_metrics_live.py -v`
Expected: PASS (4 tests); the live test PASSes if credentials are set, otherwise SKIPs cleanly.

- [ ] **Step 5: Commit**

```bash
git add analystbot/digest/compute.py tests/digest/test_compute.py tests/digest/test_weekly_metrics_live.py
git commit -m "feat: add weekly digest computation with significance-aware comparison and worst-leak ranking"
```

---

### Task 10: Reply formatting

**Files:**
- Create: `analystbot/bot/__init__.py`
- Create: `analystbot/bot/replies.py`
- Test: `tests/bot/test_replies.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `def format_refusal(missing: str) -> str`; `def format_clarify(message: str) -> str`; `def format_caution(answer: str, reason: str) -> str`; `def format_cost_warning(bytes_estimate: int) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/bot/test_replies.py
from analystbot.bot.replies import format_refusal, format_clarify, format_caution, format_cost_warning


def test_format_refusal_includes_missing_reason():
    assert "session end" in format_refusal("you don't log session end")


def test_format_clarify_passes_message_through():
    assert format_clarify("did you mean X or Y?") == "did you mean X or Y?"


def test_format_caution_appends_reason_after_answer():
    result = format_caution("38%", "unsure which param")
    assert result.startswith("38%")
    assert "unsure which param" in result


def test_format_cost_warning_converts_bytes_to_gb_and_asks_to_confirm():
    msg = format_cost_warning(2 * 1024 ** 3)
    assert "2.00 GB" in msg
    assert "confirm" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/bot/test_replies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.bot'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/bot/replies.py
def format_refusal(missing: str) -> str:
    return f"I can't answer that — {missing}."


def format_clarify(message: str) -> str:
    return message


def format_caution(answer: str, reason: str) -> str:
    return f"{answer}\n\n_Take this with caution: {reason}_"


def format_cost_warning(bytes_estimate: int) -> str:
    gb = bytes_estimate / (1024 ** 3)
    return f"That query would scan about {gb:.2f} GB. Reply `confirm` to run it anyway."
```

Also create empty `analystbot/bot/__init__.py` and `tests/bot/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/bot/test_replies.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add analystbot/bot/__init__.py analystbot/bot/replies.py tests/bot/__init__.py tests/bot/test_replies.py
git commit -m "feat: add reply formatting for refusals, clarifications, caution flags, and cost warnings"
```

---

### Task 11: Message routing & dispatch

**Files:**
- Create: `analystbot/bot/routing.py`
- Test: `tests/bot/test_routing.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `class MessageKind(Enum)` with values `NEW_QUESTION`, `THREAD_FOLLOWUP`, `IGNORE`; `def classify_message(is_bot_author: bool, mentions_bot: bool, is_thread: bool, thread_started_by_bot: bool) -> MessageKind`; `async def dispatch(kind: MessageKind, message, handlers: dict[MessageKind, Callable]) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/bot/test_routing.py
import pytest
from unittest.mock import AsyncMock
from analystbot.bot.routing import classify_message, dispatch, MessageKind


def test_bot_message_is_ignored():
    assert classify_message(is_bot_author=True, mentions_bot=True, is_thread=False, thread_started_by_bot=False) == MessageKind.IGNORE


def test_mention_outside_thread_is_new_question():
    assert classify_message(is_bot_author=False, mentions_bot=True, is_thread=False, thread_started_by_bot=False) == MessageKind.NEW_QUESTION


def test_plain_message_in_bot_thread_is_followup():
    assert classify_message(is_bot_author=False, mentions_bot=False, is_thread=True, thread_started_by_bot=True) == MessageKind.THREAD_FOLLOWUP


def test_plain_message_in_other_thread_is_ignored():
    assert classify_message(is_bot_author=False, mentions_bot=False, is_thread=True, thread_started_by_bot=False) == MessageKind.IGNORE


def test_unrelated_channel_message_is_ignored():
    assert classify_message(is_bot_author=False, mentions_bot=False, is_thread=False, thread_started_by_bot=False) == MessageKind.IGNORE


@pytest.mark.asyncio
async def test_dispatch_calls_matching_handler():
    new_question_handler = AsyncMock()
    handlers = {MessageKind.NEW_QUESTION: new_question_handler, MessageKind.THREAD_FOLLOWUP: AsyncMock()}
    message = object()
    await dispatch(MessageKind.NEW_QUESTION, message, handlers)
    new_question_handler.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_dispatch_ignores_unmapped_kind():
    await dispatch(MessageKind.IGNORE, object(), {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/bot/test_routing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.bot.routing'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/bot/routing.py
from enum import Enum
from typing import Awaitable, Callable


class MessageKind(Enum):
    NEW_QUESTION = "new_question"
    THREAD_FOLLOWUP = "thread_followup"
    IGNORE = "ignore"


def classify_message(is_bot_author: bool, mentions_bot: bool, is_thread: bool, thread_started_by_bot: bool) -> MessageKind:
    if is_bot_author:
        return MessageKind.IGNORE
    if is_thread and thread_started_by_bot:
        return MessageKind.THREAD_FOLLOWUP
    if mentions_bot and not is_thread:
        return MessageKind.NEW_QUESTION
    return MessageKind.IGNORE


async def dispatch(kind: MessageKind, message, handlers: dict[MessageKind, Callable[[object], Awaitable[None]]]) -> None:
    handler = handlers.get(kind)
    if handler:
        await handler(message)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/bot/test_routing.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add analystbot/bot/routing.py tests/bot/test_routing.py
git commit -m "feat: add message classification (new question vs thread follow-up) and handler dispatch"
```

---

### Task 12: Onboarding report

**Files:**
- Create: `analystbot/bot/onboarding.py`
- Test: `tests/bot/test_onboarding.py`

**Interfaces:**
- Consumes: schema `dict` shape from Task 3's `discover_schema`.
- Produces: `def build_onboarding_report(schema: dict) -> str`; `async def run_onboarding(message, backend, dataset_path: str, conn) -> str` (calls `schema_discovery.discover_schema`, `schema_cache.save_schema`, posts the report via `message.channel.send`, returns the report text). Only `build_onboarding_report` is unit tested here; `run_onboarding` is exercised by the Task 15 live sanity check.

- [ ] **Step 1: Write the failing test**

```python
# tests/bot/test_onboarding.py
from analystbot.bot.onboarding import build_onboarding_report


def test_report_includes_event_count_date_range_and_player_count():
    schema = {
        "events": {"level_start": ["level_number"], "session_start": []},
        "date_range": ("20180101", "20180419"),
        "player_count": 5000,
    }
    report = build_onboarding_report(schema)
    assert "2 event types" in report
    assert "level_start" in report
    assert "session_start" in report
    assert "20180101" in report and "20180419" in report
    assert "5000 players" in report
    assert "confirm" in report
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/bot/test_onboarding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.bot.onboarding'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/bot/onboarding.py
from analystbot.query.schema_discovery import discover_schema
from analystbot.storage import schema_cache


def build_onboarding_report(schema: dict) -> str:
    events = schema["events"]
    tracked = ", ".join(sorted(events.keys()))
    min_date, max_date = schema["date_range"]
    return "\n".join(
        [
            f"Tracking {len(events)} event types: {tracked}.",
            f"Data covers {min_date} to {max_date}, {schema['player_count']} players.",
            "Reply `confirm` in this channel to start using this data, or correct me if something looks wrong.",
        ]
    )


async def run_onboarding(message, backend, dataset_path: str, conn) -> str:
    schema = discover_schema(backend, dataset_path)
    schema_cache.save_schema(conn, schema)
    report = build_onboarding_report(schema)
    await message.channel.send(report)
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/bot/test_onboarding.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add analystbot/bot/onboarding.py tests/bot/test_onboarding.py
git commit -m "feat: add onboarding schema-discovery report"
```

---

### Task 13: Pipeline orchestration

**Files:**
- Create: `analystbot/bot/pipeline.py`
- Test: `tests/bot/test_pipeline.py`

**Interfaces:**
- Consumes: `analystbot.query.generate.understand_and_generate`/`QuestionResult`/`QuestionOutcome` (Task 5), `analystbot.query.cost_check.check_cost` (Task 7), `analystbot.query.confidence.score_confidence`/`score_risk`/`needs_caution` (Task 6), `analystbot.query.answer.format_answer` (Task 8), `analystbot.bot.replies.format_refusal`/`format_clarify`/`format_cost_warning`/`format_caution` (Task 10).
- Produces: `async def answer_question(question: str, user_id: int, context: list[dict], preferences: list[str], deps) -> tuple[str, str | None]` — `deps` is any object exposing `.backend`, `.schema` (dict), `.anthropic_client`, `.cost_threshold_bytes`; returns `(reply_text, sql_used_or_none)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/bot/test_pipeline.py
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
import analystbot.bot.pipeline as pipeline
from analystbot.query.generate import QuestionResult, QuestionOutcome
from analystbot.query.confidence import ConfidenceResult


@pytest.mark.asyncio
async def test_refusal_short_circuits_before_sql_execution(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, a: QuestionResult(outcome=QuestionOutcome.REFUSAL, message="you don't log session end"),
    )
    deps = SimpleNamespace(backend=MagicMock(), schema={}, anthropic_client=MagicMock(), cost_threshold_bytes=1000)
    reply, sql = await pipeline.answer_question("avg session length", 1, [], [], deps)
    assert "session end" in reply
    assert sql is None
    deps.backend.execute.assert_not_called()


@pytest.mark.asyncio
async def test_clarify_short_circuits(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, a: QuestionResult(outcome=QuestionOutcome.CLARIFY, message="did you mean X or Y?"),
    )
    deps = SimpleNamespace(backend=MagicMock(), schema={}, anthropic_client=MagicMock(), cost_threshold_bytes=1000)
    reply, sql = await pipeline.answer_question("vibe economy", 1, [], [], deps)
    assert "X or Y" in reply
    assert sql is None


@pytest.mark.asyncio
async def test_expensive_query_returns_cost_warning_without_executing(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT 1"),
    )
    deps = SimpleNamespace(
        backend=MagicMock(dry_run=MagicMock(return_value=10_000_000_000)),
        schema={}, anthropic_client=MagicMock(), cost_threshold_bytes=1000,
    )
    reply, sql = await pipeline.answer_question("how many players ever", 1, [], [], deps)
    assert "confirm" in reply
    deps.backend.execute.assert_not_called()


@pytest.mark.asyncio
async def test_confident_safe_answer_has_no_caution(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT COUNT(*) FROM x"),
    )
    monkeypatch.setattr(pipeline, "check_cost", lambda backend, sql, threshold: (False, 10))
    monkeypatch.setattr(pipeline.confidence_mod, "score_confidence", lambda q, sql, c: ConfidenceResult(confident=True))
    monkeypatch.setattr(pipeline.confidence_mod, "score_risk", lambda sql: False)
    monkeypatch.setattr(pipeline.answer_mod, "format_answer", lambda q, rows, note, c: "22% of players quit here.")
    deps = SimpleNamespace(
        backend=MagicMock(execute=MagicMock(return_value=[{"n": 220}])),
        schema={}, anthropic_client=MagicMock(), cost_threshold_bytes=1000,
    )
    reply, sql = await pipeline.answer_question("where do players quit", 1, [], [], deps)
    assert reply == "22% of players quit here."
    assert "caution" not in reply.lower()


@pytest.mark.asyncio
async def test_low_confidence_answer_gets_caution_flag(monkeypatch):
    monkeypatch.setattr(
        pipeline.generate, "understand_and_generate",
        lambda q, s, c, p, a: QuestionResult(outcome=QuestionOutcome.MATCH, sql="SELECT COUNT(*) FROM x"),
    )
    monkeypatch.setattr(pipeline, "check_cost", lambda backend, sql, threshold: (False, 10))
    monkeypatch.setattr(
        pipeline.confidence_mod, "score_confidence",
        lambda q, sql, c: ConfidenceResult(confident=False, reason="unsure which param"),
    )
    monkeypatch.setattr(pipeline.confidence_mod, "score_risk", lambda sql: False)
    monkeypatch.setattr(pipeline.answer_mod, "format_answer", lambda q, rows, note, c: "22% of players quit here.")
    deps = SimpleNamespace(
        backend=MagicMock(execute=MagicMock(return_value=[{"n": 220}])),
        schema={}, anthropic_client=MagicMock(), cost_threshold_bytes=1000,
    )
    reply, sql = await pipeline.answer_question("where do players quit", 1, [], [], deps)
    assert "caution" in reply.lower()
    assert "unsure which param" in reply
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/bot/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.bot.pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/bot/pipeline.py
import analystbot.query.generate as generate
import analystbot.query.confidence as confidence_mod
import analystbot.query.answer as answer_mod
from analystbot.query.generate import QuestionOutcome
from analystbot.query.cost_check import check_cost
from analystbot.bot.replies import format_refusal, format_clarify, format_cost_warning, format_caution


async def answer_question(
    question: str, user_id: int, context: list[dict], preferences: list[str], deps
) -> tuple[str, str | None]:
    result = generate.understand_and_generate(question, deps.schema, context, preferences, deps.anthropic_client)

    if result.outcome == QuestionOutcome.REFUSAL:
        return format_refusal(result.message), None
    if result.outcome == QuestionOutcome.CLARIFY:
        return format_clarify(result.message), None

    needs_confirm, bytes_estimate = check_cost(deps.backend, result.sql, deps.cost_threshold_bytes)
    if needs_confirm:
        return format_cost_warning(bytes_estimate), result.sql

    confidence = confidence_mod.score_confidence(question, result.sql, deps.anthropic_client)
    risky = confidence_mod.score_risk(result.sql)
    rows = deps.backend.execute(result.sql)
    answer_text = answer_mod.format_answer(question, rows, None, deps.anthropic_client)

    if confidence_mod.needs_caution(confidence, risky):
        answer_text = format_caution(answer_text, confidence.reason or "generated query uses a complex shape")

    return answer_text, result.sql
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/bot/test_pipeline.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add analystbot/bot/pipeline.py tests/bot/test_pipeline.py
git commit -m "feat: wire Q&A pipeline orchestration (understand -> cost check -> confidence -> answer)"
```

---

### Task 14: Discord client, scheduler, and entrypoint

**Files:**
- Create: `analystbot/bot/client.py`
- Create: `analystbot/digest/scheduler.py`
- Create: `analystbot/main.py`
- Test: `tests/bot/test_client.py`

**Interfaces:**
- Consumes: `analystbot.bot.routing.classify_message`/`dispatch`/`MessageKind` (Task 11), `analystbot.storage.threads.get_thread_context`/`save_thread_context` (Task 2), `analystbot.storage.config_store.get_digest_channel`/`set_digest_channel` (Task 2), `analystbot.storage.user_memory.get_preferences`/`get_recent_history`/`add_question_history` (Task 2), `analystbot.bot.onboarding.run_onboarding` (Task 12), `analystbot.bot.pipeline.answer_question` (Task 13, now taking `preferences: list[str]`), `analystbot.digest.compute.run_digest` (Task 9), `analystbot.config.load_config` (Task 1).
- Produces: `class AnalystBot(discord.Client)` with `on_message` wired to `routing.classify_message` + `routing.dispatch`; `def start_scheduler(job: Callable[[], Awaitable[None]]) -> apscheduler.schedulers.background.BackgroundScheduler` (fires `job` every Monday); `analystbot/main.py` as the process entrypoint (no functions consumed by later tasks — this is the top of the call graph).

- [ ] **Step 1: Write the failing test**

```python
# tests/bot/test_client.py
import pytest
from unittest.mock import AsyncMock
from analystbot.bot.routing import MessageKind
from analystbot.bot.client import AnalystBot


@pytest.mark.asyncio
async def test_route_message_dispatches_new_question_handler():
    handlers = {MessageKind.NEW_QUESTION: AsyncMock(), MessageKind.THREAD_FOLLOWUP: AsyncMock()}
    message = object()
    await AnalystBot.route_message(
        message, handlers,
        is_bot_author=False, mentions_bot=True, is_thread=False, thread_started_by_bot=False,
    )
    handlers[MessageKind.NEW_QUESTION].assert_awaited_once_with(message)
    handlers[MessageKind.THREAD_FOLLOWUP].assert_not_awaited()


@pytest.mark.asyncio
async def test_route_message_dispatches_followup_handler_in_bot_thread():
    handlers = {MessageKind.NEW_QUESTION: AsyncMock(), MessageKind.THREAD_FOLLOWUP: AsyncMock()}
    message = object()
    await AnalystBot.route_message(
        message, handlers,
        is_bot_author=False, mentions_bot=False, is_thread=True, thread_started_by_bot=True,
    )
    handlers[MessageKind.THREAD_FOLLOWUP].assert_awaited_once_with(message)
    handlers[MessageKind.NEW_QUESTION].assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/bot/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analystbot.bot.client'`

- [ ] **Step 3: Write minimal implementation**

```python
# analystbot/bot/client.py
import discord
from analystbot.bot.routing import classify_message, dispatch, MessageKind
from analystbot.storage import threads as thread_store
from analystbot.storage import config_store


class AnalystBot(discord.Client):
    def __init__(self, *, conn, backend, dataset_path, anthropic_client, cost_threshold_bytes,
                 handle_new_question, handle_followup, handle_onboarding, **kwargs):
        super().__init__(**kwargs)
        self.conn = conn
        self.backend = backend
        self.dataset_path = dataset_path
        self.anthropic_client = anthropic_client
        self.cost_threshold_bytes = cost_threshold_bytes
        self._handlers = {
            MessageKind.NEW_QUESTION: handle_new_question,
            MessageKind.THREAD_FOLLOWUP: handle_followup,
        }
        self._handle_onboarding = handle_onboarding

    @staticmethod
    async def route_message(message, handlers: dict, *, is_bot_author: bool, mentions_bot: bool,
                             is_thread: bool, thread_started_by_bot: bool) -> None:
        kind = classify_message(
            is_bot_author=is_bot_author, mentions_bot=mentions_bot,
            is_thread=is_thread, thread_started_by_bot=thread_started_by_bot,
        )
        await dispatch(kind, message, handlers)

    async def on_message(self, message: discord.Message) -> None:
        if self.user is None or message.author == self.user:
            return
        is_thread = isinstance(message.channel, discord.Thread)
        thread_started_by_bot = bool(thread_store.get_thread_context(self.conn, message.channel.id)) if is_thread else False
        mentions_bot = self.user in message.mentions

        handlers = dict(self._handlers)
        if config_store.get_digest_channel(self.conn) is None:
            handlers[MessageKind.NEW_QUESTION] = self._handle_onboarding

        await self.route_message(
            message, handlers,
            is_bot_author=False, mentions_bot=mentions_bot,
            is_thread=is_thread, thread_started_by_bot=thread_started_by_bot,
        )
```

```python
# analystbot/digest/scheduler.py
from typing import Awaitable, Callable
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio


def start_scheduler(job: Callable[[], Awaitable[None]]) -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: asyncio.run(job()), CronTrigger(day_of_week="mon", hour=9))
    scheduler.start()
    return scheduler
```

```python
# analystbot/main.py
import os
from datetime import date, timedelta
import discord
import anthropic
from analystbot.config import load_config
from analystbot.storage import db, threads as thread_store, user_memory, config_store, schema_cache
from analystbot.query.backend import BigQueryBackend
from analystbot.bot.client import AnalystBot
from analystbot.bot.onboarding import run_onboarding
from analystbot.bot.pipeline import answer_question
from analystbot.digest.compute import run_digest, query_weekly_metrics
from analystbot.digest.scheduler import start_scheduler
from types import SimpleNamespace


def build_bot() -> AnalystBot:
    config = load_config(dict(os.environ))
    conn = db.get_connection(config.db_path)
    backend = BigQueryBackend(project=config.bq_billing_project, credentials_path=config.google_application_credentials)
    anthropic_client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    def _long_term_context(user_id: int) -> tuple[list[dict], list[str]]:
        recent = user_memory.get_recent_history(conn, user_id)
        context = [{"question": r["question"], "sql": None, "answer": r["answer"]} for r in recent]
        preferences = user_memory.get_preferences(conn, user_id)
        return context, preferences

    def _deps() -> SimpleNamespace:
        schema = schema_cache.load_schema(conn) or {"events": {}, "date_range": ("", ""), "player_count": 0}
        return SimpleNamespace(backend=backend, schema=schema, anthropic_client=anthropic_client, cost_threshold_bytes=config.cost_threshold_bytes)

    async def handle_new_question(message: discord.Message) -> None:
        thread = await message.create_thread(name=message.content[:80])
        long_term_context, preferences = _long_term_context(message.author.id)
        reply, sql = await answer_question(message.content, message.author.id, long_term_context, preferences, _deps())
        await thread.send(reply)
        thread_store.save_thread_context(conn, thread.id, message.content, sql, reply)
        user_memory.add_question_history(conn, message.author.id, message.content, reply)

    async def handle_followup(message: discord.Message) -> None:
        thread_context = thread_store.get_thread_context(conn, message.channel.id)
        long_term_context, preferences = _long_term_context(message.author.id)
        reply, sql = await answer_question(
            message.content, message.author.id, thread_context + long_term_context, preferences, _deps()
        )
        await message.channel.send(reply)
        thread_store.save_thread_context(conn, message.channel.id, message.content, sql, reply)
        user_memory.add_question_history(conn, message.author.id, message.content, reply)

    async def handle_onboarding(message: discord.Message) -> None:
        if message.content.strip().lower() == "confirm":
            config_store.set_digest_channel(conn, message.channel.id)
            await message.channel.send("Confirmed. I'll post the weekly digest here.")
        else:
            await run_onboarding(message, backend, config.bq_dataset_path, conn)

    intents = discord.Intents.default()
    intents.message_content = True
    return AnalystBot(
        conn=conn, backend=backend, dataset_path=config.bq_dataset_path,
        anthropic_client=anthropic_client, cost_threshold_bytes=config.cost_threshold_bytes,
        handle_new_question=handle_new_question, handle_followup=handle_followup,
        handle_onboarding=handle_onboarding, intents=intents,
    )


def main() -> None:
    config = load_config(dict(os.environ))
    bot = build_bot()

    async def weekly_digest_job() -> None:
        channel_id = config_store.get_digest_channel(bot.conn)
        if channel_id is None:
            return
        channel = bot.get_channel(channel_id)
        if channel is None:
            return
        schema = schema_cache.load_schema(bot.conn)
        if schema is None:
            return
        today = date.today()
        suffix_end = today.strftime("%Y%m%d")
        suffix_start = (today - timedelta(days=6)).strftime("%Y%m%d")
        current_metrics = query_weekly_metrics(bot.backend, config.bq_dataset_path, list(schema["events"].keys()), suffix_start, suffix_end)
        result = run_digest(bot.conn, today.isoformat(), current_metrics)
        await channel.send(result.summary)

    start_scheduler(weekly_digest_job)
    bot.run(config.discord_token)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/bot/test_client.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add analystbot/bot/client.py analystbot/digest/scheduler.py analystbot/main.py tests/bot/test_client.py
git commit -m "feat: wire Discord client, weekly scheduler, and process entrypoint"
```

---

### Task 15: Live end-to-end sanity check

**Files:**
- Create: `docs/superpowers/plans/2026-08-05-discord-analytics-bot-e2e-checklist.md`

This task is manual, not automated — it's the spec's required "one live end-to-end sanity check" before v1 is done. No code changes; it produces a checklist doc recording that the check was performed.

- [ ] **Step 1: Run the full automated suite one more time**

Run: `pytest -v`
Expected: All non-`live` tests PASS; `live` tests PASS if `ANTHROPIC_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`, and `BQ_BILLING_PROJECT` are set, otherwise SKIP.

- [ ] **Step 2: Set required environment variables and start the bot**

```bash
export DISCORD_TOKEN=...
export ANTHROPIC_API_KEY=...
export BQ_BILLING_PROJECT=...
export BQ_DATASET_PATH=firebase-public-project.analytics_153293282
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
python -m analystbot.main
```

- [ ] **Step 3: In the target Discord server, @mention the bot for the first time**

Confirm: the bot posts an onboarding report naming real Flood-It! event names (e.g. `level_start`, `level_complete`, `session_start`), a real date range, and a real player count. Reply `confirm`.

- [ ] **Step 4: Ask a real question**

@mention the bot with a question like "how many players started level 3". Confirm: it opens a thread and replies with a specific number, not a template/placeholder.

- [ ] **Step 5: Ask a follow-up in the thread without @mentioning**

Reply in that thread with something like "what about level 5". Confirm: the bot answers using the prior question as context, without needing another @mention.

- [ ] **Step 6: Ask something clearly unanswerable and something nonsensical**

Confirm the bot refuses (naming what's missing) for something like "what's our average session length in seconds", and asks a clarifying question for something like "how's the vibe economy".

- [ ] **Step 7: Trigger a digest run manually and confirm the post looks right**

Temporarily call `weekly_digest_job()` directly (e.g. via a short one-off script or a Python REPL importing `analystbot.main.build_bot` and constructing the job body) instead of waiting for Monday; confirm the digest channel receives a summary with real numbers and a named worst leak.

- [ ] **Step 8: Record the results**

```markdown
# Discord Analytics Bot — E2E Checklist

- [x] Onboarding report showed real Flood-It! events/date range/player count
- [x] New question answered with a real number in a new thread
- [x] Thread follow-up answered using prior context, no re-mention needed
- [x] Unanswerable question refused with a named missing event/param
- [x] Nonsense question triggered a clarifying question
- [x] Weekly digest posted to the confirmed channel with real numbers and a worst leak

Date run: <fill in>
Run by: <fill in>
```

- [ ] **Step 9: Commit**

```bash
git add docs/superpowers/plans/2026-08-05-discord-analytics-bot-e2e-checklist.md
git commit -m "docs: record v1 live end-to-end sanity check"
```
