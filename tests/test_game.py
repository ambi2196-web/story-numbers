"""Phase 6 game layer: points, challenge checks, the fictional scorecard, scenarios and the leaderboard."""
import pytest

from app.game import challenges as ch, scoring, store
from app.story import story_numbers as sn
from app.story.fictional import FictionalSpec


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "game.sqlite")


def test_points_reward_bold_and_plausible():
    assert scoring.boldness(300, 100) == pytest.approx(1.0)
    assert scoring.boldness(100 / 3, 100) == pytest.approx(1.0)  # bold on the downside too
    assert scoring.boldness(100, 100) == 0
    assert scoring.points(300, 100, 100) == 1000
    assert scoring.points(300, 100, 50) == 250  # red flags hurt: plausibility is squared
    assert scoring.points(110, 100, 100) < 100  # timid
    assert scoring.challenge_points(30) == 100 and scoring.challenge_points(90) == 810


def test_challenge_needs_value_and_believability():
    maruti = ch.BY_ID["maruti-15000"]
    assert maruti.check(16000, "plausible", 11000)[0]
    ok, msg = maruti.check(16000, "possible", 11000)
    assert not ok and "no red flags" in msg
    ok, msg = maruti.check(9000, "probable", 11000)
    assert not ok and "below the goal of 15,000.00" in msg
    tmpv = ch.BY_ID["tmpv-price"]  # goal = today's price
    assert tmpv.check(270, "probable", 265)[0] and not tmpv.check(270, "plausible", 265)[0]


def test_fictional_card_grades_the_startup():
    spec = FictionalSpec(name="Q", description="d", country="India", currency="INR",
                         damodaran_industry="Retail (Grocery and Food)", revenue_millions=500, operating_margin=-0.2,
                         invested_capital_millions=500, growth_next_5_years=0.7, target_margin=0.08,
                         failure_probability=0.0)
    card = ch.fictional_card(spec, industry_margin=0.04).set_index("Check")
    assert card.loc["Target operating margin", "Verdict"] == sn.STRETCH
    assert card.loc["Revenue growth, years 1-5", "Verdict"] == sn.RED
    assert card.loc["Probability of failure", "Verdict"] == sn.RED


def test_scenarios_round_trip(db):
    sid = store.save_scenario(player="Ann", symbol="X.NS", company="X", name="Bull", tag="Bull", kind="Your story",
                              value_per_share=150.0, price=100.0, score=80, drivers={"headline": "h"})
    store.save_scenario(player="Ann", symbol="X.NS", company="X", name="Base", tag="Base", kind="Status quo",
                        value_per_share=90.0, price=100.0)
    store.save_scenario(player="Bob", symbol="X.NS", company="X", name="Other", tag="Bear", value_per_share=1.0)
    mine = store.scenarios("X.NS", "Ann")
    assert [s["name"] for s in mine] == ["Bull", "Base"] and mine[0]["drivers"] == {"headline": "h"}
    store.delete_scenario(sid)
    assert [s["name"] for s in store.scenarios("X.NS", "Ann")] == ["Base"]


def test_leaderboard_keeps_each_players_best(db):
    store.submit("Ann", "maruti-15000", 400, 15100, 63, "plausible", "a")
    store.submit("Ann", "maruti-15000", 640, 15200, 80, "probable", "b")
    store.submit("Bob", "maruti-15000", 500, 15050, 70, "plausible", "c")
    store.submit("Bob", "tmpv-price", 300, 270, 55, "probable", "d")
    board = store.leaderboard("maruti-15000")
    assert [(r["player"], r["points"]) for r in board] == [("Ann", 640), ("Bob", 500)]
    assert board[0]["headline"] == "b"
    overall = store.leaderboard()
    assert [(r["player"], r["points"], r["challenges"]) for r in overall] == [("Bob", 800, 2), ("Ann", 640, 1)]
