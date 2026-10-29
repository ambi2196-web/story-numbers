"""Damodaran-style FCFF DCF (the "Ginzu" structure): ten explicit years, then a stable-growth terminal value.

Pure maths, no data access: everything comes in through `Assumptions`, so a story (Mode A), a solver (Mode B)
and the Excel export all run the exact same model.

Year by year:
  revenue growth   year 1 = g1, years 2-5 = g2_5, years 6-10 fall linearly to the terminal growth rate
  operating margin moves linearly from today's margin to the target margin by `margin_year`, then stays
  tax rate         effective rate for years 1-5, moving linearly to the marginal rate by year 10
  reinvestment     change in revenue / sales-to-capital
  cost of capital  initial rate for years 1-5, moving linearly to the terminal rate by year 10
Terminal year: growth g, reinvestment = g / terminal ROIC, so a firm earning its cost of capital adds no value
by growing. Losses build a tax-loss carryforward that shelters later profits.
"""
from dataclasses import asdict, dataclass, field, replace

import numpy as np
import pandas as pd
from scipy.optimize import brentq

YEARS = 10


@dataclass
class Assumptions:
    # base year (latest fiscal year), in the reporting currency
    revenue: float
    operating_income: float
    # the story
    growth_y1: float
    growth_y2_5: float
    target_margin: float
    margin_year: int = 5
    sales_to_capital_1_5: float = 1.5
    sales_to_capital_6_10: float = 1.5
    # tax and risk
    effective_tax_rate: float = 0.25
    marginal_tax_rate: float = 0.25
    cost_of_capital: float = 0.10
    terminal_cost_of_capital: float = 0.09
    terminal_growth: float = 0.04
    terminal_roic: float | None = None  # None = terminal cost of capital (no excess returns forever)
    tax_loss_carryforward: float = 0.0
    failure_probability: float = 0.0
    distress_proceeds: float = 0.5  # fraction of the going-concern value recovered if the firm fails
    # bridge from operating assets to value per share
    cash: float = 0.0
    non_operating_assets: float = 0.0  # cross holdings and long-term financial investments
    debt: float = 0.0
    minority_interest: float = 0.0
    shares: float = 1.0
    price: float | None = None
    # where each number came from: {"target_margin": "Damodaran India Auto & Truck average", ...}
    sources: dict = field(default_factory=dict)

    @property
    def current_margin(self) -> float:
        return self.operating_income / self.revenue if self.revenue else 0.0

    def with_(self, **changes) -> "Assumptions":
        return replace(self, **changes)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Valuation:
    assumptions: Assumptions
    table: pd.DataFrame  # rows = line items, columns = "Base", 1..10, "Terminal"
    pv_fcff: float
    terminal_value: float
    pv_terminal_value: float
    operating_assets: float  # after the failure adjustment
    equity_value: float
    value_per_share: float

    @property
    def upside(self) -> float | None:
        p = self.assumptions.price
        return self.value_per_share / p - 1 if p else None

    @property
    def terminal_share(self) -> float:
        total = self.pv_fcff + self.pv_terminal_value
        return self.pv_terminal_value / total if total else float("nan")


def _paths(a: Assumptions) -> dict[str, np.ndarray]:
    t = np.arange(1, YEARS + 1)
    growth = np.where(t == 1, a.growth_y1, a.growth_y2_5)
    late = t > 5
    growth[late] = a.growth_y2_5 - (a.growth_y2_5 - a.terminal_growth) * (t[late] - 5) / 5
    m0, years = a.current_margin, max(a.margin_year, 1)
    margin = np.where(t >= years, a.target_margin, m0 + (a.target_margin - m0) * t / years)
    tax = np.where(late, a.effective_tax_rate + (a.marginal_tax_rate - a.effective_tax_rate) * (t - 5) / 5,
                   a.effective_tax_rate)
    s2c = np.where(late, a.sales_to_capital_6_10, a.sales_to_capital_1_5)
    wacc = np.where(late, a.cost_of_capital + (a.terminal_cost_of_capital - a.cost_of_capital) * (t - 5) / 5,
                    a.cost_of_capital)
    return {"growth": growth, "margin": margin, "tax": tax, "s2c": s2c, "wacc": wacc}


