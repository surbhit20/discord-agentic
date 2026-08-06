from analystbot.digest.compute import query_weekly_metrics


class _FakeBackend:
    """Records every SQL statement it is asked to run and answers from canned rows."""

    def __init__(self, total: int, per_event: dict[str, int]):
        self._total = total
        self._per_event = per_event
        self.queries: list[str] = []

    def execute(self, sql: str) -> list[dict]:
        self.queries.append(sql)
        if "GROUP BY event_name" in sql:
            return [{"event_name": name, "n": n} for name, n in self._per_event.items()]
        return [{"n": self._total}]


def test_metrics_are_gathered_in_exactly_two_queries():
    backend = _FakeBackend(total=1000, per_event={"level_start": 700, "level_complete": 400, "app_remove": 90})
    metrics = query_weekly_metrics(
        backend, "p.d", ["level_start", "level_complete", "app_remove"], "20180501", "20180507"
    )
    # One query for the active-player total, one grouped query for every event —
    # not one query per event name.
    assert len(backend.queries) == 2
    assert metrics == {
        "level_start": (700, 1000),
        "level_complete": (400, 1000),
        "app_remove": (90, 1000),
    }


def test_requested_event_with_no_rows_in_the_window_counts_as_zero():
    backend = _FakeBackend(total=1000, per_event={"level_start": 700})
    metrics = query_weekly_metrics(backend, "p.d", ["level_start", "never_fired"], "20180501", "20180507")
    assert metrics["never_fired"] == (0, 1000)


def test_events_outside_the_requested_list_are_not_reported():
    backend = _FakeBackend(total=1000, per_event={"level_start": 700, "some_other_event": 5})
    metrics = query_weekly_metrics(backend, "p.d", ["level_start"], "20180501", "20180507")
    assert set(metrics) == {"level_start"}
