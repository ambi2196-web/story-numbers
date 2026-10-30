"""Phase 3 story layer with a scripted LLM: profile industry choice, market story fallback, fictional companies."""
import json
from io import BytesIO

from openpyxl import load_workbook

from app.data import cache
from app.engine.dcf import solve, value
from app.engine.defaults import status_quo
from app.excel.workbook import build
from app.story import fictional, profile as prof
from app.story.market_story import market_story
from tests.test_llm_json import ScriptedLLM
from tests.test_ratios_excel import synthetic

PROFILE = {"one_liner": "Makes cars.", "segments": [{"name": "Cars", "share_of_revenue": 1.0, "description": "Cars"}],
           "unit_drivers": [{"name": "Cars sold", "unit": "units", "latest_value": 1000, "note": "x"}],
           "addressable_market": "Indian cars", "competitive_position": "Leader", "key_risks": ["EVs", "Rates", "Steel"],
           "damodaran_industry": "Auto Parts", "industry_reason": "It mostly sells parts."}


def no_cache(monkeypatch):
    monkeypatch.setattr(cache, "get", lambda *a, **k: None)
    monkeypatch.setattr(cache, "put", lambda *a, **k: None)


def test_profile_moves_industry_and_rejects_made_up_groups(monkeypatch):
    no_cache(monkeypatch)
    c = synthetic()
    p = prof.build_profile(c, ScriptedLLM([json.dumps(PROFILE)]))
    assert prof.apply_industry(c, p) and c.profile["damodaran_industry"] == "Auto Parts"
    assert c.profile["rule_based_industry"] == "Auto & Truck"
    c2 = synthetic()
    p2 = prof.build_profile(c2, ScriptedLLM([json.dumps(PROFILE | {"damodaran_industry": "Flying Cars"})]))
    assert p2.damodaran_industry == "Auto & Truck"  # falls back to the rule-based mapping


def test_market_story_falls_back_to_template_without_ai():
    c = synthetic()
    s = status_quo(c)
    v = value(s.assumptions)
    implied = {"growth": solve(s.assumptions, "growth"), "target_margin": solve(s.assumptions, "target_margin")}
    story = market_story(c.profile["name"], "TEST.NS", s, v, implied, {"operating_margin": 0.1, "sales_to_capital": 1},
                         None, None)
    assert "market expects" in story.story


def test_fictional_company_values_and_exports():
    spec = fictional.FictionalSpec(name="QuickKirana", description="Dark stores in Pune.", country="India",
                                   currency="INR", damodaran_industry="Retail (Grocery and Food)",
                                   revenue_millions=500, operating_margin=-0.3, invested_capital_millions=750,
                                   cash_millions=280, debt_millions=60, shares_millions=100,
                                   growth_next_5_years=0.45, target_margin=0.05, years_to_target_margin=7,
                                   failure_probability=0.3)
    company, setup = fictional.setup_for(spec)
    a = setup.assumptions
    assert 0.10 < a.cost_of_capital < 0.20  # not the after-tax cost of debt
    assert a.failure_probability == 0.3 and a.margin_year == 7
    v = value(a)
    p = prof.BusinessProfile.model_validate(PROFILE)
    wb = load_workbook(BytesIO(build(company, setup, v, None, p, None)))
    assert wb.sheetnames[:3] == ["Summary", "Story", "DCF"]
