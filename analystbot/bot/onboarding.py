from analystbot.query.schema_discovery import discover_schema
from analystbot.storage import schema_cache


def build_onboarding_report(schema: dict) -> str:
    events = schema["events"]
    tracked = ", ".join(sorted(events.keys()))
    min_date, max_date = schema["date_range"]
    return "\n".join(
        [
            f"Tracking {len(events)} event types: {tracked}.",
            f"Data covers {min_date} to {max_date}, {schema['player_count']} players.",
            "Reply `confirm` in this channel to start using this data, or correct me if something looks wrong.",
        ]
    )


async def run_onboarding(message, backend, dataset_path: str, conn) -> str:
    schema = discover_schema(backend, dataset_path)
    schema_cache.save_schema(conn, schema)
    report = build_onboarding_report(schema)
    await message.channel.send(report)
    return report
