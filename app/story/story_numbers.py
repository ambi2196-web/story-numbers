"""Mode A, story → numbers: "Maruti takes 70% of India's car market and 80% of its cars are EVs".

The AI reads the story and fills a driver sheet (market size and growth, share, price per unit, margin path,
capital intensity), tagging each number as *stated* by you or *inferred* by it. Revenue is then built bottom-up:
units sold = market units x share, revenue = today's revenue scaled by units and price. The same DCF engine
values it, and a rule-based scorecard checks every driver against the company's own history and its industry.
"""
import dataclasses
import hashlib
import math
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from app.data import cache, damodaran
from app.data.collector import Company
from app.data.ratios import compute
from app.engine.dcf import YEARS, Assumptions, Valuation, _paths
from app.engine.defaults import Setup
from app.llm import LLMProvider
from app.story.profile import SYSTEM, BusinessProfile, _facts


class Tagged(BaseModel):
    value: float
    source: Literal["stated", "inferred"] = Field(description="'stated' only if the user's story gives this number")
    reason: str = Field(description="one short sentence: where the number comes from")


class MixItem(BaseModel):
    name: str = Field(description="e.g. 'Electric vehicles'")
    share_of_units: float = Field(description="fraction of units sold once the story plays out, 0-1")
    today: float | None = Field(None, description="fraction today, 0-1; null if unknown")
    source: Literal["stated", "inferred"]
    effect: str = Field(description="how this mix shift changes price, margin or capital needs")


class StoryDrivers(BaseModel):
    headline: str = Field(description="the user's story restated in one line")
    market: str = Field(description="the market the share refers to, e.g. 'Indian passenger vehicles'")
    unit_name: str = Field(description="what is counted, plural, e.g. 'cars', 'subscribers', 'orders'")
    market_units: Tagged = Field(description="units sold by the whole market in the latest year")
    market_growth: Tagged = Field(description="annual growth of market units, years 1-5")
    current_share: Tagged = Field(description="company's share of that market today, 0-1")
    target_share: Tagged = Field(description="share the story reaches, 0-1")
    share_year: Tagged = Field(description="year (1-10) the target share is reached")
    price_per_unit: Tagged = Field(description="company's revenue per unit today, full currency units (not millions)")
    price_growth: Tagged = Field(description="annual growth in revenue per unit (inflation plus mix)")
    revenue_share: Tagged = Field(
        Tagged(value=1.0, source="inferred", reason="All of the company's revenue comes from this market"),
        description="fraction of the company's revenue today that comes from this market, 0-1 (1 if all of it)")
    target_margin: Tagged = Field(description="operating margin once the story plays out, e.g. 0.12")
    margin_year: Tagged = Field(description="year (1-10) the target margin is reached")
    sales_to_capital: Tagged = Field(description="revenue added per unit of new capital invested (capex intensity)")
    mix: list[MixItem] = Field(default_factory=list, description="product-mix shifts in the story, if any")
    red_flags: list[str] = Field(description="2-4 places the story clashes with facts about the market, with numbers")


DRIVER_ROWS = [  # key, label, display unit ("pct", "x", "n", "money", "year")
    ("market_units", "Market size today", "n"), ("market_growth", "Market growth, years 1-5", "pct"),
    ("current_share", "Market share today", "pct"), ("target_share", "Target market share", "pct"),
    ("share_year", "Year target share is reached", "year"), ("price_per_unit", "Revenue per unit today", "money"),
    ("price_growth", "Revenue per unit growth", "pct"),
    ("revenue_share", "Share of revenue from this market", "pct"), ("target_margin", "Target operating margin", "pct"),
    ("margin_year", "Year target margin is reached", "year"), ("sales_to_capital", "Sales-to-capital", "x"),
]


