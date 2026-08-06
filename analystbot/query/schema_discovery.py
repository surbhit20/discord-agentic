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
