"""Runs against the committed CSVs in data/damodaran/parsed (no network)."""
import pytest

from app.data import damodaran


@pytest.mark.parametrize("region", list(damodaran.REGIONS))
def test_every_region_has_parsed_data(region):
    names = damodaran.industries(region)
    assert len(names) > 50
    assert "Auto & Truck" in names


def test_india_auto_benchmarks_are_sane():
    b = damodaran.benchmarks("Auto & Truck", "India")
    assert 0 < b["operating_margin"] < 0.5
    assert 0.2 < b["sales_to_capital"] < 10
    assert 0.05 < b["cost_of_capital"] < 0.25
    assert 0 < b["effective_tax_rate"] < 0.5


def test_unknown_industry_raises():
    with pytest.raises(KeyError):
        damodaran.benchmarks("Space Pirates", "India")


def test_india_country_risk():
    r = damodaran.country_risk("India")
    assert 0 < r["country_risk_premium"] < r["equity_risk_premium"] < 0.2
