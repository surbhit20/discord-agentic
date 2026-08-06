"""Structural funnel-shape detection over a discovered event-name set.

Purely name-based, deliberately conservative: no semantic guessing about what an
event means, only what the naming convention implies (an event ending "_start" with
a matching "_complete"/"_end"/etc counterpart is a funnel pair; one without a match
is a gap). Shared by onboarding's gap detection and the digest's worst-leak ranking
so both draw the same conclusions from the same schema.
"""

# Suffixes that mark the opening of something that should also have a closing event.
# Deliberately excludes "_open"/"_opened": that suffix is the one Firebase/GA4 uses for
# automatic events with no completion concept at all (first_open, notification_open), so
# treating it as a funnel-start suffix produced fabricated gaps for events that were never
# a "start" of anything.
START_SUFFIXES = ("_start", "_started", "_begin", "_begun")
# Suffixes that count as a closing event for a given stem.
END_SUFFIXES = (
    "_complete", "_completed", "_end", "_ended", "_finish", "_finished",
    "_success", "_succeeded", "_fail", "_failed", "_quit", "_abandon", "_abandoned", "_close", "_closed",
)
# Automatic Firebase/GA4 events that never have a "completion" counterpart, no matter what
# they're named — belt-and-suspenders alongside dropping "_open" above, in case a future
# automatic event happens to end in one of the suffixes above.
AUTOMATIC_EVENTS_WITHOUT_COMPLETION = frozenset(
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


def find_funnel_pairs(events) -> list[tuple[str, str, str]]:
    """Return (stem, start_event, end_event) for every genuine funnel pair in `events`.

    A pair is "genuine" only when a real closing-suffix event exists for the same stem —
    no guessing, no partial matches. Automatic Firebase/GA4 events are never treated as a
    funnel start, since they have no completion concept regardless of their suffix.
    """
    names = set(events)
    pairs: list[tuple[str, str, str]] = []
    for name in sorted(names):
        if name in AUTOMATIC_EVENTS_WITHOUT_COMPLETION:
            continue
        stem = next((name[: -len(s)] for s in START_SUFFIXES if name.endswith(s)), None)
        if not stem:
            continue
        end = next((f"{stem}{suffix}" for suffix in END_SUFFIXES if f"{stem}{suffix}" in names), None)
        if end:
            pairs.append((stem, name, end))
    return pairs
