"""Mode B, numbers → story: "Maruti 3x in 3 years". What has to be true, and which stories get there.

From target to today: if the market prices the company at fair value in T years, the price then equals the
value then, and value grows at the cost of equity in the meantime (the return shareholders require). So a price
of P in T years needs a value today of P / (1 + cost of equity)^T. The engine then solves for what has to be true:
  1. one driver at a time (growth, margin, capital efficiency, moat), everything else at the status quo
  2. 2-3 AI stories (each a full set of Mode A drivers), each scaled by the engine on one lever until it hits the
     target exactly, then graded by the story-vs-reality scorecard: Damodaran's 3P test, rule-based.
"""
import hashlib
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy.optimize import brentq

from app.data import cache, damodaran
from app.data.collector import Company
from app.engine.dcf import solve, value
from app.engine.defaults import Setup
from app.llm import LLMProvider
from app.story import story_numbers as sn
from app.story.profile import SYSTEM, BusinessProfile, _facts


@dataclass
class Target:
    kind: Literal["multiple", "price", "market_cap"]
    amount: float  # 3.0 for 3x; a price per share; or a market cap in full currency units
    years: int

    def price(self, a) -> float:
        """The target share price in `years` years."""
        if self.kind == "multiple":
            return a.price * self.amount
        if self.kind == "market_cap":
            return self.amount / a.shares
        return self.amount

    def annual_return(self, a) -> float:
        return (self.price(a) / a.price) ** (1 / self.years) - 1 if a.price else float("nan")

    def value_today(self, setup: Setup) -> float:
        """The value per share today that grows into the target price at the cost of equity."""
        return self.price(setup.assumptions) / (1 + setup.wacc.cost_of_equity) ** self.years

    def label(self, currency: str = "") -> str:
        return (f"{self.amount:g}x" if self.kind == "multiple" else f"{currency} {self.amount:,.0f}".strip()
                + (" market cap" if self.kind == "market_cap" else "")) + f" in {self.years} years"


def requirements(setup: Setup, required: float) -> pd.DataFrame:
    """One driver at a time: the value each needs for the value per share to reach `required`."""
    a = setup.assumptions
    rows = []
    names = {"growth": ("Revenue growth, years 1-5", a.growth_y2_5),
             "target_margin": ("Target operating margin", a.target_margin),
             "sales_to_capital": ("Sales-to-capital", a.sales_to_capital_1_5),
             "terminal_roic": ("Return on capital after year 10",
                               a.terminal_roic if a.terminal_roic is not None else a.terminal_cost_of_capital)}
    for key, (label, now) in names.items():
        x = solve(a, key, required)
        row = {"key": key, "Driver": label, "Required": x, "Status quo": now}
        if key == "growth" and x is not None:
            t = value(a.with_(growth_y1=x, growth_y2_5=x, growth_path=None)).table
            row["Revenue year 5 vs today"] = t.loc["Revenue", 5] / a.revenue
            if x < now and required > value(a).value_per_share:
                row["Note"] = ("Slower growth adds value: at this margin and capital need, growth earns less than "
                               "the cost of capital")
        if x is None:
            row["Note"] = "Cannot get there alone"
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- AI stories, calibrated by the engine
class Route(BaseModel):
    name: str = Field(description="short name, e.g. 'Win the EV entry segment'")
    pitch: str = Field(description="2-3 sentences: what the company does differently, in operating terms")
    market_growth: float = Field(description="annual growth of market units, years 1-5")
    target_share: float = Field(description="share of the market reached, 0-1")
    share_year: int = Field(ge=1, le=10)
    price_growth: float = Field(description="annual growth in revenue per unit")
    target_margin: float
    margin_year: int = Field(ge=1, le=10)
    sales_to_capital: float
    mix: list[sn.MixItem] = Field(default_factory=list)
    lever: Literal["target_share", "target_margin", "market_growth", "price_growth"] = Field(
        description="the one number this story leans on most (share, margin, market growth or price growth, "
                    "as a fraction); the engine moves it until the target is hit")
    risks: list[str] = Field(description="2-3 things that would break this story")


