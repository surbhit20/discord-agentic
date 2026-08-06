import asyncio

from analystbot.query.schema_discovery import discover_schema
from analystbot.schema_funnels import AUTOMATIC_EVENTS_WITHOUT_COMPLETION, END_SUFFIXES, START_SUFFIXES
from analystbot.storage import schema_cache


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
        if name in AUTOMATIC_EVENTS_WITHOUT_COMPLETION:
            continue
        stem = next((name[: -len(s)] for s in START_SUFFIXES if name.endswith(s)), None)
        if not stem:
            continue
        if any(f"{stem}{end}" in names for end in END_SUFFIXES):
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


def _format_date(yyyymmdd: str) -> str:
    """`20180612` -> `2018-06-12`; passes through anything not in that exact shape."""
    if len(yyyymmdd) == 8 and yyyymmdd.isdigit():
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    return yyyymmdd


def build_onboarding_report(schema: dict) -> str:
    events = schema["events"]
    tracked = ", ".join(sorted(events.keys()))
    min_date, max_date = schema["date_range"]
    player_count = schema["player_count"]

    lines = [
        "**Setup complete — here's what I found**",
        "",
        f"**{player_count:,} players**, tracked from **{_format_date(min_date)}** to **{_format_date(max_date)}**.",
        "",
        f"**{len(events)} event types tracked:**",
        f"```\n{tracked}\n```",
    ]

    gaps = find_schema_gaps(events)
    if gaps:
        lines.append("")
        lines.append("**⚠️ Notable gaps:**")
        lines.extend(f"- {gap}" for gap in gaps)

    lines.append("")
    lines.append(
        "**Next step:** reply with `confirm` (make sure to @-mention me, since that's the only way "
        "I hear you outside my own threads) to start using this data, or tell me if something above "
        "looks wrong."
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
