import pytest
from analystbot.config import load_config, ConfigError

_FULL_ENV = {
    "DISCORD_TOKEN": "d-token",
    "ANTHROPIC_API_KEY": "a-key",
    "BQ_BILLING_PROJECT": "my-project",
    "BQ_DATASET_PATH": "firebase-public-project.analytics_153293282",
    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/creds.json",
}

def test_loads_config_from_full_env():
    config = load_config(_FULL_ENV)
    assert config.discord_token == "d-token"
    assert config.bq_dataset_path == "firebase-public-project.analytics_153293282"
    assert config.cost_threshold_bytes == 1024 ** 3
    assert config.bq_price_per_tib_usd == 6.25
    assert config.db_path == "analystbot.db"

def test_missing_required_var_raises_with_name():
    partial = dict(_FULL_ENV)
    del partial["DISCORD_TOKEN"]
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        load_config(partial)

def test_cost_threshold_overridable():
    env = dict(_FULL_ENV, COST_THRESHOLD_BYTES="500")
    assert load_config(env).cost_threshold_bytes == 500

def test_price_per_tib_overridable():
    env = dict(_FULL_ENV, BQ_PRICE_PER_TIB_USD="5.00")
    assert load_config(env).bq_price_per_tib_usd == 5.00
