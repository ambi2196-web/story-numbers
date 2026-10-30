"""Phase 7 hardening: odd fiscal years, source gaps, retries, featured profiles and the prompt-eval checks."""
import math

import pandas as pd
import pytest

from app import evals, featured
from app.data import collector, net
from app.engine.defaults import status_quo
from app.story import profile as prof
from app.story import story_numbers as sn
from tests.test_ratios_excel import synthetic
from tests.test_story_numbers import DRIVERS


def frame(years, revenue):
    keys = [k for k, *_ in collector.FIELDS]
    df = pd.DataFrame(math.nan, index=keys, columns=years)
    df.loc["revenue"] = revenue
    return df


def test_period_note_flags_a_changed_year_end():
    df = frame(["FY2021", "FY2022", "FY2023", "FY2025", "FY2026"], [1, 2, 3, 4, 5])
    assert "No figures for FY2024" in collector.period_note(df)
    assert collector.period_note(frame(["FY2024", "FY2025"], [1, 2])) is None


def test_growth_uses_the_real_years_between_figures():
    c = synthetic()
    c.financials.columns = ["FY2022", "FY2023", "FY2026"]  # revenue 100 -> 120 -> 150 with a 3-year gap
    s = status_quo(c)
    assert s.assumptions.growth_y2_5 == pytest.approx(1.5 ** (1 / 4) - 1)  # 4 years, not 2
    assert "4-year" in s.assumptions.sources["growth"]


def test_merge_fills_years_the_primary_source_lacks_only_when_sources_agree():
    yahoo = frame(["FY2021", "FY2022", "FY2025"], [100.0, 110.0, 150.0])
    agree = frame(["FY2025"], [151.0])
    df, sources = collector._merge(yahoo, agree)
    assert df.loc["revenue"].tolist() == [100.0, 110.0, 151.0]
    assert sources["_years_from_yahoo"] == "FY2021, FY2022"
    disagree = frame(["FY2025"], [1500.0])  # e.g. a different currency or scope
    df, sources = collector._merge(yahoo, disagree)
    assert math.isnan(df.loc["revenue", "FY2021"]) and "_years_from_yahoo" not in sources


def test_retry_backs_off_then_gives_a_friendly_error():
    calls, waits = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("rate limited")
        return "ok"
    assert net.retry(flaky, "Yahoo", sleep=waits.append) == "ok" and waits == [1.0, 3.0]
    with pytest.raises(net.SourceUnavailable, match="try again in a minute"):
        net.retry(lambda: 1 / 0, "Yahoo", waits=(0.1,), sleep=lambda _: None)


def test_featured_profiles_load_without_ai(monkeypatch):
    monkeypatch.setattr(prof.cache, "get", lambda *a, **k: None)
    for symbol in featured.FEATURED:
        p = prof.cached_profile(symbol, "gemini")
        assert p is not None and p.segments, symbol


def test_eval_checks():
    d = sn.StoryDrivers.model_validate(DRIVERS)
    ok = {"expect": {"target_share": [0.68, 0.72]}, "stated": ["target_share"], "mix_share": [0.75, 0.85],
          "min_red_flags": 1}
    assert evals.check(ok, d) == []
    bad = {"expect": {"market_units": [1, 2]}, "stated": ["market_growth"], "share_flat": True}
    fails = evals.check(bad, d)
    assert len(fails) == 3 and "market_growth not tagged stated" in fails
