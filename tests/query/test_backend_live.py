import os
import pytest
from tests.conftest import skip_unless_env
from analystbot.query.backend import BigQueryBackend

pytestmark = pytest.mark.live

_SQL = (
    "SELECT COUNT(*) AS n FROM `firebase-public-project.analytics_153293282.events_*` "
    "WHERE _TABLE_SUFFIX BETWEEN '20180701' AND '20180702'"
)

# COUNT(*) alone can be resolved from table metadata with 0 bytes scanned;
# dry_run needs a query that actually reads column data to report > 0 bytes.
_SQL_WITH_COLUMN_SCAN = (
    "SELECT COUNT(DISTINCT user_pseudo_id) AS n "
    "FROM `firebase-public-project.analytics_153293282.events_*` "
    "WHERE _TABLE_SUFFIX BETWEEN '20180701' AND '20180702'"
)


def _backend():
    skip_unless_env("GOOGLE_APPLICATION_CREDENTIALS", "BQ_BILLING_PROJECT")
    return BigQueryBackend(
        project=os.environ["BQ_BILLING_PROJECT"],
        credentials_path=os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
    )


def test_dry_run_estimates_bytes_without_charge():
    backend = _backend()
    assert backend.dry_run(_SQL_WITH_COLUMN_SCAN) > 0


def test_execute_returns_rows():
    backend = _backend()
    rows = backend.execute(_SQL)
    assert len(rows) == 1
    assert rows[0]["n"] > 0
