"""Data models for the payroll system.

All money values are stored as plain floats; rounding is applied only at the
edges (payslip rendering, persistence summing).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


@dataclass
class Employee:
    code: str
    first_name: str
    last_name: str
    rate_per_hour: float
    hire_date: str
    address_line_1: str = ""
    address_line_2: str = ""
    city: str = ""
    province: str = "QC"
    postal_code: str = ""
    date_of_birth: Optional[str] = None
    sin: str = ""
    employee_id: str = ""
    department: str = ""
    occupation: str = ""
    vacation_rate: float = 0.04
    federal_td1_claim: float = 16452
    provincial_td1_claim: float = 18952
    additional_federal_tax: float = 0.0
    additional_quebec_tax: float = 0.0
    tax_exempt_federal: bool = False
    tax_exempt_quebec: bool = False
    tax_exempt_ei: bool = False
    tax_exempt_qpip: bool = False
    tax_exempt_qpp: bool = False
    active: bool = True

    @property
    def full_name(self) -> str:
        return f"{self.first_name.strip()} {self.last_name.strip()}".strip()


@dataclass
class HoursInput:
    """Client-supplied hours for one employee in one pay period."""
    regular: float = 0.0
    holiday_paid: float = 0.0      # holiday hours paid out (T col on summary)
    vacation_paid: float = 0.0     # vacation hours paid out (S col)
    special: float = 0.0           # special pay (sick day etc.)
    maternity: float = 0.0         # MAL PAY
    ssl_hours: float = 0.0         # statutory sick leave hours
    other_amount: float = 0.0      # non-hourly addition (bonus etc.)
    override_rate: Optional[float] = None  # rare override per period


@dataclass
class YtdOpening:
    """YTD balances brought forward when starting a new fiscal year."""
    gross: float = 0.0
    regular_hours: float = 0.0
    regular_amount: float = 0.0
    holiday_hours: float = 0.0
    holiday_amount: float = 0.0
    vacation_hours: float = 0.0
    vacation_amount: float = 0.0
    special_amount: float = 0.0
    maternity_hours: float = 0.0
    maternity_amount: float = 0.0
    federal_tax: float = 0.0
    quebec_tax: float = 0.0
    ei_ee: float = 0.0
    qpip_ee: float = 0.0
    qpp_ee: float = 0.0
    insurable_ei: float = 0.0
    insurable_qpip: float = 0.0
    pensionable_qpp: float = 0.0
    csst_insurable: float = 0.0
    vacation_accrual: float = 0.0
    vacation_paid_amount: float = 0.0
    holiday_balance: float = 0.0


@dataclass
class PayResult:
    """One employee's calculated pay for one period (current + YTD snapshot)."""
    employee_code: str

    # Current pay
    regular_hours: float = 0.0
    regular_amount: float = 0.0
    holiday_hours: float = 0.0
    holiday_amount: float = 0.0
    vacation_hours: float = 0.0
    vacation_amount: float = 0.0
    special_amount: float = 0.0
    maternity_hours: float = 0.0
    maternity_amount: float = 0.0
    other_amount: float = 0.0
    gross: float = 0.0

    federal_tax: float = 0.0
    quebec_tax: float = 0.0
    ei_ee: float = 0.0
    ei_er: float = 0.0
    qpip_ee: float = 0.0
    qpip_er: float = 0.0
    qpp_ee: float = 0.0
    qpp_er: float = 0.0
    fss: float = 0.0
    csst: float = 0.0
    total_deductions: float = 0.0
    employer_burden: float = 0.0
    net_pay: float = 0.0

    vacation_accrual: float = 0.0

    # YTD snapshot AFTER this pay
    ytd_gross: float = 0.0
    ytd_regular_hours: float = 0.0
    ytd_regular_amount: float = 0.0
    ytd_holiday_hours: float = 0.0
    ytd_holiday_amount: float = 0.0
    ytd_vacation_hours: float = 0.0
    ytd_vacation_amount: float = 0.0
    ytd_special_amount: float = 0.0
    ytd_maternity_hours: float = 0.0
    ytd_maternity_amount: float = 0.0
    ytd_federal_tax: float = 0.0
    ytd_quebec_tax: float = 0.0
    ytd_ei_ee: float = 0.0
    ytd_qpip_ee: float = 0.0
    ytd_qpp_ee: float = 0.0
    ytd_vacation_accrual: float = 0.0
    ytd_net_pay: float = 0.0

    vacation_balance: float = 0.0


@dataclass
class Period:
    """A single pay period."""
    pay_end_date: str        # YYYY-MM-DD — end of work period
    payment_date: str        # YYYY-MM-DD — date wages are paid
    pay_number: int          # nth pay of the year (1..pay_periods_per_year)
    year: int

    @property
    def label(self) -> str:
        return self.pay_end_date


def dict_to_employee(d: dict) -> Employee:
    """Build an Employee from a dict, ignoring unknown keys (forward compat)."""
    fields_set = {f for f in Employee.__dataclass_fields__}
    clean = {k: v for k, v in d.items() if k in fields_set}
    return Employee(**clean)


def to_jsonable(obj) -> dict:
    """Convert a dataclass to a JSON-safe dict (datetime -> ISO string)."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    return obj
