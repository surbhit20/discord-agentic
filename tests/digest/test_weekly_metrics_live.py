import os
import pytest
from tests.conftest import skip_unless_env
from analystbot.query.backend import BigQueryBackend
from analystbot.digest.compute import query_weekly_metrics

pytestmark = pytest.mark.live

_DATASET = "firebase-public-project.analytics_153293282"


def test_query_weekly_metrics_returns_count_and_total_per_event():
    skip_unless_env("GOOGLE_APPLICATION_CREDENTIALS", "BQ_BILLING_PROJECT")
    backend = BigQueryBackend(
        project=os.environ["BQ_BILLING_PROJECT"],
        credentials_path=os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
    )
    metrics = query_weekly_metrics(backend, _DATASET, ["level_start"], "20180701", "20180707")
    count, total = metrics["level_start"]
    assert 0 <= count <= total
    assert total > 0
