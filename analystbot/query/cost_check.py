def check_cost(backend, sql: str, threshold_bytes: int) -> tuple[bool, int]:
    estimate = backend.dry_run(sql)
    return estimate > threshold_bytes, estimate
