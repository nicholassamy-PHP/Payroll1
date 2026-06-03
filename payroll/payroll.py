"""Top-level orchestration: build a PayResult for one employee + one period,
and aggregate across an entire pay run."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from . import tax
from .config import Company, load_company, load_tax_config
from .models import (Employee, HoursInput, PayResult, Period, dict_to_employee,
                     to_jsonable)
from .storage import (DATA_DIR, append_period_to_history, load_employees,
                      load_year_history)


# ---------- YTD aggregation ----------------------------------------------- #

def ytd_before(year: int, pay_end_date: str, employee_code: str) -> dict:
    """Sum prior-period values from history for one employee, up to (but not
    including) `pay_end_date`."""
    totals = {
        "gross": 0.0,
        "regular_hours": 0.0, "regular_amount": 0.0,
        "holiday_hours": 0.0, "holiday_amount": 0.0,
        "vacation_hours": 0.0, "vacation_amount": 0.0,
        "special_amount": 0.0,
        "maternity_hours": 0.0, "maternity_amount": 0.0,
        "federal_tax": 0.0, "quebec_tax": 0.0,
        "ei_ee": 0.0, "qpip_ee": 0.0, "qpp_ee": 0.0,
        "insurable_ei": 0.0, "insurable_qpip": 0.0,
        "pensionable_qpp": 0.0, "csst_insurable": 0.0,
        "vacation_accrual": 0.0,
        "net_pay": 0.0,
    }
    for record in load_year_history(year):
        if record["period"]["pay_end_date"] >= pay_end_date:
            continue
        for r in record["results"]:
            if r["employee_code"] != employee_code:
                continue
            totals["gross"]            += r.get("gross", 0)
            totals["regular_hours"]    += r.get("regular_hours", 0)
            totals["regular_amount"]   += r.get("regular_amount", 0)
            totals["holiday_hours"]    += r.get("holiday_hours", 0)
            totals["holiday_amount"]   += r.get("holiday_amount", 0)
            totals["vacation_hours"]   += r.get("vacation_hours", 0)
            totals["vacation_amount"]  += r.get("vacation_amount", 0)
            totals["special_amount"]   += r.get("special_amount", 0)
            totals["maternity_hours"]  += r.get("maternity_hours", 0)
            totals["maternity_amount"] += r.get("maternity_amount", 0)
            totals["federal_tax"]      += r.get("federal_tax", 0)
            totals["quebec_tax"]       += r.get("quebec_tax", 0)
            totals["ei_ee"]            += r.get("ei_ee", 0)
            totals["qpip_ee"]          += r.get("qpip_ee", 0)
            totals["qpp_ee"]           += r.get("qpp_ee", 0)
            totals["vacation_accrual"] += r.get("vacation_accrual", 0)
            totals["net_pay"]          += r.get("net_pay", 0)
            # Insurable ytd = gross up to ceiling — track as raw cumulative gross
            totals["insurable_ei"]     += r.get("gross", 0)
            totals["insurable_qpip"]   += r.get("gross", 0)
            totals["pensionable_qpp"]  += r.get("gross", 0)
            totals["csst_insurable"]   += r.get("gross", 0)
    return totals


# ---------- single-employee calculation ----------------------------------- #

def calculate_pay(
    employee: Employee, hours: HoursInput, period: Period,
    company: Company, tax_cfg: dict, ytd: dict,
) -> PayResult:
    """Build a PayResult for one employee for one period."""
    rate = hours.override_rate if hours.override_rate is not None else employee.rate_per_hour

    regular_amt   = hours.regular        * rate
    holiday_amt   = hours.holiday_paid   * rate
    vacation_amt  = hours.vacation_paid  * rate
    special_amt   = hours.special        * rate
    maternity_amt = hours.maternity      * rate

    gross = (regular_amt + holiday_amt + vacation_amt + special_amt
             + maternity_amt + hours.other_amount)

    pp = company.pay_periods_per_year

    # Statutory deductions
    qpp_ee, _ = tax.calc_qpp_ee(gross, tax_cfg, ytd["pensionable_qpp"], pp, employee)
    qpp_er = tax.calc_qpp_er(qpp_ee, tax_cfg)
    ei_ee, ei_er, _ = tax.calc_ei(gross, tax_cfg, ytd["insurable_ei"], employee)
    qpip_ee, qpip_er, _ = tax.calc_qpip(gross, tax_cfg, ytd["insurable_qpip"], employee)
    fss = tax.calc_fss(gross, tax_cfg)
    csst = tax.calc_csst(gross, tax_cfg, ytd["csst_insurable"])

    fed_tax = tax.calc_federal_tax(gross, tax_cfg, employee, pp, ei_ee, qpp_ee, qpip_ee)
    qc_tax  = tax.calc_quebec_tax(gross, tax_cfg, employee, pp, ei_ee, qpp_ee, qpip_ee)

    total_ded = fed_tax + qc_tax + ei_ee + qpip_ee + qpp_ee
    employer = ei_er + qpip_er + qpp_er + fss + csst
    net = gross - total_ded

    vac_accrual = gross * employee.vacation_rate

    result = PayResult(
        employee_code=employee.code,
        regular_hours=hours.regular, regular_amount=regular_amt,
        holiday_hours=hours.holiday_paid, holiday_amount=holiday_amt,
        vacation_hours=hours.vacation_paid, vacation_amount=vacation_amt,
        special_amount=special_amt,
        maternity_hours=hours.maternity, maternity_amount=maternity_amt,
        other_amount=hours.other_amount, gross=gross,
        federal_tax=fed_tax, quebec_tax=qc_tax,
        ei_ee=ei_ee, ei_er=ei_er, qpip_ee=qpip_ee, qpip_er=qpip_er,
        qpp_ee=qpp_ee, qpp_er=qpp_er, fss=fss, csst=csst,
        total_deductions=total_ded, employer_burden=employer, net_pay=net,
        vacation_accrual=vac_accrual,
        ytd_gross            = ytd["gross"] + gross,
        ytd_regular_hours    = ytd["regular_hours"] + hours.regular,
        ytd_regular_amount   = ytd["regular_amount"] + regular_amt,
        ytd_holiday_hours    = ytd["holiday_hours"] + hours.holiday_paid,
        ytd_holiday_amount   = ytd["holiday_amount"] + holiday_amt,
        ytd_vacation_hours   = ytd["vacation_hours"] + hours.vacation_paid,
        ytd_vacation_amount  = ytd["vacation_amount"] + vacation_amt,
        ytd_special_amount   = ytd["special_amount"] + special_amt,
        ytd_maternity_hours  = ytd["maternity_hours"] + hours.maternity,
        ytd_maternity_amount = ytd["maternity_amount"] + maternity_amt,
        ytd_federal_tax      = ytd["federal_tax"] + fed_tax,
        ytd_quebec_tax       = ytd["quebec_tax"] + qc_tax,
        ytd_ei_ee            = ytd["ei_ee"] + ei_ee,
        ytd_qpip_ee          = ytd["qpip_ee"] + qpip_ee,
        ytd_qpp_ee           = ytd["qpp_ee"] + qpp_ee,
        ytd_vacation_accrual = ytd["vacation_accrual"] + vac_accrual,
        ytd_net_pay          = ytd["net_pay"] + net,
    )
    result.vacation_balance = result.ytd_vacation_accrual - result.ytd_vacation_amount
    return result


# ---------- pay-run orchestration ----------------------------------------- #

def derive_pay_number(period_end: str, year: int) -> int:
    """How many periods have already been persisted for this year, plus one."""
    return len([p for p in load_year_history(year)
                if p["period"]["pay_end_date"] < period_end]) + 1


def load_hours_file(path: Path) -> dict[str, HoursInput]:
    raw = json.loads(path.read_text())
    out: dict[str, HoursInput] = {}
    for emp_key, row in raw.items():
        if not isinstance(row, dict):
            continue
        fields = HoursInput.__dataclass_fields__
        clean = {k: v for k, v in row.items() if k in fields}
        out[emp_key] = HoursInput(**clean)
    return out


def lookup_employee(key: str, employees: list[Employee]) -> Employee | None:
    """Resolve an employee key (code, first name, or full name)."""
    k = key.strip().lower()
    for e in employees:
        if e.code.lower() == k: return e
        if e.first_name.strip().lower() == k: return e
        if e.full_name.lower() == k: return e
    return None


def run_period(
    period: Period, hours_by_employee: dict[str, HoursInput],
    company: Company | None = None,
    tax_cfg: dict | None = None,
    employees: list[Employee] | None = None,
) -> tuple[Period, list[tuple[Employee, PayResult]]]:
    company = company or load_company()
    tax_cfg = tax_cfg or load_tax_config()
    employees = employees or load_employees()

    rows: list[tuple[Employee, PayResult]] = []
    for emp in employees:
        if not emp.active:
            continue
        h_key = next((k for k in (emp.code, emp.first_name, emp.full_name)
                      if k in hours_by_employee), None)
        if h_key is None:
            # No hours submitted for this employee — record a zero row.
            hours = HoursInput()
        else:
            hours = hours_by_employee[h_key]
        ytd = ytd_before(period.year, period.pay_end_date, emp.code)
        result = calculate_pay(emp, hours, period, company, tax_cfg, ytd)
        rows.append((emp, result))
    return period, rows


def persist_run(period: Period, rows: list[tuple[Employee, PayResult]]) -> None:
    record = {
        "period": {
            "pay_end_date": period.pay_end_date,
            "payment_date": period.payment_date,
            "pay_number": period.pay_number,
            "year": period.year,
        },
        "results": [to_jsonable(r) for _, r in rows],
    }
    append_period_to_history(period.year, record)
