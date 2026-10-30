"""The "status quo" story: default DCF assumptions for a real company, each tagged with where it came from.

Cost of capital is built bottom-up the way Damodaran does it: in US dollars (Treasury rate + relevered industry
beta x the country's equity risk premium; debt priced off a synthetic rating from interest coverage), then
converted to the reporting currency with the inflation differential.
"""
import math
from dataclasses import dataclass, field

import pandas as pd

from app.data import damodaran
from app.data.collector import Company, fiscal_year
from app.data.ratios import compute
from app.engine.dcf import Assumptions

# Interest coverage -> (rating, default spread) for large non-financial firms. Approximation of Damodaran's
# synthetic rating table (ratings.xls); his January update moves these by a few basis points.
SYNTHETIC_RATINGS = [(8.5, "AAA", 0.0059), (6.5, "AA", 0.0078), (5.5, "A+", 0.0098), (4.25, "A", 0.0108),
                     (3.0, "A-", 0.0122), (2.5, "BBB", 0.0156), (2.25, "BB+", 0.0200), (2.0, "BB", 0.0240),
                     (1.75, "B+", 0.0298), (1.5, "B", 0.0369), (1.25, "B-", 0.0450), (0.8, "CCC", 0.0613),
                     (0.65, "CC", 0.0846), (0.2, "C", 0.1178), (-math.inf, "D", 0.1700)]
CURRENCY_REGION = {"USD": "US", "INR": "India", "EUR": "Europe", "JPY": "Japan", "CNY": "China"}
FINANCIAL_INDUSTRIES = ("bank", "financial svcs", "insurance", "brokerage", "investments & asset")


@dataclass
class CostOfCapital:
    currency: str
    riskfree_usd: float
    inflation_local: float
    inflation_usd: float
    riskfree_local: float
    unlevered_beta: float
    levered_beta: float
    equity_risk_premium: float
    cost_of_equity: float
    rating: str
    pretax_cost_of_debt: float
    marginal_tax_rate: float
    debt_weight: float
    cost_of_capital: float  # local currency
    terminal_cost_of_capital: float  # local currency, beta moving to 1 in stable growth
    default_spread: float = 0.0  # country + company spread over the US$ risk-free rate

    def local(self, usd_rate: float) -> float:
        return (1 + usd_rate) * (1 + self.inflation_local) / (1 + self.inflation_usd) - 1


@dataclass
class Setup:
    assumptions: Assumptions
    wacc: CostOfCapital
    warnings: list[str] = field(default_factory=list)
    is_financial: bool = False


def synthetic_rating(coverage: float) -> tuple[str, float]:
    if not math.isfinite(coverage):
        coverage = 100.0  # no interest expense: as safe as it gets
    return next((r, s) for floor, r, s in SYNTHETIC_RATINGS if coverage > floor)


def _num(x, default=0.0) -> float:
    return float(x) if x is not None and pd.notna(x) else default


def cost_of_capital(company: Company, ratios: pd.DataFrame) -> CostOfCapital:
    p, latest = company.profile, company.financials.columns[-1]
    fin = company.financials[latest]
    market = damodaran.market_inputs(p["region"] if p["region"] != "Global" else "Global")
    try:
        country = damodaran.country_risk(p.get("country") or "")
        erp, country_spread, marginal = (country["equity_risk_premium"], country["default_spread"], country["tax_rate"])
    except KeyError:
        erp, country_spread, marginal = (market["equity_risk_premium"], market["default_spread"],
                                         market["marginal_tax_rate"])
    currency = p.get("currency") or "USD"
    infl = damodaran.market_inputs(CURRENCY_REGION.get(currency, "US"))
    inflation_local, inflation_usd = infl.get("inflation_local", 0.025), infl.get("inflation_usd", 0.025)

    betas = damodaran.load_industry("beta", p["region"])
    row = betas[betas["Industry Name"].str.lower() == p["damodaran_industry"].lower()].iloc[0]
    unlevered = float(row.get("Unlevered beta corrected for cash", row["Unlevered beta"]))
    debt, equity = _num(fin.get("total_debt")), _num(p.get("market_cap"))
    if equity > 0:
        wd = debt / (debt + equity)
    else:  # no market price (fictional or unlisted): borrow the industry's typical financing mix
        wd = damodaran.benchmarks(p["damodaran_industry"], p["region"])["debt_to_capital"] if debt > 0 else 0.0
    d_e = wd / (1 - wd) if wd < 1 else 0.0
    levered = unlevered * (1 + (1 - marginal) * d_e)

    rf = market["treasury_rate"]
    # Median of the last three years, so one bad year (a strike, a cyber attack) does not reprice all the debt.
    coverage = ratios.loc["interest_coverage"].dropna().tail(3)
    if len(coverage):
        cov = float(coverage.median())
    else:  # no interest data: safe only if it is profitable
        cov = math.inf if _num(fin.get("operating_income")) > 0 or not debt else 0.0
    rating, spread = synthetic_rating(cov)
    kd = rf + country_spread + spread
    ke = rf + levered * erp
    wacc_usd = (1 - wd) * ke + wd * kd * (1 - marginal)
    # Stable growth: beta moves to 1, but a maturing firm never becomes riskier than it is today.
    terminal_usd = min(wacc_usd, (1 - wd) * (rf + erp) + wd * kd * (1 - marginal))
    c = CostOfCapital(currency, rf, inflation_local, inflation_usd, 0.0, unlevered, levered, erp, 0.0, rating, 0.0,
                      marginal, wd, 0.0, 0.0)
    c.default_spread = country_spread + spread
    c.riskfree_local, c.cost_of_equity, c.pretax_cost_of_debt = c.local(rf), c.local(ke), c.local(kd)
    c.cost_of_capital, c.terminal_cost_of_capital = c.local(wacc_usd), c.local(terminal_usd)
    return c


