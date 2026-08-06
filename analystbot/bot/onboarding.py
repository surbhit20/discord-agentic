import asyncio

from analystbot.query.schema_discovery import discover_schema
from analystbot.storage import schema_cache


# Suffixes that mark the opening of something that should also have a closing event.
_START_SUFFIXES = ("_start", "_started", "_begin", "_begun", "_open", "_opened")
# Suffixes that count as a closing event for a given stem.
_END_SUFFIXES = (
    "_complete", "_completed", "_end", "_ended", "_finish", "_finished",
    "_success", "_succeeded", "_fail", "_failed", "_quit", "_abandon", "_abandoned", "_close", "_closed",
)
_ENGAGEMENT_EVENTS = ("session_end", "user_engagement", "app_remove", "screen_view")
_MAX_GAPS = 3


def find_schema_gaps(events: dict) -> list[str]:
    """Name concrete things this schema *can't* answer, derived only from event names.

    Purely structural, and deliberately conservative: it only reports gaps that are
    literally true of the event-name set it was handed (an opening event with no
    matching closing event; no engagement/session-end signal at all). No semantic
    guessing about what an event means.
    """
    names = set(events)
    gaps: list[str] = []

    for name in sorted(names):
        stem = next((name[: -len(s)] for s in _START_SUFFIXES if name.endswith(s)), None)
        if not stem:
            continue
        if any(f"{stem}{end}" in names for end in _END_SUFFIXES):
            continue
        if stem == "session":
            gaps.append(
                f"you track `{name}` but nothing that closes a session, so I can't tell you "
                "session length or how many sessions ended early"
            )
        else:
            gaps.append(
                f"you track `{name}` but no matching completion or failure event, so I can't tell "
                f"you {stem} completion or fail rates — only how many players started"
            )

    if not any(name in names for name in _ENGAGEMENT_EVENTS):
        gaps.append(
            "there's no session-end, engagement-time, or app-removal event, so I can't tell you "
            "playtime, session length, or churn"
        )

    return gaps[:_MAX_GAPS]


def build_onboarding_report(schema: dict) -> str:
    events = schema["events"]
    tracked = ", ".join(sorted(events.keys()))
    min_date, max_date = schema["date_range"]
    lines = [
        f"Tracking {len(events)} event types: {tracked}.",
        f"Data covers {min_date} to {max_date}, {schema['player_count']} players.",
    ]
    gaps = find_schema_gaps(events)
    if gaps:
        lines.append("Notable gaps:")
        lines.extend(f"- {gap}" for gap in gaps)
    lines.append(
        "Reply with `confirm` (mentioning me, since that's the only way I hear you outside my own "
        "threads) to start using this data, or correct me if something looks wrong."
    )
    return "\n".join(lines)


async def run_onboarding(message, backend, dataset_path: str, conn) -> str:
    # discover_schema runs two full-wildcard BigQuery scans; off the event loop it goes,
    # or the gateway heartbeat stalls for as long as they take. The SQLite write stays
    # on this thread (thread-affine connection).
    schema = await asyncio.to_thread(discover_schema, backend, dataset_path)
    schema_cache.save_schema(conn, schema)
    report = build_onboarding_report(schema)
    await message.channel.send(report)
    return report
