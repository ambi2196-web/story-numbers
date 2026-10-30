"""Phase 5, numbers → story: target to value today, one-driver requirements, AI routes calibrated and graded."""
import json
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.engine.dcf import value
from app.engine.defaults import status_quo
from app.excel.workbook import build
from app.story import target as tg
from tests.test_llm_json import ScriptedLLM
from tests.test_ratios_excel import synthetic
from tests.test_story import no_cache

ROUTE = {"name": "Export push", "pitch": "Sell abroad.", "market_growth": 0.06, "target_share": 0.45, "share_year": 5,
         "price_growth": 0.04, "target_margin": 0.12, "margin_year": 5, "sales_to_capital": 2.0, "mix": [],
         "lever": "target_share", "risks": ["Tariffs"]}
ROUTES = {"market": "Cars", "unit_name": "cars", "market_units": 1000.0, "current_share": 0.4,
          "price_per_unit": 3.75e6, "revenue_share": 1.0, "base_reason": "test",
          "routes": [ROUTE, ROUTE | {"name": "Fat margins", "lever": "target_margin", "target_share": 0.4}]}


@pytest.fixture
def setup():
    c = synthetic()
    return c, status_quo(c)


def test_target_needs_value_today_that_grows_at_cost_of_equity(setup):
    _, s = setup
    t = tg.Target("multiple", 2.0, 3)
    assert t.price(s.assumptions) == 200.0
    assert t.annual_return(s.assumptions) == pytest.approx(2 ** (1 / 3) - 1)
    assert t.value_today(s) * (1 + s.wacc.cost_of_equity) ** 3 == pytest.approx(200.0)
    assert tg.Target("market_cap", 3e9, 2).price(s.assumptions) == pytest.approx(3e9 / s.assumptions.shares)


def test_requirements_each_reach_the_needed_value(setup):
    _, s = setup
    need = value(s.assumptions).value_per_share * 1.1
    reqs = tg.requirements(s, need).set_index("key")
    # this firm earns less than its cost of capital on growth, so a higher value needs slower growth
    assert reqs.loc["growth", "Required"] < reqs.loc["growth", "Status quo"]
    assert "Slower growth adds value" in reqs.loc["growth", "Note"]
    g = reqs.loc["growth", "Required"]
    assert value(s.assumptions.with_(growth_y1=g, growth_y2_5=g)).value_per_share == pytest.approx(need, rel=1e-4)
    m = reqs.loc["target_margin", "Required"]
    assert value(s.assumptions.with_(target_margin=m)).value_per_share == pytest.approx(need, rel=1e-4)
    assert reqs.loc["growth", "Revenue year 5 vs today"] > 1
    assert reqs.loc["growth", "Required"] == reqs.loc["growth", "Required"]  # reachable, not NaN


def test_routes_are_calibrated_to_the_target_and_graded(setup):
    c, s = setup
    need = value(s.assumptions).value_per_share * 1.3
    routes = tg.Routes.model_validate(ROUTES)
    results = tg.evaluate(c, s, routes, need)
    assert len(results) == 2
    for rr in results:
        if rr.lever_value is not None:
            assert rr.valuation.value_per_share == pytest.approx(need, rel=1e-3)
            assert rr.verdict in ("probable", "plausible", "possible")
    import pandas as pd
    from app.story import story_numbers as sn
    card = lambda *v: pd.DataFrame({"Verdict": list(v)})
    assert tg.verdict(card(sn.OK, sn.STRETCH), True) == "probable"
    assert tg.verdict(card(sn.STRETCH, sn.STRETCH), True) == "plausible"
    assert tg.verdict(card(sn.OK, sn.RED), True) == "possible"
    assert tg.verdict(card(sn.OK), False) == "out of reach"
    pushed = tg.lever_check("target_margin", 0.10, 0.30)
    assert pushed["Verdict"] == sn.RED and "+20.0 points" in pushed["Why"]


def test_out_of_reach_route_is_reported(setup):
    c, s = setup
    routes = tg.Routes.model_validate(ROUTES | {"routes": [ROUTE | {"lever": "price_growth"}]})
    rr = tg.evaluate(c, s, routes, value(s.assumptions).value_per_share * 1000)[0]
    assert rr.lever_value is None and rr.verdict == "out of reach"


def test_draft_routes_and_excel_sheet(setup, monkeypatch):
    no_cache(monkeypatch)
    c, s = setup
    t = tg.Target("multiple", 2.0, 3)
    need = t.value_today(s)
    reqs = tg.requirements(s, need)
    llm = ScriptedLLM([json.dumps(ROUTES)])
    routes = tg.draft_routes(c, s, t, need, reqs, llm)
    assert "2x in 3 years" in llm.prompts[0]
    results = tg.evaluate(c, s, routes, need)
    wb = load_workbook(BytesIO(build(c, target_pack=(t, s, reqs, results))))
    assert wb.sheetnames[1] == "Target"
    ws = wb["Target"]
    assert ws["B10"].value == "=B6/(1+B8)^B7"
    assert any(ws.cell(r, 1).value == "Export push" for r in range(1, 40))
