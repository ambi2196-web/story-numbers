"""'The market's story today': the reverse DCF turned into plain language, with Damodaran's 3P test.

The numbers are computed by the engine and handed to the LLM; it only narrates them. If the LLM is
unavailable, a plain template says the same thing.
"""
import hashlib
from typing import Literal

from pydantic import BaseModel, Field

from app.data import cache
from app.engine.dcf import Valuation
from app.engine.defaults import Setup
from app.llm import LLMError, LLMProvider
from app.story.profile import SYSTEM, BusinessProfile

DRIVER_NAMES = {"growth": "revenue growth of {x:.1%} a year for five years",
                "target_margin": "an operating margin of {x:.1%}",
                "sales_to_capital": "sales-to-capital of {x:.2f}x",
                "terminal_roic": "a return on capital of {x:.1%} forever after year 10"}


class MarketStory(BaseModel):
    headline: str = Field(description="one line, e.g. 'The market is betting on SUVs and fatter margins'")
    story: str = Field(description="3-5 sentences: what has to be true for today's price, in operating terms "
                                   "(units, prices, share, margins), not finance jargon")
    verdict: Literal["possible", "plausible", "probable"] = Field(
        description="Damodaran's 3P test for the price-implied story")
    reasoning: str = Field(description="2 sentences justifying the verdict against history and the industry")


def _brief(setup: Setup, v: Valuation, implied: dict, bench: dict) -> str:
    a = setup.assumptions
    lines = [f"Status-quo value per share {v.value_per_share:,.2f} vs price {a.price:,.2f} "
             f"({v.upside:+.0%}).",
             f"Status-quo assumptions: growth {a.growth_y2_5:.1%}, target margin {a.target_margin:.1%}, "
             f"sales-to-capital {a.sales_to_capital_1_5:.2f}, cost of capital {a.cost_of_capital:.2%}.",
             f"Industry averages: operating margin {bench['operating_margin']:.1%}, sales-to-capital "
             f"{bench['sales_to_capital']:.2f}."]
    for d, x in implied.items():
        lines.append(f"Price-implied, alone: {DRIVER_NAMES[d].format(x=x)}" if x is not None
                     else f"Price-implied {d}: not reachable by this driver alone")
    return "\n".join(lines)


def template_story(setup: Setup, v: Valuation, implied: dict) -> MarketStory:
    a = setup.assumptions
    reachable = [DRIVER_NAMES[d].format(x=x) for d, x in implied.items() if x is not None]
    direction = "more" if (v.upside or 0) < 0 else "less"
    story = (f"At {a.price:,.2f} a share the market expects {direction} than the company's recent track record "
             f"delivers (status-quo value {v.value_per_share:,.2f}). Holding everything else fixed, the price needs "
             + (" or ".join(reachable) if reachable else "a combination of changes no single driver reaches") + ".")
    return MarketStory(headline="What today's price is betting on", story=story, verdict="possible",
                       reasoning="Template text (the AI was unavailable); judge the drivers against the industry.")


def market_story(company_name: str, symbol: str, setup: Setup, v: Valuation, implied: dict, bench: dict,
                 profile: BusinessProfile | None, llm: LLMProvider | None) -> MarketStory:
    if llm is None:
        return template_story(setup, v, implied)
    brief = _brief(setup, v, implied, bench)
    key = f"market_story:v2:{symbol}:{llm.name}:{hashlib.sha1(brief.encode()).hexdigest()[:12]}"
    if hit := cache.get(key):
        return MarketStory.model_validate(hit)
    business = (f"Business: {profile.one_liner} Drivers: "
                + "; ".join(f"{d.name} {d.latest_value if d.latest_value is not None else 'n/a'} {d.unit}"
                            for d in profile.unit_drivers)) if profile else ""
    prompt = (f"{company_name}. {business}\n{brief}\n\nTell the story today's share price implies. Translate the "
              "implied numbers into operating terms (for a carmaker: cars sold, price per car, segment share). "
              "The price-implied numbers are ALTERNATIVES: each one alone, with everything else at status quo, "
              "justifies today's price, so never add them together. Say which alternative is the most believable "
              "route. Use only the numbers and history given (five years); do not recompute the valuation.")
    try:
        story = llm.complete_json(prompt, MarketStory, system=SYSTEM)
    except LLMError:
        return template_story(setup, v, implied)
    cache.put(key, story.model_dump())
    return story
