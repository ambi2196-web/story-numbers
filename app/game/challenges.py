"""Challenges: a company, a value to reach and how believable the story must be (Damodaran's 3P test)."""
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from app.story import story_numbers as sn

RANK = {"out of reach": 0, "possible": 1, "plausible": 2, "probable": 3}


@dataclass(frozen=True)
class Challenge:
    id: str
    title: str
    query: str | None  # what to type in the search box; None = a fictional company
    brief: str
    goal: Literal["at_least", "at_most"]
    goal_value: float | None  # per share; None = today's price
    needs: Literal["possible", "plausible", "probable"]
    hint: str
    symbol: str | None = None  # the listed company the challenge is about

    def target(self, price: float | None) -> float | None:
        return self.goal_value if self.goal_value is not None else price

    def check(self, value_per_share: float, verdict: str, price: float | None) -> tuple[bool, str]:
        target = self.target(price)
        hit = value_per_share >= target if self.goal == "at_least" else value_per_share <= target
        believable = RANK[verdict] >= RANK[self.needs]
        if hit and believable:
            return True, f"Challenge met: worth {value_per_share:,.2f} with a {verdict} story."
        miss = []
        if not hit:
            miss.append(f"value {value_per_share:,.2f} is {'below' if self.goal == 'at_least' else 'above'} "
                        f"the goal of {target:,.2f}")
        if not believable:
            miss.append(f"the story is only {verdict}; this challenge needs {self.needs}"
                        + (" (no red flags)" if self.needs == "plausible" else
                           " (no red flags, at most one stretch)" if self.needs == "probable" else ""))
        return False, "Not yet: " + " and ".join(miss) + "."


CHALLENGES = [
    Challenge("paytm-2000", "Make Paytm worth ₹2,000", "Paytm", "One 97 Communications (Paytm) trades near "
              "₹1,600 but its track record is worth far less. Find a story worth ₹2,000 a share without a red flag.",
              "at_least", 2000.0, "plausible", "Payments are a scale game: think merchants, lending take-rates "
              "and how much capital growth needs.", symbol="PAYTM.NS"),
    Challenge("maruti-15000", "Maruti at ₹15,000", "Maruti Suzuki", "Tell a story that makes Maruti worth ₹15,000 "
              "a share, with no red flags.", "at_least", 15000.0, "plausible",
              "70% market share will not survive the scorecard. Mix (SUVs, exports) and margins might.", symbol="MARUTI.NS"),
    Challenge("tmpv-price", "Justify Tata Motors PV's price", "Tata Motors Passenger", "Find the most believable "
              "story that justifies today's share price: at most one stretch, no red flags.", "at_least", None,
              "probable", "JLR is most of the revenue: its margins matter more than Indian EV share.", symbol="TMPV.NS"),
    Challenge("eternal-400", "Eternal at ₹400", "Eternal", "Zomato's owner is mostly a quick-commerce bet now. "
              "Make it worth ₹400 a share with no red flags.", "at_least", 400.0, "plausible",
              "Quick commerce is only part of revenue; set its share of revenue honestly.", symbol="ETERNAL.NS"),
    Challenge("apple-price", "Earn Apple's price", "Apple", "Apple's status quo is worth well below its price. "
              "Find a story worth today's price with no red flags.", "at_least", None, "plausible",
              "Services margins and a light capital need do the heavy lifting.", symbol="AAPL"),
    Challenge("qcommerce-1000", "A ₹1,000 crore quick-commerce startup", None, "Build a fictional quick-commerce "
              "startup worth at least ₹1,000 crore with numbers a venture capitalist would accept: margins no "
              "higher than the industry's, growth below 60% a year and at least a 10% chance of failure.",
              "at_least", None, "plausible", "Margins are capped at the industry's, so the value has to come from "
              "scale and growth. Inputs are in millions: ₹1,000 crore = ₹10,000 million."),
]
BY_ID = {c.id: c for c in CHALLENGES}
FICTIONAL_TARGET = 1e10  # ₹1,000 crore of equity, in rupees


def fictional_card(spec, industry_margin: float) -> pd.DataFrame:
    """Story vs reality for a fictional company, judged on the same OK / stretch / red-flag scale."""
    rows = []

    def add(check, story, reality, verdict, why):
        rows.append({"Check": check, "Story": story, "Reality": reality, "Verdict": verdict, "Why": why})

    gap = spec.target_margin - industry_margin
    add("Target operating margin", f"{spec.target_margin:.1%}", f"industry {industry_margin:.1%}",
        sn.OK if gap <= 0.005 else sn.STRETCH if gap <= 0.05 else sn.RED,
        "Start-ups rarely end up more profitable than the industry they join.")
    g = spec.growth_next_5_years
    add("Revenue growth, years 1-5", f"{g:.0%} a year", "limit 60%", sn.OK if g <= 0.4 else sn.STRETCH if g <= 0.6
        else sn.RED, "Five years above 40% a year is rare even for winners.")
    f = spec.failure_probability
    add("Probability of failure", f"{f:.0%}", "at least 10%", sn.OK if f >= 0.1 else sn.STRETCH if f >= 0.05
        else sn.RED, "Most young companies do not survive to maturity.")
    return pd.DataFrame(rows)
