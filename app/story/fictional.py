"""Fictional companies: describe a business in words ("a quick-commerce startup in Pune doing ₹50 crore, losing
money") and the AI drafts its numbers; the same engine and industry benchmarks then value it.
"""
import math

import pandas as pd
from pydantic import BaseModel, Field

from app.data import damodaran
from app.data.collector import FIELDS, Company
from app.data.industry_map import to_region
from app.engine.defaults import Setup, status_quo
from app.llm import LLMProvider
from app.story.profile import SYSTEM


class FictionalSpec(BaseModel):
    name: str
    description: str = Field(description="what it sells and to whom, 2-3 sentences")
    country: str = Field(description="country of operations, e.g. 'India', 'United States'")
    currency: str = Field(description="ISO code, e.g. INR, USD")
    damodaran_industry: str = Field(description="exactly one name from the provided Damodaran industry list")
    revenue_millions: float = Field(description="latest annual revenue, millions of currency")
    operating_margin: float = Field(description="latest operating margin, e.g. -0.15 for a 15% loss")
    invested_capital_millions: float = Field(description="capital tied up in the business (equity + debt - cash)")
    cash_millions: float = 0.0
    debt_millions: float = 0.0
    shares_millions: float = Field(100.0, description="shares outstanding, millions")
    growth_next_5_years: float = Field(description="expected annual revenue growth, years 1-5")
    target_margin: float = Field(description="operating margin once mature")
    years_to_target_margin: int = Field(5, ge=1, le=10)
    failure_probability: float = Field(0.0, ge=0, le=1, description="chance it fails before maturing")


def draft(text: str, llm: LLMProvider) -> FictionalSpec:
    """Turn a description into a full spec. Missing numbers are filled with industry-typical values."""
    choices = damodaran.industries("Global")
    prompt = (f"Draft the starting numbers for this fictional company:\n\"{text}\"\n\nUse what the description "
              "states; fill the rest with numbers typical for a company of that kind, size and stage. Young "
              "loss-making firms should carry a failure probability (10-40%). Pick the industry from this list:\n"
              + "; ".join(choices))
    spec = llm.complete_json(prompt, FictionalSpec, system=SYSTEM)
    if spec.damodaran_industry not in choices:
        close = [c for c in choices if c.lower() == spec.damodaran_industry.lower()]
        spec.damodaran_industry = close[0] if close else "Total Market"
    return spec


def to_company(spec: FictionalSpec) -> Company:
    m = 1e6
    revenue, ebit = spec.revenue_millions * m, spec.revenue_millions * spec.operating_margin * m
    cash, debt = spec.cash_millions * m, spec.debt_millions * m
    values = {key: math.nan for key, *_ in FIELDS} | {
        "revenue": revenue, "operating_income": ebit, "pretax_income": ebit, "tax": max(ebit, 0) * 0.25,
        "net_income": ebit - max(ebit, 0) * 0.25, "cash": cash, "total_debt": debt,
        "equity": spec.invested_capital_millions * m + cash - debt, "diluted_shares": spec.shares_millions * m}
    fin = pd.DataFrame({"FY0": values}).astype(float)
    region = to_region(spec.country)
    if spec.damodaran_industry not in damodaran.industries(region):
        region = "Global"
    profile = {"symbol": "FICTIONAL", "name": spec.name, "exchange": "Fictional", "currency": spec.currency,
               "price_currency": spec.currency, "country": spec.country, "region": region, "sector": None,
               "industry": spec.damodaran_industry, "damodaran_industry": spec.damodaran_industry,
               "summary": spec.description, "price": None, "shares_outstanding": spec.shares_millions * m,
               "market_cap": None, "beta": None, "years": ["FY0"], "source": "Fictional (your inputs)",
               "field_sources": {}}
    return Company(profile, fin)


def setup_for(spec: FictionalSpec) -> tuple[Company, Setup]:
    """The fictional company plus its valuation set-up, with the spec's story replacing the history-based defaults."""
    company = to_company(spec)
    setup = status_quo(company)
    a = setup.assumptions.with_(growth_y1=spec.growth_next_5_years, growth_y2_5=spec.growth_next_5_years,
                                target_margin=spec.target_margin, margin_year=spec.years_to_target_margin,
                                failure_probability=spec.failure_probability)
    # A young firm's past capital includes money burnt on losses, so growth is funded at the industry's rate.
    s2c = damodaran.benchmarks(spec.damodaran_industry, company.profile["region"])["sales_to_capital"]
    a = a.with_(sales_to_capital_1_5=s2c, sales_to_capital_6_10=s2c,
                sources=a.sources | {"growth": "Your story", "target_margin": "Your story",
                                     "failure_probability": "Your story",
                                     "sales_to_capital": f"Damodaran {company.profile['region']} "
                                                         f"{spec.damodaran_industry} average"})
    setup.assumptions = a
    setup.warnings = [w for w in setup.warnings if "sales-to-capital" not in w]
    return company, setup
