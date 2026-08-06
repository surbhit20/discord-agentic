from dataclasses import dataclass
from analystbot.digest.significance import is_significant
from analystbot.schema_funnels import find_funnel_pairs
from analystbot.storage import digest_history


@dataclass
class DigestResult:
    summary: str
    metrics: dict[str, float]


def _worst_funnel_leak(current_metrics: dict[str, tuple[int, int]]) -> tuple[str, str, str, float] | None:
    """The genuine funnel pair (stem, start_event, end_event) with the lowest completion
    rate — i.e. of players who started, the smallest fraction who finished.

    Deliberately restricted to detected start/end pairs rather than the raw participation
    rate across every tracked event: that used to surface things like a rare marketing
    event (`dynamic_link_first_open`) as the "worst leak" just because few players ever
    fire it, which isn't a drop-off at all. When no genuine funnel pair is present in this
    week's metrics, there is nothing honest to report — return None rather than falling
    back to a misleading pick.
    """
    candidates = []
    for stem, start_event, end_event in find_funnel_pairs(current_metrics.keys()):
        start_count, _ = current_metrics[start_event]
        end_count, _ = current_metrics[end_event]
        if start_count == 0:
            continue
        candidates.append((stem, start_event, end_event, end_count / start_count))
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[3])


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

    lines = [f"Week of {week_start}:"]
    if moved:
        for name, prev_rate, rate in moved:
            lines.append(f"- {name} moved from {prev_rate:.0%} to {rate:.0%} (significant)")
    else:
        lines.append("- nothing moved significantly this week")

    worst = _worst_funnel_leak(current_metrics)
    if worst is not None:
        stem, start_event, end_event, completion_rate = worst
        lines.append(
            f"- worst leak: {stem} — {start_event} → {end_event} at {completion_rate:.0%} completion"
        )

    metrics = {name: (count / total if total else 0.0) for name, (count, total) in current_metrics.items()}
    return DigestResult(summary="\n".join(lines), metrics=metrics)


def query_weekly_metrics(backend, dataset_path: str, events: list[str], suffix_start: str, suffix_end: str) -> dict[str, tuple[int, int]]:
    total_sql = f"""
        SELECT COUNT(DISTINCT user_pseudo_id) AS n
        FROM `{dataset_path}.events_*`
        WHERE _TABLE_SUFFIX BETWEEN '{suffix_start}' AND '{suffix_end}'
    """
    total = backend.execute(total_sql)[0]["n"]

    # One grouped query for every event, not one query per event: the digest previously
    # issued 1+N serial BigQuery jobs, which is both slow and needlessly expensive.
    per_event_sql = f"""
        SELECT event_name, COUNT(DISTINCT user_pseudo_id) AS n
        FROM `{dataset_path}.events_*`
        WHERE _TABLE_SUFFIX BETWEEN '{suffix_start}' AND '{suffix_end}'
        GROUP BY event_name
    """
    counts = {row["event_name"]: row["n"] for row in backend.execute(per_event_sql)}

    # Events that fired zero times in the window are absent from the grouped result;
    # they still belong in the digest as (0, total).
    return {event_name: (counts.get(event_name, 0), total) for event_name in events}
