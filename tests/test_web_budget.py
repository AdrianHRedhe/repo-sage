from datetime import datetime, timedelta, timezone
from pathlib import Path

from reposage.web.budget import BudgetGuard


def _guard(tmp_path: Path, hourly: int, daily: int, at: datetime) -> tuple[BudgetGuard, list[datetime]]:
    clock = [at]
    guard = BudgetGuard(tmp_path / "usage.json", hourly, daily, now=lambda: clock[0])
    return guard, clock


def test_allows_requests_under_both_limits(tmp_path: Path) -> None:
    guard, _ = _guard(tmp_path, hourly=2, daily=10, at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    assert guard.allow()
    guard.record()
    assert guard.allow()


def test_blocks_once_hourly_limit_reached(tmp_path: Path) -> None:
    guard, _ = _guard(tmp_path, hourly=2, daily=10, at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    guard.record()
    guard.record()

    assert guard.allow() is False


def test_blocks_once_daily_limit_reached_even_if_hourly_ok(tmp_path: Path) -> None:
    guard, clock = _guard(tmp_path, hourly=100, daily=2, at=datetime(2026, 1, 1, 0, tzinfo=timezone.utc))

    guard.record()
    clock[0] += timedelta(hours=1)
    guard.record()

    assert guard.allow() is False


def test_hourly_bucket_resets_on_new_hour(tmp_path: Path) -> None:
    guard, clock = _guard(tmp_path, hourly=1, daily=10, at=datetime(2026, 1, 1, 10, tzinfo=timezone.utc))

    guard.record()
    assert guard.allow() is False

    clock[0] += timedelta(hours=1)
    assert guard.allow() is True


def test_daily_bucket_resets_on_new_day(tmp_path: Path) -> None:
    guard, clock = _guard(tmp_path, hourly=100, daily=1, at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    guard.record()
    assert guard.allow() is False

    clock[0] += timedelta(days=1)
    assert guard.allow() is True


def test_limit_of_zero_disables_that_tier(tmp_path: Path) -> None:
    guard, _ = _guard(tmp_path, hourly=0, daily=0, at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    for _ in range(50):
        guard.record()

    assert guard.allow() is True
