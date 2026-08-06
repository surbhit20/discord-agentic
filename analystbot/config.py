from dataclasses import dataclass


class ConfigError(Exception):
    pass


@dataclass
class Config:
    discord_token: str
    anthropic_api_key: str
    bq_billing_project: str
    bq_dataset_path: str
    google_application_credentials: str
    cost_threshold_bytes: int
    db_path: str


_REQUIRED = [
    "DISCORD_TOKEN",
    "ANTHROPIC_API_KEY",
    "BQ_BILLING_PROJECT",
    "BQ_DATASET_PATH",
    "GOOGLE_APPLICATION_CREDENTIALS",
]


def load_config(env: dict[str, str]) -> Config:
    missing = [name for name in _REQUIRED if not env.get(name)]
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")
    return Config(
        discord_token=env["DISCORD_TOKEN"],
        anthropic_api_key=env["ANTHROPIC_API_KEY"],
        bq_billing_project=env["BQ_BILLING_PROJECT"],
        bq_dataset_path=env["BQ_DATASET_PATH"],
        google_application_credentials=env["GOOGLE_APPLICATION_CREDENTIALS"],
        cost_threshold_bytes=int(env.get("COST_THRESHOLD_BYTES", str(1024 ** 3))),
        db_path=env.get("DB_PATH", "analystbot.db"),
    )
