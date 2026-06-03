"""Statutory deduction engine for Quebec biweekly payroll.

Each function computes one statutory item for a single pay period given:
  * the employee
  * the gross for the current pay
  * relevant YTD totals (so annual ceilings can be respected)
  * the tax_config dict (rates / brackets)
  * the company config (mainly pay_periods_per_year for annualisation)

The math here is validated against the GARDERIE_2_May_2026.xlsx workbook
(see tests/test_tax_matches_workbook.py).
"""
from __future__ import annotations

from .models import Employee


# ---------- helpers -------------------------------------------------------- #

def _apply_ceiling(insurable_ytd: float, gross: float, annual_max: float) -> float:
    """Return the portion of `gross` that is still insurable given the YTD."""
    remaining = max(0.0, annual_max - insurable_ytd)
    return min(gross, remaining)


def _progressive_tax(annual_income: float, brackets: list[dict]) -> float:
    """Apply a progressive bracket table to an annual income.

    `brackets` is a list of {"upper": float|None, "rate": float} ordered low→high.
    """
    if annual_income <= 0:
        return 0.0
    tax = 0.0
    prev = 0.0
    for b in brackets:
        upper = b["upper"]
        rate = b["rate"]
        if upper is None or annual_income <= upper:
            tax += (annual_income - prev) * rate
            return tax
        tax += (upper - prev) * rate
        prev = upper
    return tax


# ---------- individual deductions ----------------------------------------- #

def calc_qpp_ee(gross: float, tax_cfg: dict, pensionable_ytd: float, pay_periods: int,
                employee: Employee) -> tuple[float, float]:
    """Return (qpp_ee, pensionable_amount_used)."""
    if employee.tax_exempt_qpp:
        return 0.0, 0.0
    qpp = tax_cfg["qpp"]
    max_pen = qpp["annual_max_pensionable"]
    pensionable = _apply_ceiling(pensionable_ytd, gross, max_pen)
    if pensionable <= 0:
        return 0.0, 0.0
    per_period_exemption = qpp["basic_exemption_annual"] / pay_periods
    base = max(0.0, pensionable - per_period_exemption)
    return base * qpp["ee_rate"], pensionable


def calc_qpp_er(qpp_ee: float, tax_cfg: dict) -> float:
    qpp = tax_cfg["qpp"]
    if qpp["ee_rate"] == 0:
        return 0.0
    return qpp_ee * (qpp["er_rate"] / qpp["ee_rate"])


def calc_ei(gross: float, tax_cfg: dict, insurable_ytd: float,
            employee: Employee) -> tuple[float, float, float]:
    """Return (ei_ee, ei_er, insurable_amount_used)."""
    if employee.tax_exempt_ei:
        return 0.0, 0.0, 0.0
    ei = tax_cfg["ei"]
    insurable = _apply_ceiling(insurable_ytd, gross, ei["annual_max_insurable"])
    ee = insurable * ei["ee_rate"]
    er = ee * ei["er_multiplier"]
    return ee, er, insurable


def calc_qpip(gross: float, tax_cfg: dict, insurable_ytd: float,
              employee: Employee) -> tuple[float, float, float]:
    """Return (qpip_ee, qpip_er, insurable_amount_used)."""
    if employee.tax_exempt_qpip:
        return 0.0, 0.0, 0.0
    q = tax_cfg["qpip"]
    insurable = _apply_ceiling(insurable_ytd, gross, q["annual_max_insurable"])
    return insurable * q["ee_rate"], insurable * q["er_rate"], insurable


def calc_fss(gross: float, tax_cfg: dict) -> float:
    return gross * tax_cfg["fss"]["rate"]


def calc_csst(gross: float, tax_cfg: dict, insurable_ytd: float) -> float:
    c = tax_cfg["csst"]
    insurable = _apply_ceiling(insurable_ytd, gross, c["annual_max_insurable"])
    return insurable * c["rate"]


def calc_federal_tax(
    gross: float, tax_cfg: dict, employee: Employee,
    pay_periods: int, ei_ee_pp: float, qpp_ee_pp: float, qpip_ee_pp: float
) -> float:
    """Simplified CRA T4127 federal-tax-for-Quebec calculation.

    annual_taxable = gross × pp
    tax = progressive(annual) − credits
    credits @ 15% = TD1 + CEA + annualised EI + QPP + QPIP employee shares
    apply Quebec abatement of 16.5%
    return per-pay (annual_tax/pp) + additional flat tax per pay.
    """
    if employee.tax_exempt_federal:
        return employee.additional_federal_tax

    fed = tax_cfg["federal"]
    annual_gross = gross * pay_periods
    annual_ei = ei_ee_pp * pay_periods
    annual_qpp = qpp_ee_pp * pay_periods
    annual_qpip = qpip_ee_pp * pay_periods

    annual_tax = _progressive_tax(annual_gross, fed["brackets"])

    credit_base = (
        employee.federal_td1_claim
        + fed["canada_employment_amount"]
        + annual_ei + annual_qpp + annual_qpip
    )
    credits = credit_base * fed["credit_rate"]
    annual_tax = max(0.0, annual_tax - credits)

    # Quebec residents: 16.5% federal tax abatement
    annual_tax *= (1 - fed["quebec_abatement"])

    return annual_tax / pay_periods + employee.additional_federal_tax


def calc_quebec_tax(
    gross: float, tax_cfg: dict, employee: Employee,
    pay_periods: int, ei_ee_pp: float, qpp_ee_pp: float, qpip_ee_pp: float
) -> float:
    """TP1015.F provincial tax — progressive brackets less basic personal
    amount credit and worker deduction credit. Per-employee additional tax
    is added on top."""
    if employee.tax_exempt_quebec:
        return employee.additional_quebec_tax

    qc = tax_cfg["quebec"]
    annual_gross = gross * pay_periods

    # worker deduction (deduction pour travailleur) — reduces taxable income
    worker_ded = min(annual_gross * qc["worker_deduction_rate"], qc["worker_deduction_max"])
    annual_taxable = max(0.0, annual_gross - worker_ded)

    annual_tax = _progressive_tax(annual_taxable, qc["brackets"])

    # Non-refundable credits @ credit_rate: basic personal amount only.
    # (Quebec does not credit federal EI; QPP/QPIP/EI are payroll-deductible
    # on the Quebec side via the worker deduction.)
    credits = employee.provincial_td1_claim * qc["credit_rate"]
    annual_tax = max(0.0, annual_tax - credits)

    return annual_tax / pay_periods + employee.additional_quebec_tax
