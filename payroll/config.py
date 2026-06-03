"""Load and expose company + tax configuration."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


@dataclass
class Company:
    name: str
    address_line_1: str
    address_line_2: str
    city: str
    province: str
    postal_code: str
    payroll_year: int
    pay_periods_per_year: int
    pay_frequency: str
    payroll_fees_per_run: float
    bank_fees_per_run: float

    @property
    def address(self) -> str:
        parts = [self.address_line_1, self.address_line_2,
                 f"{self.city}, {self.province} {self.postal_code}".strip()]
        return ", ".join(p for p in parts if p and p.strip())


def load_company(path: Path | None = None) -> Company:
    p = path or DATA_DIR / "company.json"
    raw = json.loads(p.read_text())
    return Company(**raw)


def load_tax_config(path: Path | None = None) -> dict[str, Any]:
    p = path or DATA_DIR / "tax_config.json"
    return json.loads(p.read_text())
