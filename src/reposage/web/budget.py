import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


class BudgetGuard:
    """A tiny file-backed request budget: an hourly bucket (burst
    protection) and a daily bucket (total spend protection), each
    independently disableable by setting its limit to 0 or less.

    Sized for very light traffic (a personal showcase site, not a
    production service) - a single JSON file is plenty; there's no need
    for a database or per-IP tracking here.
    """

    def __init__(
        self,
        path: Path,
        hourly_limit: int,
        daily_limit: int,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._path = path
        self._hourly_limit = hourly_limit
        self._daily_limit = daily_limit
        self._now = now

    def _buckets(self) -> tuple[str, str]:
        current = self._now()
        return current.strftime("%Y-%m-%dT%H"), current.strftime("%Y-%m-%d")

    def _read(self) -> dict:
        if not self._path.exists():
            return {"hour": "", "hour_count": 0, "day": "", "day_count": 0}
        return json.loads(self._path.read_text())

    def _write(self, state: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(state))

    def allow(self) -> bool:
        hour, day = self._buckets()
        state = self._read()

        hour_count = state["hour_count"] if state["hour"] == hour else 0
        day_count = state["day_count"] if state["day"] == day else 0

        if self._hourly_limit > 0 and hour_count >= self._hourly_limit:
            return False
        if self._daily_limit > 0 and day_count >= self._daily_limit:
            return False
        return True

    def record(self) -> None:
        hour, day = self._buckets()
        state = self._read()

        hour_count = state["hour_count"] if state["hour"] == hour else 0
        day_count = state["day_count"] if state["day"] == day else 0

        self._write({"hour": hour, "hour_count": hour_count + 1, "day": day, "day_count": day_count + 1})
