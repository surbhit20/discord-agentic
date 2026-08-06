import os
import pytest
from tests.conftest import skip_unless_env
from analystbot.query.backend import BigQueryBackend
from analystbot.query.schema_discovery import discover_schema

pytestmark = pytest.mark.live

_DATASET = "firebase-public-project.analytics_153293282"


def test_discover_schema_finds_known_flood_it_events():
    skip_unless_env("GOOGLE_APPLICATION_CREDENTIALS", "BQ_BILLING_PROJECT")
    backend = BigQueryBackend(
        project=os.environ["BQ_BILLING_PROJECT"],
        credentials_path=os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
    )
    schema = discover_schema(backend, _DATASET)
    assert "level_complete" in schema["events"] or "level_start" in schema["events"]
    assert schema["player_count"] > 0
    min_date, max_date = schema["date_range"]
    assert min_date < max_date
