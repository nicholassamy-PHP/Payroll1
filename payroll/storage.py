"""Persistence for employees and per-year pay history."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .config import DATA_DIR
from .models import Employee, dict_to_employee, to_jsonable


HISTORY_DIR = DATA_DIR / "history"


def load_employees(path: Path | None = None) -> list[Employee]:
    p = path or DATA_DIR / "employees.json"
    return [dict_to_employee(rec) for rec in json.loads(p.read_text())]


def find_employee(code: str, employees: Iterable[Employee]) -> Employee | None:
    for e in employees:
        if e.code == code or e.first_name.strip().lower() == code.strip().lower():
            return e
    return None


def history_file(year: int) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR / f"{year}.json"


def load_year_history(year: int) -> list[dict]:
    """Return the list of persisted periods for the given year (oldest first)."""
    f = history_file(year)
    if not f.exists():
        return []
    return json.loads(f.read_text())


def save_year_history(year: int, periods: list[dict]) -> None:
    history_file(year).write_text(json.dumps(periods, indent=2, default=str))


def append_period_to_history(year: int, period_record: dict) -> None:
    """Append a period to year history, replacing any existing entry with the
    same pay_end_date (so re-running a period is idempotent)."""
    periods = load_year_history(year)
    key = period_record["period"]["pay_end_date"]
    periods = [p for p in periods if p["period"]["pay_end_date"] != key]
    periods.append(period_record)
    periods.sort(key=lambda r: r["period"]["pay_end_date"])
    save_year_history(year, periods)


def serialize(obj) -> dict:
    return to_jsonable(obj)