class Routes(BaseModel):
    market: str = Field(description="the market the shares refer to, e.g. 'Indian passenger vehicles'")
    unit_name: str = Field(description="what is counted, plural, e.g. 'cars', 'orders'")
    market_units: float = Field(description="units sold by the whole market in the latest year")
    current_share: float = Field(description="company's share of that market today, 0-1")
    price_per_unit: float = Field(description="revenue from this market / company units sold in it, full currency")
    revenue_share: float = Field(1.0, description="fraction of today's revenue from this market, 0-1")
    base_reason: str = Field(description="one sentence on where the market numbers come from")
    routes: list[Route] = Field(description="2-3 genuinely different routes to the target")


LEVER_RANGE = {"target_share": (0.01, 0.95), "target_margin": (-0.10, 0.60), "market_growth": (-0.05, 0.60),
               "price_growth": (-0.05, 0.40)}
LEVER_LABEL = {"target_share": "Target market share", "target_margin": "Target operating margin",
               "market_growth": "Market growth, years 1-5", "price_growth": "Revenue per unit growth"}


def draft_routes(company: Company, setup: Setup, target: Target, required: float, reqs: pd.DataFrame,
                 llm: LLMProvider, profile: BusinessProfile | None = None) -> Routes:
    p, a = company.profile, setup.assumptions
    bench = damodaran.benchmarks(p["damodaran_industry"], p["region"])
    business = f"\nBusiness: {profile.one_liner}\nMarket: {profile.addressable_market}" if profile else ""
    alone = "; ".join(f"{r['Driver']} {r['Required']:.3g}" if pd.notna(r["Required"]) else
                      f"{r['Driver']} cannot get there alone" for _, r in reqs.iterrows())
    prompt = (f"{_facts(company)}{business}\n"
              f"Price today {a.price:,.2f}. Target: {target.label(p.get('price_currency') or '')} "
              f"({target.annual_return(a):.0%} a year), which needs a value today of {required:,.2f} a share "
              f"(status quo {value(a).value_per_share:,.2f}). One driver alone would need: {alone}.\n"
              f"Status quo: growth {a.growth_y2_5:.1%}, margin {a.target_margin:.1%}, sales-to-capital "
              f"{a.sales_to_capital_1_5:.2f}. Industry ({bench['industry']}): margin {bench['operating_margin']:.1%}, "
              f"sales-to-capital {bench['sales_to_capital']:.2f}.\n\n"
              "Write 2-3 genuinely different business stories that could get the company to this target (e.g. for "
              "a carmaker: win the EV entry segment, an export push, a premium SUV shift). Give the shared market "
              "facts first (market_units x current_share x price_per_unit should be close to the latest revenue x "
              "revenue_share), then each story's drivers. Be realistic: drivers should be the most believable "
              "version of that story; the engine will push the story's lever as far as the target needs and grade "
              "it, so do not stretch numbers to hit the target yourself.")
    key = f"routes:v1:{p['symbol']}:{llm.name}:{hashlib.sha1(prompt.encode()).hexdigest()[:12]}"
    if hit := cache.get(key):
        return Routes.model_validate(hit)
    routes = llm.complete_json(prompt, Routes, system=SYSTEM, retries=2)
    cache.put(key, routes.model_dump())
    return routes


