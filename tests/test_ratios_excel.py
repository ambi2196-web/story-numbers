"""Offline tests for ratio maths and the Excel export (no network: a synthetic company)."""
import math
from io import BytesIO

import pandas as pd
from openpyxl import load_workbook

from app.data.collector import FIELDS, Company
from app.data.ratios import compute, excel_formula
from app.excel.workbook import build

YEARS = ["FY2024", "FY2025", "FY2026"]


def synthetic() -> Company:
    data = {key: [math.nan] * 3 for key, *_ in FIELDS}
    data.update(revenue=[100, 120, 150], gross_profit=[40, 48, 60], operating_income=[10, 15, 20],
                pretax_income=[10, 15, 20], tax=[2.5, 3.75, 5], net_income=[7.5, 11.25, 15], depreciation=[5, 5, 6],
                capex=[8, 9, 12], equity=[80, 90, 100], total_debt=[20, 20, 20], cash=[10, 10, 20],
                current_assets=[40, 45, 60], current_liabilities=[30, 32, 40], current_debt=[5, 5, 5],
                interest_expense=[1, 1, 1])
    fin = pd.DataFrame(data, index=YEARS).T * 1e7
    profile = {"symbol": "TEST.NS", "name": "Test Motors", "currency": "INR", "price_currency": "INR",
               "country": "India", "region": "India", "damodaran_industry": "Auto & Truck", "industry": "Auto Manufacturers",
               "price": 100.0, "shares_outstanding": 1e7, "market_cap": 1e9, "beta": 1.0, "years": YEARS,
               "source": "test", "summary": "A test company."}
    return Company(profile, fin)


def test_ratio_values():
    r = compute(synthetic().financials)
    assert math.isclose(r.loc["revenue_growth", "FY2025"], 0.2)
    assert r.loc["operating_margin", "FY2026"] == 20 / 150
    assert r.loc["effective_tax_rate", "FY2026"] == 0.25
    assert math.isclose(r.loc["nopat", "FY2026"], 15e7)
    # invested capital = 100 + 20 - 20 (missing minority/investments count as 0) = 100 crore
    assert math.isclose(r.loc["invested_capital", "FY2026"], 100e7)
    assert math.isnan(r.loc["revenue_growth", "FY2024"])  # no prior year
    assert math.isnan(r.loc["roic", "FY2024"])


def test_excel_formula_blank_guard():
    f = excel_formula("{a} + N({b}) - {c@prev}", lambda name, prev: f"{'B' if prev else 'C'}{name}")
    assert f == '=IF(COUNT(Ca,Bc)<2,"",IFERROR(Ca + N(Cb) - Bc,""))'
    assert excel_formula("{a@prev}", lambda name, prev: None if prev else "C1") is None


def test_workbook_builds_with_live_formulas():
    wb = load_workbook(BytesIO(build(synthetic())))
    assert wb.sheetnames[:4] == ["Summary", "Financials", "Ratios", "Industry Benchmarks"]
    ratios = wb["Ratios"]
    formulas = [c.value for row in ratios.iter_rows(min_row=5) for c in row if isinstance(c.value, str)
                and c.value.startswith("=")]
    assert len(formulas) > 40
    assert wb["Financials"]["C5"].value == 100  # revenue shown in ₹ crore
