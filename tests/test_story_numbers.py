"""Phase 4, story → numbers: units x price revenue path, plausibility scorecard and the live Your story sheet."""
import json
import math
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.engine.dcf import value
from app.engine.defaults import Setup, status_quo
from app.excel.workbook import build
from app.story import story_numbers as sn
from tests.test_llm_json import ScriptedLLM
from tests.test_ratios_excel import synthetic
from tests.test_story import no_cache


def t(v, source="inferred"):
    return {"value": v, "source": source, "reason": "test"}


DRIVERS = {"headline": "Test Motors takes 70% and goes 80% EV", "market": "Indian cars", "unit_name": "cars",
           "market_units": t(4e6), "market_growth": t(0.06), "current_share": t(0.4), "target_share": t(0.7, "stated"),
           "share_year": t(10), "price_per_unit": t(400), "price_growth": t(0.05), "target_margin": t(0.10),
           "margin_year": t(5), "sales_to_capital": t(2.0),
           "mix": [{"name": "EVs", "share_of_units": 0.8, "today": 0.02, "source": "stated", "effect": "Batteries"}],
           "red_flags": ["EVs are 3% of the market."]}


@pytest.fixture
def story():
    c = synthetic()
    s = status_quo(c)
    return c, s, sn.build(c, s, sn.StoryDrivers.model_validate(DRIVERS))


def test_revenue_is_units_times_price(story):
    c, s, r = story
    path = r.path
    assert path["Market share"].iloc[10] == pytest.approx(0.7) and path["Market share"].iloc[5] == pytest.approx(0.55)
    expected = s.assumptions.revenue * path["Units sold"] / path["Units sold"].iloc[0] \
        * path["Revenue per unit"] / path["Revenue per unit"].iloc[0]
    assert (path["Revenue"] - expected).abs().max() < 1e-3
    v = value(r.assumptions)  # the engine's revenue follows the story's path exactly
    assert v.table.loc["Revenue", 10] == pytest.approx(path["Revenue"].iloc[10])
    # once share stops moving, revenue growth ends at the terminal growth rate
    held = sn.build(c, s, sn.StoryDrivers.model_validate(DRIVERS | {"share_year": t(5)}))
    assert held.path["Revenue growth"].iloc[10] == pytest.approx(s.assumptions.terminal_growth)


def test_story_about_one_business_line_leaves_the_rest_at_status_quo(story):
    c, s, _ = story
    r = sn.build(c, s, sn.StoryDrivers.model_validate(DRIVERS | {"revenue_share": t(0.25)}))
    path, a0 = r.path, s.assumptions
    assert path["Revenue from this market"].iloc[0] == pytest.approx(0.25 * a0.revenue)
    assert path["Other revenue"].iloc[1] == pytest.approx(0.75 * a0.revenue * (1 + a0.growth_y1))
    assert (path["Revenue"] - path["Revenue from this market"] - path["Other revenue"]).abs().max() < 1e-3
    assert r.assumptions.growth_y1 == a0.growth_y1  # the DCF's growth inputs now drive the other revenue


def test_fade_factor_shrinks_both_rates_in_proportion():
    k = sn.fade_factor(0.06, 0.05, 0.04)
    assert (1 + k * 0.06) * (1 + k * 0.05) == pytest.approx(1.04)
    assert sn.fade_factor(0.0, 0.08, 0.04) == pytest.approx(0.5)


def test_scorecard_flags_monopoly_share_and_mix(story):
    c, s, r = story
    card = sn.scorecard(c, s, r, value(r.assumptions)).set_index("Check")
    assert card.loc["Market share", "Verdict"] == sn.RED
    assert card.loc["Mix: EVs", "Verdict"] == sn.RED
    assert card.loc["Target operating margin", "Verdict"] == sn.OK  # 10% vs the synthetic firm's 13% best year
    assert sn.story_score(card.reset_index()) <= 50
    modest = sn.build(c, s, sn.StoryDrivers.model_validate(DRIVERS | {"target_share": t(0.42), "mix": []}))
    card2 = sn.scorecard(c, s, modest).set_index("Check")
    assert card2.loc["Market share", "Verdict"] == sn.OK


def test_draft_tags_stated_numbers(monkeypatch):
    no_cache(monkeypatch)
    c = synthetic()
    llm = ScriptedLLM([json.dumps(DRIVERS)])
    d = sn.draft(c, status_quo(c), "Test Motors takes 70% of the market", llm)
    assert d.target_share.source == "stated" and d.market_units.source == "inferred"
    assert "Test Motors takes 70%" in llm.prompts[0]


def test_excel_story_sheet_drives_the_dcf(story):
    c, s, r = story
    v = value(r.assumptions)
    card = sn.scorecard(c, s, r, v)
    data = build(c, Setup(r.assumptions, s.wacc, s.warnings), v, your_story=r, card=card,
                 score=sn.story_score(card))
    wb = load_workbook(BytesIO(data))
    assert wb.sheetnames[:3] == ["Summary", "Your story", "DCF"]
    dcf = wb["DCF"]
    growth_row = next(row for row in dcf.iter_rows() if row[0].value == "Revenue growth")
    assert growth_row[2].value.startswith("='Your story'!C")  # year 1 links to the story sheet
    ws = wb["Your story"]
    labels = [ws.cell(i, 1).value for i in range(1, 40)]
    assert "Units sold (cars)" in labels and any(str(x).startswith("Story score") for x in labels if x)
    assert not math.isnan(v.value_per_share)
