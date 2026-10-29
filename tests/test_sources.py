"""Offline tests for the data sources added in Phases 1-2: NSE names, SEC 10-K parsing, currency detection."""
import pandas as pd

from app.data import edgar, nse
from app.data.collector import _needs_fx


def test_nse_search_ranks_exact_symbol_then_names(monkeypatch):
    names = pd.DataFrame({"SYMBOL": ["MARUTI", "JAYBARMARU", "TMPV", "TMCV"],
                          "NAME": ["Maruti Suzuki India Limited", "Jay Bharat Maruti Limited",
                                   "Tata Motors Passenger Vehicles Limited", "Tata Motors Limited"]})
    monkeypatch.setattr(nse, "equities", lambda: names)
    assert [m["symbol"] for m in nse.search("maruti")] == ["MARUTI.NS", "JAYBARMARU.NS"]
    assert nse.search("MARUTI.NS")[0]["name"] == "Maruti Suzuki India Limited"
    assert {m["symbol"] for m in nse.search("Tata Motors")} == {"TMPV.NS", "TMCV.NS"}
    assert nse.search("Apple") == []


def test_edgar_keeps_full_year_10k_values_latest_filing():
    def fact(start, end, val, filed, form="10-K"):
        return {"start": start, "end": end, "val": val, "filed": filed, "form": form}
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        fact("2023-10-01", "2024-09-28", 100, "2024-11-01"),
        fact("2024-06-30", "2024-09-28", 30, "2024-11-01"),           # a quarter inside the 10-K: ignored
        fact("2022-09-25", "2023-09-30", 90, "2023-11-03"),
        fact("2022-09-25", "2023-09-30", 91, "2024-11-01"),           # restated in the next 10-K: wins
        fact("2024-09-29", "2025-09-27", 120, "2025-08-01", "10-Q"),  # not an annual filing
    ]}}}}}
    s = edgar._annual(facts, "Revenues")
    assert s.to_dict() == {"FY2023": 91.0, "FY2024": 100.0}


def test_currency_mismatch_detected_from_revenue_ratio():
    years = ["FY2025", "FY2026"]
    screener_inr = pd.DataFrame({"FY2025": [162990e7], "FY2026": [178650e7]}, index=["revenue"])
    yahoo_usd = screener_inr / 85
    assert _needs_fx(yahoo_usd, screener_inr)
    assert not _needs_fx(screener_inr * 0.97, screener_inr[years])