def draft(company: Company, setup: Setup, story_text: str, llm: LLMProvider,
          profile: BusinessProfile | None = None) -> StoryDrivers:
    p, a = company.profile, setup.assumptions
    bench = damodaran.benchmarks(p["damodaran_industry"], p["region"])
    business = ""
    if profile:
        business = (f"\nBusiness: {profile.one_liner}\nMarket: {profile.addressable_market}\nUnit drivers (AI "
                    "estimates): " + "; ".join(f"{d.name} = {d.latest_value} {d.unit}" for d in profile.unit_drivers))
    prompt = (f"{_facts(company)}{business}\n"
              f"Status quo: growth {a.growth_y2_5:.1%}, target margin {a.target_margin:.1%}, sales-to-capital "
              f"{a.sales_to_capital_1_5:.2f}. Industry ({bench['industry']}, {bench['region']}): operating margin "
              f"{bench['operating_margin']:.1%}, sales-to-capital {bench['sales_to_capital']:.2f}.\n\n"
              f"The user's story: \"{story_text}\"\n\n"
              "Turn this story into valuation drivers. Use the user's numbers exactly where they give them (tag "
              "'stated'); infer the rest from the company's history, the industry and what you know of the market "
              "(tag 'inferred'), and say why in each reason. Pick the market the user's share refers to; "
              "current_share must be the company's real share of it today. revenue_share is the part of today's "
              "revenue that comes from this market (below 1 when the story is about one business line, e.g. "
              "quick commerce inside a food-delivery company); the rest keeps its status-quo growth. "
              "price_per_unit is the revenue from this market divided by the company's units sold in it, in full "
              "currency (e.g. 700000 for a ₹7 lakh car). Check before answering: market_units x current_share x "
              "price_per_unit must be close to the latest revenue x revenue_share shown above (same year, same "
              "accounting); if not, fix the least certain number and say so in its reason. If the story changes the product mix (e.g. 80% "
              "EVs), list it in mix and carry its effect into price per unit, margin and sales-to-capital (EVs need "
              "batteries and new plants). red_flags: where the user's story clashes with known facts, with numbers (about the story "
              "itself, not about the status-quo inputs, which your drivers replace).")
    key = f"story_drivers:v3:{p['symbol']}:{llm.name}:{hashlib.sha1(prompt.encode()).hexdigest()[:12]}"
    if hit := cache.get(key):
        return StoryDrivers.model_validate(hit)
    drivers = llm.complete_json(prompt, StoryDrivers, system=SYSTEM, retries=2)
    cache.put(key, drivers.model_dump())
    return drivers


@dataclasses.dataclass
class StoryResult:
    drivers: StoryDrivers
    path: pd.DataFrame  # rows = years 0-10: market units, share, units, price, revenue, growth
    assumptions: Assumptions


def fade_factor(mg: float, pg: float, terminal_growth: float) -> float:
    """k such that (1 + k mg)(1 + k pg) = 1 + terminal growth: market and price growth shrink in proportion."""
    a, b = mg * pg, mg + pg
    try:
        return terminal_growth / b if abs(a) < 1e-12 else (-b + math.sqrt(b * b + 4 * a * terminal_growth)) / (2 * a)
    except (ZeroDivisionError, ValueError):
        return 1.0


def _rates(d: StoryDrivers, terminal_growth: float) -> tuple[np.ndarray, np.ndarray]:
    """Market-unit and price growth for years 1-10: the story's rates for 1-5, then both fade in proportion so
    total revenue growth (at constant share) reaches the terminal growth rate in year 10."""
    t = np.arange(1, YEARS + 1)
    mg, pg = d.market_growth.value, d.price_growth.value
    k = fade_factor(mg, pg, terminal_growth)
    fade = np.clip((t - 5) / 5, 0, 1)
    return mg + (k * mg - mg) * fade, pg + (k * pg - pg) * fade


