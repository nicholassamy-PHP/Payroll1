"""Flask web interface for the Quebec payroll system."""
from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
import json
from datetime import datetime, timedelta

from payroll.config import load_company, load_tax_config
from payroll.models import HoursInput, Period
from payroll.payroll import run_period, persist_run, ytd_before
from payroll.payslip import render_payslip, render_run, render_summary
from payroll.storage import load_employees, load_year_history

app = Flask(__name__)
REPO_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = REPO_ROOT / "output"


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


app.jinja_env.filters["f2"] = _format_money
app.jinja_env.filters["pct"] = _format_pct


# --------- helpers -------------------------------------------------------- #

def get_next_pay_date(end_date_str: str) -> str:
    """Default: payment 6 days after period end (Garderie's pattern)."""
    end = datetime.fromisoformat(end_date_str)
    pay = end + timedelta(days=6)
    return pay.strftime("%Y-%m-%d")


def list_periods() -> list[dict]:
    """List all completed pay periods (most recent first)."""
    company = load_company()
    history = load_year_history(company.payroll_year)
    return list(reversed(history))


# --------- routes --------------------------------------------------------- #

@app.route("/")
def index():
    company = load_company()
    employees = [e for e in load_employees() if e.active]
    periods = list_periods()
    return render_template("index.html", company=company, employees=employees,
                          periods=periods)


@app.route("/period/<period_end>")
def period_detail(period_end: str):
    """View or enter hours for a period."""
    company = load_company()
    employees = [e for e in load_employees() if e.active]

    # Check if period already exists
    periods = load_year_history(company.payroll_year)
    period_rec = next((p for p in periods if p["period"]["pay_end_date"] == period_end), None)

    if period_rec:
        # Period already run — show results
        return render_template("period_results.html", company=company,
                              period=period_rec["period"], results=period_rec["results"],
                              employees=employees)

    # New period — show entry form
    pay_date = get_next_pay_date(period_end)
    template_hours = {e.first_name: {
        "regular": 0, "holiday_paid": 0, "vacation_paid": 0,
        "special": 0, "maternity": 0, "ssl_hours": 0, "other_amount": 0
    } for e in employees}

    return render_template("period_entry.html", company=company,
                          period_end=period_end, pay_date=pay_date,
                          employees=employees, template_hours=json.dumps(template_hours))


@app.route("/api/run-period", methods=["POST"])
def api_run_period():
    """Calculate payroll for a period."""
    data = request.json
    period_end = data.get("period_end")
    pay_date = data.get("pay_date")
    hours_by_emp = data.get("hours", {})

    company = load_company()
    tax_cfg = load_tax_config()
    employees = load_employees()

    # Parse hours input
    hours_by_emp_obj = {}
    for emp_key, h in hours_by_emp.items():
        if not isinstance(h, dict):
            continue
        fields = HoursInput.__dataclass_fields__
        clean = {k: v for k, v in h.items() if k in fields}
        hours_by_emp_obj[emp_key] = HoursInput(**clean)

    # Build period
    year = int(period_end[:4])
    pay_num = len([p for p in load_year_history(year)
                   if p["period"]["pay_end_date"] < period_end]) + 1
    period = Period(pay_end_date=period_end, payment_date=pay_date,
                    pay_number=pay_num, year=year)

    # Run payroll
    period, rows = run_period(period, hours_by_emp_obj, company, tax_cfg, employees)

    # Persist
    persist_run(period, rows)

    # Generate HTML
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    period_out = OUTPUT_DIR / period_end
    period_out.mkdir(exist_ok=True)

    (period_out / "run.html").write_text(render_run(period, rows, company))
    (period_out / "summary.html").write_text(render_summary(period, rows, company))

    payslips = {}
    for emp, r in rows:
        if r.gross > 0:
            html = render_payslip(emp, r, period, company)
            fn = f"payslip-{emp.first_name}.html"
            (period_out / fn).write_text(html)
            payslips[emp.code] = fn

    return jsonify({
        "success": True,
        "period": {
            "pay_end_date": period.pay_end_date,
            "payment_date": period.payment_date,
            "pay_number": period.pay_number,
        },
        "employees_paid": sum(1 for _, r in rows if r.gross > 0),
        "gross_total": sum(r.gross for _, r in rows),
        "net_total": sum(r.net_pay for _, r in rows),
        "payslips": payslips,
    })


@app.route("/payslip/<period_end>/<emp_name>")
def view_payslip(period_end: str, emp_name: str):
    """Render a single payslip as HTML."""
    period_out = OUTPUT_DIR / period_end / f"payslip-{emp_name}.html"
    if not period_out.exists():
        return "Payslip not found", 404
    return period_out.read_text()


@app.route("/run-sheet/<period_end>")
def view_run_sheet(period_end: str):
    """View the run sheet for a period."""
    period_out = OUTPUT_DIR / period_end / "run.html"
    if not period_out.exists():
        return "Run sheet not found", 404
    return period_out.read_text()


@app.route("/summary/<period_end>")
def view_summary(period_end: str):
    """View the YTD summary as of a period."""
    period_out = OUTPUT_DIR / period_end / "summary.html"
    if not period_out.exists():
        return "Summary not found", 404
    return period_out.read_text()


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
