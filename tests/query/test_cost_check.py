from analystbot.query.cost_check import check_cost


class _FakeBackend:
    def __init__(self, bytes_estimate: int):
        self._bytes = bytes_estimate

    def dry_run(self, sql: str) -> int:
        return self._bytes


def test_under_threshold_does_not_need_confirmation():
    needs_confirm, estimate = check_cost(_FakeBackend(500), "SELECT 1", threshold_bytes=1000)
    assert needs_confirm is False
    assert estimate == 500


def test_over_threshold_needs_confirmation():
    needs_confirm, estimate = check_cost(_FakeBackend(5000), "SELECT 1", threshold_bytes=1000)
    assert needs_confirm is True
    assert estimate == 5000


def test_exactly_at_threshold_does_not_need_confirmation():
    needs_confirm, estimate = check_cost(_FakeBackend(1000), "SELECT 1", threshold_bytes=1000)
    assert needs_confirm is False