def build(company: Company, setup: Setup, d: StoryDrivers) -> StoryResult:
    a0 = setup.assumptions
    t = np.arange(0, YEARS + 1)
    mg, pg = _rates(d, a0.terminal_growth)
    market = d.market_units.value * np.concatenate([[1], np.cumprod(1 + mg)])
    sy = max(int(round(d.share_year.value)), 1)
    s0, s1 = d.current_share.value, d.target_share.value
    share = np.where(t >= sy, s1, s0 + (s1 - s0) * t / sy)
    units = market * share
    price = d.price_per_unit.value * np.concatenate([[1], np.cumprod(1 + pg)])
    # Revenue scales from the reported figure, so revenue the unit count misses (spares, services) grows with it.
    # Revenue outside the story's market keeps the status-quo growth path (growth_y1, growth_y2_5, fade).
    seg = min(max(d.revenue_share.value, 0.0), 1.0)
    story_rev = a0.revenue * seg * (units / units[0]) * (price / price[0])
    rest = a0.revenue * (1 - seg) * np.concatenate([[1], np.cumprod(1 + _paths(a0.with_(growth_path=None))["growth"])])
    revenue = story_rev + rest
    growth = revenue[1:] / revenue[:-1] - 1
    path = pd.DataFrame({"Market units": market, "Market share": share, "Units sold": units,
                         "Revenue per unit": price, "Revenue from this market": story_rev,
                         "Other revenue": rest, "Revenue": revenue,
                         "Revenue growth": np.concatenate([[np.nan], growth])}, index=t)
    tag = {"stated": "Your story", "inferred": "AI inferred"}
    unused = ("Rest of the business (outside the story's market), status quo: " + a0.sources.get("growth", "")
              if seg < 1 else "Not used: growth follows the story's units x price path")
    a = a0.with_(growth_path=tuple(float(g) for g in growth),
                 target_margin=d.target_margin.value, margin_year=max(int(round(d.margin_year.value)), 1),
                 sales_to_capital_1_5=d.sales_to_capital.value, sales_to_capital_6_10=d.sales_to_capital.value,
                 sources=a0.sources | {
                     "growth_y1": unused, "growth_y2_5": unused,
                     "target_margin": f"{tag[d.target_margin.source]}: {d.target_margin.reason}",
                     "margin_year": tag[d.margin_year.source],
                     "sales_to_capital_1_5": f"{tag[d.sales_to_capital.source]}: {d.sales_to_capital.reason}",
                     "sales_to_capital_6_10": tag[d.sales_to_capital.source]})
    return StoryResult(d, path, a)


# ---------------------------------------------------------------- plausibility
OK, STRETCH, RED = "✅ OK", "⚠️ Stretch", "🚩 Red flag"


def _grade(x: float, ok: float, stretch: float) -> str:
    return OK if x <= ok else STRETCH if x <= stretch else RED


