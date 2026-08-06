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
