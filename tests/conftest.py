import os
import pytest


def skip_unless_env(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        pytest.skip(f"missing env vars for live test: {', '.join(missing)}")
