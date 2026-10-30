"""The AI business profile: what the company sells, its revenue mix, the unit drivers a story will move
(cars sold, average price per car) and which Damodaran industry group it really belongs to.

The LLM only describes; numbers it offers are labelled as AI estimates. The data passed in (Yahoo's
description, five years of financials) anchors it. Results are cached for a week per company.
"""
from pydantic import BaseModel, Field

from app.data import cache, damodaran
from app.data.collector import Company
from app.data.ratios import compute
from app.excel.workbook import units
from app.llm import LLMProvider

SYSTEM = ("You are an equity analyst trained in Aswath Damodaran's narrative-and-numbers approach. Be concrete, "
          "use the company's own reported figures when you know them, and never invent precision: when you are "
          "not confident of a number, return null.")


class Segment(BaseModel):
    name: str
    share_of_revenue: float | None = Field(None, description="fraction of revenue, 0-1; null if unknown")
    description: str


class UnitDriver(BaseModel):
    name: str = Field(description="e.g. 'Cars sold', 'Average selling price per car', 'Orders per day'")
    unit: str = Field(description="e.g. 'units per year', 'INR per car'")
    latest_value: float | None = Field(None, description="latest fiscal year value; null if not confident")
    note: str = Field(description="where it comes from or why it matters")


class BusinessProfile(BaseModel):
    one_liner: str = Field(description="what the company does, in one sentence a 15-year-old understands")
    segments: list[Segment] = Field(description="2-6 lines of business, largest first")
    unit_drivers: list[UnitDriver] = Field(description="2-5 operating drivers that revenue = volume x price rests on")
    addressable_market: str = Field(description="the market it competes in and a rough size, with currency")
    competitive_position: str = Field(description="market share, moat, main competitors; 2-3 sentences")
    key_risks: list[str] = Field(description="3 risks that would change the valuation")
    damodaran_industry: str = Field(description="exactly one name from the provided Damodaran industry list")
    industry_reason: str


def _facts(company: Company) -> str:
    p, fin = company.profile, company.financials
    scale, unit = units(p.get("currency"))
    r = compute(fin)
    lines = [f"{y}: revenue {fin.loc['revenue', y] / scale:,.0f}, operating margin "
             f"{r.loc['operating_margin', y]:.1%}" for y in fin.columns]
    return (f"Company: {p['name']} ({p['symbol']}), {p.get('country')}. Yahoo industry: {p.get('industry')}.\n"
            f"Description: {p.get('summary') or 'n/a'}\nFinancials ({unit}):\n" + "\n".join(lines))


def _industry_menu(region: str) -> str:
    df = damodaran.load_industry("margin", region)
    firms = damodaran._col(df, "Number of firms")
    margin = damodaran._col(df, "Pre-tax Lease adjusted", "Pre-tax Unadjusted Operating")
    return "; ".join(f"{r['Industry Name']} ({r[firms]:.0f}, {r[margin]:.0%})" for _, r in df.iterrows()
                     if not str(r["Industry Name"]).startswith("Total Market"))


def cached_profile(symbol: str, provider: str) -> BusinessProfile | None:
    hit = cache.get(f"profile:{symbol}:{provider}", max_age_hours=24 * 7)
    return BusinessProfile.model_validate(hit) if hit else None


def build_profile(company: Company, llm: LLMProvider, refresh: bool = False) -> BusinessProfile:
    key = f"profile:{company.profile['symbol']}:{llm.name}"
    if not refresh and (hit := cache.get(key, max_age_hours=24 * 7)):
        return BusinessProfile.model_validate(hit)
    region = company.profile.get("region") or "Global"
    choices = damodaran.industries(region)
    prompt = (f"{_facts(company)}\n\nWrite this company's business profile. The financials are consolidated: the "
              "segments must account for all of that revenue, subsidiaries included (check the scale: a segment "
              "list that cannot add up to the revenue shown is missing something). Pick its Damodaran industry group: "
              "the peer group whose firms make money the way this company does (judge by where most of its "
              "operating profit comes from, not by its label). Groups with few firms are noisy benchmarks; pick "
              "one only when it clearly fits. Groups (firms, operating margin):\n" + _industry_menu(region))
    profile = llm.complete_json(prompt, BusinessProfile, system=SYSTEM, retries=2)  # long JSON: allow a second fix
    if profile.damodaran_industry not in choices:  # keep the rule-based mapping rather than a made-up group
        match = [c for c in choices if c.lower() == profile.damodaran_industry.lower()]
        profile.damodaran_industry = match[0] if match else company.profile["damodaran_industry"]
    cache.put(key, profile.model_dump())
    return profile


def apply_industry(company: Company, profile: BusinessProfile) -> bool:
    """Use the AI's industry group for benchmarks and beta. Returns True if it changed the mapping."""
    p = company.profile
    if profile.damodaran_industry == p["damodaran_industry"]:
        return False
    p.setdefault("rule_based_industry", p["damodaran_industry"])
    p["damodaran_industry"] = profile.damodaran_industry
    p["industry_source"] = f"AI: {profile.industry_reason}"
    return True
