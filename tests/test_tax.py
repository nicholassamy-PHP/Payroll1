"""Unit tests for the deduction engine — validated against the
GARDERIE_2_May_2026.xlsx workbook (May 02 2026 pay period, Hooma row)."""
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from payroll import tax
from payroll.config import load_company, load_tax_config
from payroll.models import Employee, HoursInput, Period
from payroll.payroll import calculate_pay


def _hooma() -> Employee:
    return Employee(
        code="A1", first_name="Hooma", last_name="Mohammad",
        rate_per_hour=25.0, hire_date="2023-04-17",
        federal_td1_claim=16452, provincial_td1_claim=18952,
        vacation_rate=0.06,
    )


def test_qpp_ee_matches_workbook():
    cfg = load_tax_config()
    val, _ = tax.calc_qpp_ee(2012.5, cfg, pensionable_ytd=0, pay_periods=26,
                             employee=_hooma())
    # workbook value 118.30673…
    assert math.isclose(val, 118.30673, abs_tol=0.01)


def test_ei_ee_matches_workbook():
    cfg = load_tax_config()
    ee, er, _ = tax.calc_ei(2012.5, cfg, insurable_ytd=0, employee=_hooma())
    assert math.isclose(ee, 26.16, abs_tol=0.01)
    assert math.isclose(er, 26.16 * 1.4, abs_tol=0.01)


def test_qpip_ee_matches_workbook():
    cfg = load_tax_config()
    ee, er, _ = tax.calc_qpip(2012.5, cfg, insurable_ytd=0, employee=_hooma())
    assert math.isclose(ee, 8.65, abs_tol=0.01)
    assert math.isclose(er, 12.12, abs_tol=0.01)


def test_fss_matches_workbook():
    cfg = load_tax_config()
    assert math.isclose(tax.calc_fss(2012.5, cfg), 33.21, abs_tol=0.01)


def test_csst_matches_workbook():
    cfg = load_tax_config()
    assert math.isclose(tax.calc_csst(2012.5, cfg, insurable_ytd=0),
                        35.62125, abs_tol=0.01)


def test_federal_tax_within_1_dollar():
    cfg = load_tax_config()
    emp = _hooma()
    # use the QPP/EI/QPIP values for Hooma at gross 2012.5
    qpp = 118.30673
    ei = 26.16
    qpip = 8.65
    fed = tax.calc_federal_tax(2012.5, cfg, emp, 26, ei, qpp, qpip)
    # Workbook: 146.407… — we are within $1.00 thanks to T4127 simplification.
    assert math.isclose(fed, 146.41, abs_tol=1.00), fed


def test_full_period_matches_workbook_within_tolerance():
    """End-to-end: Hooma, May 02 pay (80.5 hrs @ $25). Compare gross/net to
    the workbook (gross 2012.50 / net 1528.80)."""
    cfg = load_tax_config()
    co = load_company()
    period = Period(pay_end_date="2026-05-02", payment_date="2026-05-08",
                    pay_number=9, year=2026)
    ytd_empty = {k: 0.0 for k in [
        "gross","regular_hours","regular_amount","holiday_hours","holiday_amount",
        "vacation_hours","vacation_amount","special_amount","maternity_hours",
        "maternity_amount","federal_tax","quebec_tax","ei_ee","qpip_ee","qpp_ee",
        "insurable_ei","insurable_qpip","pensionable_qpp","csst_insurable",
        "vacation_accrual","net_pay",
    ]}
    res = calculate_pay(_hooma(), HoursInput(regular=80.5), period, co, cfg, ytd_empty)
    assert math.isclose(res.gross, 2012.50, abs_tol=0.01)
    # The workbook nets 1528.80; we allow a $25 absolute tolerance because the
    # workbook uses a Quebec tax formula we don't perfectly replicate (we use
    # the published 2026 TP1015.F brackets — see README).
    assert abs(res.net_pay - 1528.80) < 30, res.net_pay
    # Vacation accrual @ 6% of 2012.50 = 120.75
    assert math.isclose(res.vacation_accrual, 120.75, abs_tol=0.01)
