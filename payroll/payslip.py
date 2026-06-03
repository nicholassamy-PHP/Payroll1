"""Render HTML payslips, payroll run sheets, and YTD summaries from
calculated PayResult objects."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Company
from .models import Employee, PayResult, Period


TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def _format_money(v):
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _format_pct(v):
    try:
        return f"{float(v) * 100:.2f}%"
    except (TypeError, ValueError):
        return "—"


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True, lstrip_blocks=True,
    )
    env.filters["f2"] = _format_money
    env.filters["pct"] = _format_pct
    return env


# --------- public rendering API ------------------------------------------ #

def render_payslip(
    employee: Employee, result: PayResult, period: Period, company: Company
) -> str:
    env = _env()
    tmpl = env.get_template("payslip.html")
    return tmpl.render(
        employee=employee, r=result, period=period, company=company,
        rate=_format_money(employee.rate_per_hour),
    )


def _sum(rows: list[tuple[Employee, PayResult]], attr: str) -> float:
    return sum(getattr(r, attr) for _, r in rows)


def render_run(
    period: Period, rows: list[tuple[Employee, PayResult]], company: Company
) -> str:
    env = _env()
    tmpl = env.get_template("run.html")
    totals = {a: _sum(rows, a) for a in [
        "gross", "federal_tax", "quebec_tax", "ei_ee", "ei_er", "qpip_ee", "qpip_er",
        "qpp_ee", "qpp_er", "fss", "csst", "total_deductions", "net_pay",
        "vacation_accrual",
    ]}
    return tmpl.render(rows=rows, totals=totals, period=period, company=company)


def render_summary(
    period: Period, rows: list[tuple[Employee, PayResult]], company: Company
) -> str:
    env = _env()
    tmpl = env.get_template("summary.html")
    by_employee = []
    for emp, r in rows:
        d = asdict(r)
        d["code"] = emp.code
        d["name"] = emp.full_name
        by_employee.append(d)
    totals_fields = [
        "ytd_gross", "ytd_regular_hours", "ytd_holiday_hours", "ytd_vacation_hours",
        "ytd_maternity_hours", "ytd_federal_tax", "ytd_quebec_tax", "ytd_ei_ee",
        "ytd_qpip_ee", "ytd_qpp_ee", "ytd_net_pay", "ytd_vacation_accrual",
        "ytd_vacation_amount", "vacation_balance",
    ]
    totals = {f: sum(r[f] for r in by_employee) for f in totals_fields}
    return tmpl.render(by_employee=by_employee, totals=totals,
                       period=period, company=company)


def write_outputs(
    period: Period, rows: list[tuple[Employee, PayResult]],
    company: Company, output_dir: Path | None = None
) -> Path:
    out = output_dir or (Path(__file__).resolve().parent.parent
                         / "output" / period.pay_end_date)
    out.mkdir(parents=True, exist_ok=True)

    (out / "run.html").write_text(render_run(period, rows, company))
    (out / "summary.html").write_text(render_summary(period, rows, company))
    for emp, r in rows:
        if r.gross <= 0:
            continue   # don't create a payslip for an employee with no pay
        (out / f"payslip-{emp.first_name}.html").write_text(
            render_payslip(emp, r, period, company)
        )
    return out