def status_quo(company: Company) -> Setup:
    """Default assumptions: the company keeps doing what it has been doing, judged against its industry."""
    p, fin = company.profile, company.financials
    ratios = compute(fin)
    latest = fin.columns[-1]
    f = fin[latest]
    bench = damodaran.benchmarks(p["damodaran_industry"], p["region"])
    wacc = cost_of_capital(company, ratios)
    warnings, src = [], {}

    is_financial = any(k in p["damodaran_industry"].lower() for k in FINANCIAL_INDUSTRIES)
    if is_financial:
        warnings.append("Banks and insurers fund themselves with debt as raw material, so a free-cash-flow-to-firm "
                        "DCF does not fit them. Treat this value as indicative only; a dividend/excess-return "
                        "model for financials is planned.")

    if p.get("period_note"):
        warnings.append(p["period_note"])
    rev = fin.loc["revenue"].dropna()
    k = min(3, len(rev) - 1)  # three periods back, measured in actual years (fiscal years can have gaps)
    n = fiscal_year(rev.index[-1]) - fiscal_year(rev.index[-1 - k]) if k > 0 else 0
    cagr = (rev.iloc[-1] / rev.iloc[-1 - k]) ** (1 / n) - 1 if n > 0 and rev.iloc[-1 - k] > 0 else 0.05
    growth = min(max(cagr, 0.0), 0.25)
    src["growth"] = f"{n}-year revenue CAGR ({cagr:.1%})" + (", capped" if growth != cagr else "")

    margins = ratios.loc["operating_margin"].dropna()
    target = float(margins.mean()) if len(margins) else math.nan
    src["target_margin"] = f"Company {len(margins)}-year average operating margin"
    if not target > 0:  # young or loss-making: the default story is that it becomes a typical industry player
        target = bench["operating_margin"]
        src["target_margin"] = f"Damodaran {p['region']} {p['damodaran_industry']} average (company is loss-making)"

    s2c_hist = ratios.loc["sales_to_capital"].replace([math.inf, -math.inf], math.nan).dropna()
    s2c = float(s2c_hist.median()) if len(s2c_hist) else math.nan
    if not 0.25 <= s2c <= 6:
        if math.isfinite(s2c):
            warnings.append(f"The company's own sales-to-capital ({s2c:.1f}x) is distorted (invested capital near "
                            f"zero or negative), so the industry ratio is used instead.")
        s2c = bench["sales_to_capital"]
        src["sales_to_capital"] = f"Damodaran {p['region']} {p['damodaran_industry']} average"
    else:
        src["sales_to_capital"] = "Company median sales-to-capital"

    tax_hist = ratios.loc["effective_tax_rate"].dropna().tail(3)
    eff = min(max(float(tax_hist.mean()), 0.0), wacc.marginal_tax_rate) if len(tax_hist) else wacc.marginal_tax_rate
    src["effective_tax_rate"] = "Company 3-year average effective tax rate"
    src["marginal_tax_rate"] = f"Damodaran marginal tax rate, {p.get('country')}"
    src["cost_of_capital"] = (f"Bottom-up: beta {wacc.levered_beta:.2f}, ERP {wacc.equity_risk_premium:.2%}, "
                              f"rating {wacc.rating}, debt {wacc.debt_weight:.0%} of capital")
    src["terminal_cost_of_capital"] = "Beta moves to 1 in stable growth (capped at today's rate)"
    src["terminal_roic"] = "Equal to the cost of capital: no excess returns forever"
    src["terminal_growth"] = f"Risk-free rate in {wacc.currency} (growth cannot exceed it forever)"

    price = p.get("price")
    if p.get("price_currency") and p.get("currency") and p["price_currency"] != p["currency"]:
        warnings.append(f"Shares trade in {p['price_currency']} but report in {p['currency']}; the price "
                        f"comparison is skipped.")
        price = None
    shares = _num(p.get("shares_outstanding")) or _num(f.get("diluted_shares"), 1.0)

    a = Assumptions(
        revenue=float(f["revenue"]), operating_income=float(f["operating_income"]),
        growth_y1=growth, growth_y2_5=growth, target_margin=target, margin_year=5,
        sales_to_capital_1_5=s2c, sales_to_capital_6_10=s2c,
        effective_tax_rate=eff, marginal_tax_rate=wacc.marginal_tax_rate,
        cost_of_capital=wacc.cost_of_capital, terminal_cost_of_capital=wacc.terminal_cost_of_capital,
        terminal_growth=wacc.riskfree_local,
        cash=_num(f.get("cash")),
        non_operating_assets=_num(f.get("financial_investments")) + _num(f.get("equity_investments")),
        debt=_num(f.get("total_debt")), minority_interest=_num(f.get("minority_interest")),
        shares=shares, price=price, sources=src,
    )
    return Setup(a, wacc, warnings, is_financial)
