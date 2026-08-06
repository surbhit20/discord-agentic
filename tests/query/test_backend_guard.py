import pytest

from analystbot.query.backend import BigQueryBackend, ensure_read_only


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "  select count(*) from t",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "-- a leading comment\nSELECT 1",
        "/* block comment */ SELECT 1",
    ],
)
def test_select_and_with_queries_are_allowed(sql):
    ensure_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE events",
        "delete from events where 1=1",
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET x = 1",
        "CREATE TABLE t (x INT64)",
        "MERGE INTO t USING s ON t.id = s.id",
        "",
        "-- only a comment",
    ],
)
def test_non_select_statements_are_rejected(sql):
    with pytest.raises(ValueError, match="Only SELECT/WITH queries are allowed"):
        ensure_read_only(sql)


class _FakeClient:
    def __init__(self):
        self.queries = []

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        raise AssertionError("query should never be reached for a rejected statement")


def _backend_without_credentials() -> BigQueryBackend:
    backend = BigQueryBackend.__new__(BigQueryBackend)
    backend.client = _FakeClient()
    return backend


def test_execute_rejects_ddl_before_touching_the_client():
    backend = _backend_without_credentials()
    with pytest.raises(ValueError, match="Only SELECT/WITH queries are allowed"):
        backend.execute("DROP TABLE events")
    assert backend.client.queries == []


def test_dry_run_rejects_dml_before_touching_the_client():
    backend = _backend_without_credentials()
    with pytest.raises(ValueError, match="Only SELECT/WITH queries are allowed"):
        backend.dry_run("DELETE FROM events")
    assert backend.client.queries == []