def scorecard(company: Company, setup: Setup, result: StoryResult, v: Valuation | None = None) -> pd.DataFrame:
    """Story vs reality: each driver against the company's five years and its Damodaran industry."""
    p, fin = company.profile, company.financials
    d, path, a = result.drivers, result.path, result.assumptions
    ratios = compute(fin)
    bench = damodaran.benchmarks(p["damodaran_industry"], p["region"])
    rev = fin.loc["revenue"].dropna()
    hist_g = (rev.iloc[-1] / rev.iloc[0]) ** (1 / (len(rev) - 1)) - 1 if len(rev) > 1 and rev.iloc[0] > 0 else math.nan
    best_margin = ratios.loc["operating_margin"].max()
    s2c_hist = ratios.loc["sales_to_capital"].median()
    ind_m, ind_s2c = bench["operating_margin"], bench["sales_to_capital"]
    rows = []

    def add(check, story, reality, verdict, why):
        rows.append({"Check": check, "Story": story, "Reality": reality, "Verdict": verdict, "Why": why})

    s0, s1 = d.current_share.value, d.target_share.value
    gain = s1 - s0
    # Holding a big share is fine; winning one is the hard part.
    monopoly = s1 > 0.5 and gain > 0.05
    verdict = RED if monopoly or gain > 0.25 else STRETCH if gain > 0.10 or (s1 > 0.4 and gain > 0.05) else OK
    add("Market share", f"{s1:.0%} by year {int(d.share_year.value)}", f"{s0:.0%} today", verdict,
        "Few markets let one firm win more than half; rivals cut prices and regulators step in." if monopoly
        else f"A {gain * 100:+.0f} point swing in share" + (" is rare without a disruption." if gain > 0.10 else "."))

    # Judged against the market's own growth in value (units and price): history can flatter (a COVID-low base).
    col = "Revenue from this market" if path["Revenue from this market"].iloc[0] > 0 else "Revenue"
    g5 = (path[col].iloc[5] / path[col].iloc[0]) ** 0.2 - 1
    # The market grows in units plus inflation; price rises beyond inflation are judged separately below.
    infl = setup.wacc.inflation_local
    market_value_g = (1 + d.market_growth.value) * (1 + infl) - 1
    add("Revenue growth" + (" from this market" if d.revenue_share.value < 1 else "") + ", years 1-5",
        f"{g5:.1%} a year",
        f"market {market_value_g:.1%} (units + {infl:.0%} inflation); company {hist_g:.1%} over the last "
        f"{len(rev) - 1} years", _grade(g5 - market_value_g, 0.03, 0.10),
        f"{(g5 - market_value_g) * 100:.0f} points a year faster than the market grows in money terms."
        if g5 > market_value_g + 0.03 else "Close to the market's own growth.")
    pg = d.price_growth.value
    add("Revenue per unit growth", f"{pg:.1%} a year", f"inflation {infl:.1%}", _grade(pg - infl, 0.03, 0.08),
        "Prices rising this much faster than inflation every year needs a big shift to pricier products."
        if pg > infl + 0.03 else "Roughly inflation plus a little mix.")

    ceiling = max(best_margin, ind_m)
    add("Target operating margin", f"{a.target_margin:.1%}", f"best year {best_margin:.1%}; industry {ind_m:.1%}",
        _grade(a.target_margin - ceiling, 0.01, 0.05),
        "Above anything the company or its industry earns." if a.target_margin > ceiling + 0.01
        else "Within what the company or its peers already earn.")

    eff = max(s2c_hist if pd.notna(s2c_hist) else 0, ind_s2c)
    ratio = a.sales_to_capital_1_5 / eff if eff > 0 else 1
    capital_heavy_mix = any(m.share_of_units - (m.today or 0) > 0.3 for m in d.mix)
    verdict = _grade(ratio, 1.15, 1.6)
    if capital_heavy_mix and a.sales_to_capital_1_5 >= min(s2c_hist, ind_s2c) and verdict == OK:
        verdict = STRETCH
    add("Sales-to-capital (capex intensity)", f"{a.sales_to_capital_1_5:.2f}x",
        f"company median {s2c_hist:.2f}x; industry {ind_s2c:.2f}x", verdict,
        "Growth funded more cheaply than the company or industry ever has." if ratio > 1.15 else
        f"The mix shift needs new plants and products, yet growth is funded more cheaply than the industry's "
        f"{ind_s2c:.2f}x." if verdict != OK else "Consistent with the company and its industry.")

    units_from_revenue = a.revenue * d.revenue_share.value / d.price_per_unit.value if d.price_per_unit.value else math.nan
    units_story = path["Units sold"].iloc[0]
    gap = abs(units_from_revenue / units_story - 1) if units_story else math.nan
    add("Units today (revenue ÷ price vs market × share)", f"{units_story:,.0f} {d.unit_name}",
        f"{units_from_revenue:,.0f} from revenue", _grade(gap, 0.25, 0.6) if pd.notna(gap) else STRETCH,
        "Revenue includes sales outside this market (exports, services) or the price per unit is off."
        if pd.notna(gap) and gap > 0.25 else "The market, share and price add up to reported revenue.")

    for m in d.mix:
        jump = m.share_of_units - (m.today or 0)
        add(f"Mix: {m.name}", f"{m.share_of_units:.0%} of {d.unit_name}",
            f"{m.today:.0%} today" if m.today is not None else "unknown today",
            RED if jump > 0.5 else STRETCH if jump > 0.2 else OK, m.effect)

    if v is not None and a.price:
        add("Value vs price", f"{max(v.value_per_share, 0):,.2f}", f"{a.price:,.2f}",
            "ℹ️ Result", f"The story says the stock is {'cheap' if v.value_per_share > a.price else 'expensive'} "
                f"({v.upside:+.0%}).")
    return pd.DataFrame(rows)


def story_score(card: pd.DataFrame) -> int:
    """0-100: every driver within limits scores full marks; stretches cost 10, red flags 25."""
    checks = card[card["Check"] != "Value vs price"]["Verdict"]
    return max(0, 100 - 10 * int((checks == STRETCH).sum()) - 25 * int((checks == RED).sum()))
