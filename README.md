# Payroll1 — Quebec Biweekly Payroll System

A self-contained payroll system that replaces the multi-sheet Excel workflow
(employee tabs + period sheet + YTD summary + payslip sheet) with an
automated process: client sends hours → system calculates gross, federal
and Quebec deductions, vacation/holiday accrual, and YTD totals → system
emits a payslip per employee and a payroll run sheet.

Modelled on Garderie La Belle Academie Inc. (the `GARDERIE_2_May_2026.xlsx`
workbook), but driven entirely by JSON config so any Quebec employer with
the same statutory deductions can use it.

## What the system replaces

| Workbook artefact                         | Now produced by               |
| ----------------------------------------- | ----------------------------- |
| Per-period sheet (`May 02`)               | `output/<period>/run.html`    |
| Per-employee payslip sheet (`Hooma`, …)   | `output/<period>/payslip-*.html` |
| `Summary-2026` YTD roll-up                | `output/<period>/summary.html`|
| Top-of-sheet rates row                    | `data/tax_config.json`        |
| Address / hire-date / payee block         | `data/employees.json`         |

## Layout

```
data/
  company.json        Company name, address, year, pay frequency
  tax_config.json     Statutory rates & ceilings (federal, Quebec, EI, QPIP, QPP, FSS, CSST)
  employees.json      Employee master (name, address, DOB, tax IDs, rate, TD1 claim, …)
  history/<year>.json Persisted pay-period results, used to compute YTD
examples/
  may02_2026.hours.json   Sample client hours-input file
payroll/                 Application package
  cli.py             Entry point (`python -m payroll <cmd>`)
  config.py          Loads company + tax config
  models.py          Dataclasses for Employee, PayInput, PayResult, Period
  storage.py         JSON file I/O for master data + history
  tax.py             Statutory deduction engine (matches workbook math)
  payroll.py         Per-employee + per-period orchestration
  payslip.py         HTML payslip + run sheet + summary renderer
templates/
  payslip.html, run.html, summary.html  Jinja-style HTML templates
output/<period>/     Generated artefacts (HTML, JSON dump)
```

## Process — entering a pay period

```bash
# 1. Show employees and the next pay period
python -m payroll status

# 2. Generate a blank hours input template for the period
python -m payroll new-period --end 2026-05-02 --pay-date 2026-05-08
# -> writes examples/<period>.hours.json with one row per active employee

# 3. Open the JSON, fill in hours per employee:
#    {
#      "Hooma":  {"regular": 80.5, "holiday_paid": 0, "vacation_paid": 0,
#                 "special": 0,    "maternity": 0,  "ssl_hours": 0},
#      ...
#    }

# 4. Run payroll for the period
python -m payroll run --hours examples/2026-05-02.hours.json

# 5. Generated artefacts land in output/2026-05-02/:
#    run.html       (statutory run sheet — like the workbook's `May 02` tab)
#    summary.html   (YTD summary — like `Summary-2026`)
#    payslip-<employee>.html   per employee
#    period.json    (raw results, used to roll YTD forward)

# 6. Print or PDF the HTML; the YTD is now persisted in data/history/2026.json
```

## Employee onboarding

Add a record to `data/employees.json`:

```json
{
  "code": "A6",
  "first_name": "Nadin",
  "last_name": "Al Katan",
  "address_line_1": "...",
  "city": "Laval",
  "province": "QC",
  "postal_code": "...",
  "date_of_birth": "1980-09-11",
  "hire_date": "2023-04-17",
  "sin": "295 781 694",
  "employee_id": "8PB...",
  "occupation": "Carer",
  "rate_per_hour": 18.00,
  "federal_td1_claim": 16452,
  "provincial_td1_claim": 18952,
  "vacation_rate": 0.06,
  "active": true,
  "ytd_opening": {       # optional — only when migrating mid-year
    "regular_hours": 0, "gross": 0, ...
  }
}
```

## How calculations work

All formulas are validated against the `GARDERIE_2_May_2026.xlsx` workbook —
running the seeded employees against the May 02 hours reproduces the
workbook to within rounding (see `tests/`).

| Item                  | Formula                                                 |
| --------------------- | ------------------------------------------------------- |
| Gross                 | `hours × rate` (sum over all earning types)             |
| Vacation accrual      | `gross × vacation_rate` (default 6%)                    |
| QPP-EE / QPP-ER       | `(gross − 3500/26) × 0.063`, capped at $74 600 YTD      |
| EI-EE                 | `gross × 0.013`, capped at $68 900 YTD                  |
| EI-ER                 | `gross × 0.01820 (= EI-EE × 1.4)`                       |
| QPIP-EE / QPIP-ER     | `gross × 0.0043 / 0.00602`, capped at $103 000 YTD      |
| FSS (employer)        | `gross × 0.0165`                                        |
| CSST (employer)       | `gross × 0.0177`, capped at $88 000 YTD                 |
| Federal tax           | CRA T4127 simplified: `(annual_gross × bracket) − K` with credits for basic personal amount, CEA, EI/QPP/QPIP employee shares, then × 0.835 Quebec abatement |
| Quebec tax            | TP1015.F brackets minus credits for basic personal amount and worker deduction |
| Net pay               | `gross − fed − qc − ei_ee − qpip_ee − qpp_ee`           |

YTD ceilings are applied: once an employee hits the EI/QPP/QPIP annual
maximum, further pays stop withholding for the rest of the year and the
ceiling resets on Jan 1.

Per-employee overrides:
* `federal_td1_claim`, `provincial_td1_claim` — for non-basic claim codes
* `additional_federal_tax`, `additional_quebec_tax` — flat $ extra per pay
* `tax_exempt_federal`, `tax_exempt_quebec` — zero out income tax (e.g. status Indian on reserve)

## Pay frequency

Default is biweekly (26 pays/year), matching the workbook. `company.json`
exposes `pay_periods_per_year` so weekly (52), semi-monthly (24), or
monthly (12) employers can adjust without code changes.

## Files generated per run

For period `2026-05-02`:

```
output/2026-05-02/
  run.html                Side-by-side per-employee statutory run sheet
  summary.html            YTD rollup as of this period
  payslip-Hooma.html      Individual payslip (print to PDF for delivery)
  payslip-Nadin.html
  ...
  period.json             Persisted results
```

The same data also lands in `data/history/2026.json` so the next period's
YTD picks up automatically.