def _drivers(routes: Routes, r: Route) -> sn.StoryDrivers:
    def t(v, why=r.name):
        return {"value": v, "source": "inferred", "reason": why}
    return sn.StoryDrivers.model_validate({
        "headline": r.name, "market": routes.market, "unit_name": routes.unit_name,
        "market_units": t(routes.market_units, routes.base_reason), "market_growth": t(r.market_growth),
        "current_share": t(routes.current_share, routes.base_reason), "target_share": t(r.target_share),
        "share_year": t(r.share_year), "price_per_unit": t(routes.price_per_unit, routes.base_reason),
        "price_growth": t(r.price_growth), "revenue_share": t(routes.revenue_share, routes.base_reason),
        "target_margin": t(r.target_margin), "margin_year": t(r.margin_year),
        "sales_to_capital": t(r.sales_to_capital), "mix": [m.model_dump() for m in r.mix], "red_flags": r.risks})


def _with(d: sn.StoryDrivers, lever: str, x: float) -> sn.StoryDrivers:
    tagged = getattr(d, lever).model_copy(update={"value": x, "reason": "Set by the engine to hit the target"})
    return d.model_copy(update={lever: tagged})


def calibrate(company: Company, setup: Setup, d: sn.StoryDrivers, lever: str, required: float) -> float | None:
    """The lever value that makes the story worth exactly `required` a share, or None if no value gets there."""
    def gap(x):
        return value(sn.build(company, setup, _with(d, lever, x)).assumptions).value_per_share - required

    lo, hi = LEVER_RANGE[lever]
    if lever == "target_share":
        lo = max(lo, d.current_share.value * 0.5)
    grid = np.linspace(lo, hi, 25)
    gaps = [gap(x) for x in grid]
    start = getattr(d, lever).value
    roots = [brentq(gap, x0, x1, xtol=1e-6) for x0, x1, g0, g1 in zip(grid, grid[1:], gaps, gaps[1:]) if g0 * g1 <= 0]
    return min(roots, key=lambda x: abs(x - start)) if roots else None


VERDICT_ORDER = {"probable": 0, "plausible": 1, "possible": 2, "out of reach": 3}


def verdict(card: pd.DataFrame, reached: bool) -> str:
    """Damodaran's 3P test from the scorecard: any red flag makes a story merely possible; plausible allows
    stretches; probable allows at most one."""
    if not reached:
        return "out of reach"
    v = card["Verdict"]
    if (v == sn.RED).any():
        return "possible"
    return "probable" if (v == sn.STRETCH).sum() <= 1 else "plausible"


def lever_check(lever: str, start: float, needed: float | None) -> dict | None:
    """How far the engine had to push the story's lever beyond the AI's realistic version."""
    if needed is None:
        return None
    push = needed - start
    return {"Check": f"Pushed to hit the target: {LEVER_LABEL[lever].lower()}", "Story": f"{needed:.1%}",
            "Reality": f"{start:.1%} realistic", "Verdict": sn.OK if push <= 0.02 else sn.STRETCH if push <= 0.07
            else sn.RED, "Why": f"The target needs {push * 100:+.1f} points beyond the realistic version of this story."}


@dataclass
class RouteResult:
    route: Route
    drivers: sn.StoryDrivers  # with the lever at its calibrated value
    lever_start: float
    lever_value: float | None
    result: sn.StoryResult
    valuation: object
    card: pd.DataFrame
    score: int
    verdict: str


def evaluate(company: Company, setup: Setup, routes: Routes, required: float) -> list[RouteResult]:
    out = []
    for r in routes.routes:
        d = _drivers(routes, r)
        start = getattr(d, r.lever).value
        x = calibrate(company, setup, d, r.lever, required)
        if x is not None:
            d = _with(d, r.lever, x)
        res = sn.build(company, setup, d)
        v = value(res.assumptions)
        card = sn.scorecard(company, setup, res, v)
        if (row := lever_check(r.lever, start, x)) is not None:
            card = pd.concat([pd.DataFrame([row]), card], ignore_index=True)
        score = sn.story_score(card)
        out.append(RouteResult(r, d, start, x, res, v, card, score, verdict(card, x is not None)))
    return sorted(out, key=lambda rr: (VERDICT_ORDER[rr.verdict], -rr.score))
