import re

from google.cloud import bigquery
from google.oauth2 import service_account

_LEADING_COMMENTS = re.compile(r"^(?:\s*(?:--[^\n]*\n|/\*.*?\*/))*\s*", re.DOTALL)
_FIRST_WORD = re.compile(r"[A-Za-z_]+")
_ALLOWED_STATEMENTS = ("SELECT", "WITH")


def ensure_read_only(sql: str) -> None:
    """Raise unless `sql` starts with SELECT or WITH.

    The bot's only user-reachable path to BigQuery is Claude-generated SQL, so the
    "read-only throughout" guarantee needs a code-level check and not just IAM.
    Leading comments are skipped; anything that doesn't then begin with a plain
    SELECT/WITH keyword (including an empty or comment-only string) is rejected.
    """
    body = _LEADING_COMMENTS.sub("", sql or "", count=1)
    first = _FIRST_WORD.match(body)
    if first is None or first.group(0).upper() not in _ALLOWED_STATEMENTS:
        raise ValueError("Only SELECT/WITH queries are allowed")


class BigQueryBackend:
    def __init__(self, project: str, credentials_path: str):
        credentials = service_account.Credentials.from_service_account_file(credentials_path)
        self.client = bigquery.Client(project=project, credentials=credentials)

    def dry_run(self, sql: str) -> int:
        ensure_read_only(sql)
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        job = self.client.query(sql, job_config=job_config)
        return job.total_bytes_processed

    def execute(self, sql: str) -> list[dict]:
        ensure_read_only(sql)
        job = self.client.query(sql)
        return [dict(row.items()) for row in job.result()]
