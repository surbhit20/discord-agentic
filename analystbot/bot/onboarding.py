import asyncio

from analystbot.query.schema_discovery import discover_schema
from analystbot.storage import schema_cache


# Suffixes that mark the opening of something that should also have a closing event.
# Deliberately excludes "_open"/"_opened": that suffix is the one Firebase/GA4 uses for
# automatic events with no completion concept at all (first_open, notification_open), so
# treating it as a funnel-start suffix produced fabricated gaps for events that were never
# a "start" of anything.
_START_SUFFIXES = ("_start", "_started", "_begin", "_begun")
# Suffixes that count as a closing event for a given stem.
_END_SUFFIXES = (
    "_complete", "_completed", "_end", "_ended", "_finish", "_finished",
    "_success", "_succeeded", "_fail", "_failed", "_quit", "_abandon", "_abandoned", "_close", "_closed",
)
_ENGAGEMENT_EVENTS = ("session_end", "user_engagement", "app_remove", "screen_view")
# Automatic Firebase/GA4 events that never have a "completion" counterpart, no matter what
# they're named — belt-and-suspenders alongside dropping "_open" above, in case a future
# automatic event happens to end in one of the suffixes above.
_AUTOMATIC_EVENTS_WITHOUT_COMPLETION = frozenset(
    {
        "first_open",
        "app_open",
        "notification_open",
        "notification_receive",
        "notification_dismiss",
        "app_remove",
        "app_update",
        "os_update",
        "app_clear_data",
        "app_exception",
        "ad_impression",
        "ad_click",
        "ad_reward",
        "screen_view",
        "user_engagement",
    }
)
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
        if name in _AUTOMATIC_EVENTS_WITHOUT_COMPLETION:
            continue
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
