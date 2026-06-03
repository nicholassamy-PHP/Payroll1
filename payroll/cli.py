"""Command-line entry point for the payroll system.

    python -m payroll status
    python -m payroll new-period --end YYYY-MM-DD --pay-date YYYY-MM-DD
    python -m payroll run --hours examples/<period>.hours.json
    python -m payroll show --period YYYY-MM-DD
    python -m payroll add-employee
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR, load_company, load_tax_config
from .models import Employee, HoursInput, Period
from .payroll import (derive_pay_number, load_hours_file, persist_run,
                      run_period, ytd_before)
from .payslip import write_outputs
from .storage import load_employees, load_year_history


def _examples_dir() -> Path:
    p = Path(__file__).resolve().parent.parent / "examples"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ----- commands ----------------------------------------------------------- #

def cmd_status(_args: argparse.Namespace) -> int:
    company = load_company()
    employees = load_employees()
    active = [e for e in employees if e.active]
    history = load_year_history(company.payroll_year)
    print(f"Company:    {company.name}")
    print(f"Year:       {company.payroll_year} ({company.pay_frequency}, "
          f"{company.pay_periods_per_year} pays)")
    print(f"Employees:  {len(active)} active / {len(employees)} total")
    print(f"Periods on file ({company.payroll_year}): {len(history)}")
    if history:
        last = history[-1]["period"]
        print(f"  last:      {last['pay_end_date']}  (pay #{last['pay_number']})")
    print()
    print(f"{'CODE':<6}{'NAME':<30}{'RATE':>8}{'HIRE DATE':>14}")
    for e in active:
        print(f"{e.code:<6}{e.full_name:<30}{e.rate_per_hour:>8.2f}{e.hire_date:>14}")
    return 0


def cmd_new_period(args: argparse.Namespace) -> int:
    employees = load_employees()
    template = {}
    for e in employees:
        if not e.active:
            continue
        template[e.first_name] = {
            "regular": 0,
            "holiday_paid": 0,
            "vacation_paid": 0,
            "special": 0,
            "maternity": 0,
            "ssl_hours": 0,
            "other_amount": 0,
        }
    payload = {
        "_period": {
            "pay_end_date": args.end,
            "payment_date": args.pay_date,
            "notes": "Fill in hours per employee. Keys may be first name or code.",
        },
        **template,
    }
    out = _examples_dir() / f"{args.end}.hours.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"Hours-input template written: {out}")
    print("Edit it, then run:")
    print(f"  python -m payroll run --hours {out}")
    return 0


def _parse_period_from_hours_file(path: Path, override_end: str | None,
                                  override_pay: str | None,
                                  company_year: int) -> Period:
    raw = json.loads(path.read_text())
    meta = raw.get("_period", {}) if isinstance(raw, dict) else {}
    end = override_end or meta.get("pay_end_date")
    pay = override_pay or meta.get("payment_date")
    if not end:
        raise SystemExit("Hours file is missing _period.pay_end_date and "
                         "no --end was provided")
    if not pay:
        # default payment date = end date + 6 days (Garderie's pattern)
        pay = (datetime.fromisoformat(end)).strftime("%Y-%m-%d")
    year = int(end[:4])
    pn = derive_pay_number(end, year)
    return Period(pay_end_date=end, payment_date=pay, pay_number=pn, year=year)


def cmd_run(args: argparse.Namespace) -> int:
    company = load_company()
    tax_cfg = load_tax_config()
    employees = load_employees()
    hours_path = Path(args.hours)
    hours = load_hours_file(hours_path)
    period = _parse_period_from_hours_file(hours_path, args.end, args.pay_date,
                                           company.payroll_year)

    period, rows = run_period(period, hours, company, tax_cfg, employees)

    if not args.dry_run:
        persist_run(period, rows)
    out = write_outputs(period, rows, company,
                        output_dir=Path(args.output) if args.output else None)
    print(f"Period:    {period.pay_end_date}  pay #{period.pay_number}")
    print(f"Employees: {sum(1 for _, r in rows if r.gross > 0)} paid, "
          f"{sum(1 for _, r in rows if r.gross == 0)} zero")
    print(f"Run total: gross={sum(r.gross for _, r in rows):>12,.2f}  "
          f"net={sum(r.net_pay for _, r in rows):>12,.2f}  "
          f"deductions={sum(r.total_deductions for _, r in rows):>12,.2f}")
    print(f"Output:    {out}")
    if args.dry_run:
        print("(dry run — history not updated)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    company = load_company()
    history = load_year_history(company.payroll_year)
    if args.period:
        rec = next((r for r in history
                    if r["period"]["pay_end_date"] == args.period), None)
        if not rec:
            print(f"No period {args.period} on file.")
            return 1
        print(json.dumps(rec, indent=2))
        return 0
    print(json.dumps(history, indent=2))
    return 0


def cmd_add_employee(_args: argparse.Namespace) -> int:
    """Interactively append an employee to data/employees.json."""
    def ask(label, default=""):
        d = f" [{default}]" if default else ""
        ans = input(f"{label}{d}: ").strip()
        return ans or default

    code     = ask("Department / payroll code (e.g. A24)")
    fn       = ask("First name")
    ln       = ask("Last name")
    addr     = ask("Address line 1")
    city     = ask("City")
    prov     = ask("Province", "QC")
    pc       = ask("Postal code")
    dob      = ask("Date of birth (YYYY-MM-DD)") or None
    hire     = ask("Hire date (YYYY-MM-DD)")
    sin      = ask("SIN")
    emp_id   = ask("Employee/payee ID")
    occup    = ask("Occupation")
    rate     = float(ask("Rate per hour"))
    vac      = float(ask("Vacation rate (e.g. 0.04 or 0.06)", "0.04"))
    fed_td1  = float(ask("Federal TD1 claim amount", "16452"))
    qc_td1   = float(ask("Provincial TD1 claim amount", "18952"))
    add_fed  = float(ask("Additional federal tax per pay", "0"))
    add_qc   = float(ask("Additional Quebec tax per pay", "0"))

    new = {
        "code": code, "first_name": fn, "last_name": ln,
        "address_line_1": addr, "city": city, "province": prov,
        "postal_code": pc, "date_of_birth": dob, "hire_date": hire,
        "sin": sin, "employee_id": emp_id, "occupation": occup,
        "rate_per_hour": rate, "vacation_rate": vac,
        "federal_td1_claim": fed_td1, "provincial_td1_claim": qc_td1,
        "additional_federal_tax": add_fed, "additional_quebec_tax": add_qc,
        "active": True,
    }
    f = DATA_DIR / "employees.json"
    employees = json.loads(f.read_text())
    if any(e["code"] == code for e in employees):
        print(f"Code {code} already exists. Aborting.")
        return 1
    employees.append(new)
    f.write_text(json.dumps(employees, indent=2))
    print(f"Added {fn} {ln} ({code}). employees.json now has {len(employees)} records.")
    return 0


# ----- argparse wiring --------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="payroll", description="Quebec biweekly payroll")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show company, employees, and pay history").set_defaults(func=cmd_status)

    np_p = sub.add_parser("new-period", help="Write a blank hours-input template")
    np_p.add_argument("--end", required=True, help="Pay-period end date YYYY-MM-DD")
    np_p.add_argument("--pay-date", required=True, help="Payment date YYYY-MM-DD")
    np_p.set_defaults(func=cmd_new_period)

    rn = sub.add_parser("run", help="Calculate a pay period and generate payslips")
    rn.add_argument("--hours", required=True, help="Path to hours input JSON")
    rn.add_argument("--end", help="Override pay-end date YYYY-MM-DD")
    rn.add_argument("--pay-date", help="Override payment date YYYY-MM-DD")
    rn.add_argument("--output", help="Override output directory")
    rn.add_argument("--dry-run", action="store_true", help="Calculate but do not persist")
    rn.set_defaults(func=cmd_run)

    sh = sub.add_parser("show", help="Show persisted period(s)")
    sh.add_argument("--period", help="A specific YYYY-MM-DD pay-end-date")
    sh.set_defaults(func=cmd_show)

    sub.add_parser("add-employee", help="Interactively add an employee").set_defaults(func=cmd_add_employee)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