def value(a: Assumptions) -> Valuation:
    if a.terminal_growth >= a.terminal_cost_of_capital:
        raise ValueError("Terminal growth must be below the terminal cost of capital.")
    p = _paths(a)
    revenue = a.revenue * np.cumprod(1 + p["growth"])
    ebit = revenue * p["margin"]

    nol, taxes = a.tax_loss_carryforward, np.zeros(YEARS)
    for i in range(YEARS):  # losses add to the carryforward; profits use it up before paying tax
        if ebit[i] < 0:
            nol += -ebit[i]
        else:
            used = min(nol, ebit[i])
            nol -= used
            taxes[i] = (ebit[i] - used) * p["tax"][i]
    nopat = ebit - taxes
    reinvestment = np.diff(np.concatenate([[a.revenue], revenue])) / p["s2c"]
    fcff = nopat - reinvestment
    discount = np.cumprod(1 / (1 + p["wacc"]))
    pv = fcff * discount

    g, r = a.terminal_growth, a.terminal_cost_of_capital
    roic = a.terminal_roic if a.terminal_roic is not None else r
    t_revenue = revenue[-1] * (1 + g)
    t_ebit = t_revenue * a.target_margin
    t_nopat = t_ebit * (1 - a.marginal_tax_rate) if t_ebit > 0 else t_ebit
    t_reinvestment = t_nopat * g / roic if t_nopat > 0 else 0.0
    t_fcff = t_nopat - t_reinvestment
    terminal_value = t_fcff / (r - g)
    pv_tv = terminal_value * discount[-1]

    going_concern = pv.sum() + pv_tv
    operating = going_concern * (1 - a.failure_probability) + going_concern * a.distress_proceeds * a.failure_probability
    equity = operating - a.debt - a.minority_interest + a.cash + a.non_operating_assets
    per_share = equity / a.shares

    cols = ["Base"] + list(range(1, YEARS + 1)) + ["Terminal"]
    nan = np.nan
    table = pd.DataFrame({
        "Revenue growth": [nan, *p["growth"], g],
        "Revenue": [a.revenue, *revenue, t_revenue],
        "Operating margin": [a.current_margin, *p["margin"], a.target_margin],
        "Operating income (EBIT)": [a.operating_income, *ebit, t_ebit],
        "Tax rate": [a.effective_tax_rate, *p["tax"], a.marginal_tax_rate],
        "After-tax operating income": [nan, *nopat, t_nopat],
        "Sales-to-capital": [nan, *p["s2c"], nan],
        "Reinvestment": [nan, *reinvestment, t_reinvestment],
        "FCFF": [nan, *fcff, t_fcff],
        "Cost of capital": [nan, *p["wacc"], r],
        "Cumulative discount factor": [nan, *discount, nan],
        "PV of FCFF": [nan, *pv, nan],
    }, index=cols).T
    return Valuation(a, table, float(pv.sum()), float(terminal_value), float(pv_tv), float(operating),
                     float(equity), float(per_share))


# Drivers the reverse solver can move, with a search range and how one number maps onto the assumptions.
DRIVERS = {
    "growth": ((-0.10, 0.60), lambda a, x: a.with_(growth_y1=x, growth_y2_5=x)),
    "target_margin": ((-0.20, 0.80), lambda a, x: a.with_(target_margin=x)),
    "sales_to_capital": ((0.1, 20.0), lambda a, x: a.with_(sales_to_capital_1_5=x, sales_to_capital_6_10=x)),
    # the moat: return on capital earned on new investment forever (lowest = cost of capital, no excess return)
    "terminal_roic": ((None, 1.0), lambda a, x: a.with_(terminal_roic=x)),
}


def solve(a: Assumptions, driver: str, target_per_share: float | None = None) -> float | None:
    """Reverse DCF: the value of one driver that makes value per share equal the target (default: today's price).
    Returns None when no value in the driver's plausible range gets there."""
    target = target_per_share if target_per_share is not None else a.price
    if target is None:
        raise ValueError("Need a target value per share or a market price.")
    (lo, hi), apply = DRIVERS[driver]
    lo = a.terminal_cost_of_capital if lo is None else lo

    def gap(x: float) -> float:
        return value(apply(a, x)).value_per_share - target

    grid = np.linspace(lo, hi, 41)
    gaps = [gap(x) for x in grid]
    for x0, x1, g0, g1 in zip(grid, grid[1:], gaps, gaps[1:]):
        if g0 == 0:
            return float(x0)
        if g0 * g1 < 0:
            return float(brentq(gap, x0, x1, xtol=1e-7))
    return None
