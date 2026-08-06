from google.cloud import bigquery
from google.oauth2 import service_account


class BigQueryBackend:
    def __init__(self, project: str, credentials_path: str):
        credentials = service_account.Credentials.from_service_account_file(credentials_path)
        self.client = bigquery.Client(project=project, credentials=credentials)

    def dry_run(self, sql: str) -> int:
        job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        job = self.client.query(sql, job_config=job_config)
        return job.total_bytes_processed

    def execute(self, sql: str) -> list[dict]:
        job = self.client.query(sql)
        return [dict(row.items()) for row in job.result()]
