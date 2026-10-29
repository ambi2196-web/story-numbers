"""The DCF engine against closed-form answers, the reverse solver, and the live-formula Excel sheet."""
import math
from io import BytesIO

from openpyxl import load_workbook

from app.engine.dcf import Assumptions, solve, value
from app.engine.defaults import status_quo, synthetic_rating
from app.excel.workbook import build
from tests.test_ratios_excel import synthetic


def steady(g=0.04, r=0.10, margin=0.2, tax=0.25, s2c=2.0) -> Assumptions:
    """A firm already in steady state: every year looks like the terminal year."""
    return Assumptions(revenue=1000, operating_income=1000 * margin, growth_y1=g, growth_y2_5=g, target_margin=margin,
                       sales_to_capital_1_5=s2c, sales_to_capital_6_10=s2c, effective_tax_rate=tax,
                       marginal_tax_rate=tax, cost_of_capital=r, terminal_cost_of_capital=r, terminal_growth=g,
                       # makes terminal reinvestment (g / ROIC x NOPAT) equal the explicit years' (change in revenue / s2c)
                       terminal_roic=margin * (1 - tax) * (1 + g) * s2c, shares=10)


def test_steady_state_matches_growing_perpetuity():
    a = steady()
    fcff1 = 1000 * 1.04 * 0.2 * 0.75 - 1000 * 0.04 / 2.0
    assert math.isclose(value(a).operating_assets, fcff1 / (0.10 - 0.04), rel_tol=1e-9)


def test_zero_growth_is_a_perpetuity_of_nopat():
    a = steady(g=0.0)
    assert math.isclose(value(a).operating_assets, 1000 * 0.2 * 0.75 / 0.10, rel_tol=1e-9)


def test_bridge_failure_and_per_share():
    a = steady()
    base = value(a).operating_assets
    v = value(a.with_(failure_probability=0.2, distress_proceeds=0.5, cash=50, debt=200, minority_interest=10,
                      non_operating_assets=30))
    assert math.isclose(v.operating_assets, base * 0.9)
    assert math.isclose(v.equity_value, base * 0.9 - 200 - 10 + 50 + 30)
    assert math.isclose(v.value_per_share, v.equity_value / 10)


def test_losses_build_a_tax_shield():
    a = steady().with_(operating_income=-100, target_margin=0.2, margin_year=3, tax_loss_carryforward=500)
    t = value(a).table
    after_tax, ebit = t.loc["After-tax operating income"], t.loc["Operating income (EBIT)"]
    assert after_tax[1] == ebit[1]  # loss year: no tax
    assert after_tax[3] == ebit[3]  # profits sheltered by the carryforward


def test_reverse_solver_recovers_the_assumption():
    a = steady().with_(growth_y1=0.12, growth_y2_5=0.12)
    target = value(a).value_per_share
    assert math.isclose(solve(steady(), "growth", target), 0.12, abs_tol=1e-6)
    m = value(steady().with_(target_margin=0.3)).value_per_share
    assert math.isclose(solve(steady(), "target_margin", m), 0.3, abs_tol=1e-6)
    assert solve(steady(), "target_margin", 1e9) is None  # unreachable within a plausible range


def test_synthetic_rating():
    assert synthetic_rating(math.inf)[0] == "AAA"
    assert synthetic_rating(2.6)[0] == "BBB"
    assert synthetic_rating(-3)[0] == "D"


def test_status_quo_and_dcf_sheet():
    c = synthetic()
    setup = status_quo(c)
    a = setup.assumptions
    assert 0.08 < a.cost_of_capital < 0.20  # an Indian auto company in INR
    assert a.terminal_growth < a.terminal_cost_of_capital <= a.cost_of_capital
    v = value(a)
    wb = load_workbook(BytesIO(build(c, setup, v, {"growth": solve(a, "growth")})))
    assert wb.sheetnames[:2] == ["Summary", "DCF"]
    formulas = [x.value for row in wb["DCF"].iter_rows() for x in row if isinstance(x.value, str) and x.value.startswith("=")]
    assert len(formulas) > 150
