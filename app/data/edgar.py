"""SEC EDGAR XBRL "company facts": as-filed 10-K numbers for US-listed companies, free and official.

Yahoo usually has only 4 complete years; the 10-K facts go back much further, so US companies get the full
five. SEC asks for a descriptive User-Agent (set SEC_USER_AGENT in .env to include your contact email).
"""
import os

import httpx
import pandas as pd

from app.data import cache

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# our field -> us-gaap concepts, first with data wins (companies pick different tags for the same line)
CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "cost_of_revenue": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "gross_profit": ["GrossProfit"],
    "sga": ["SellingGeneralAndAdministrativeExpense"],
    "rnd": ["ResearchAndDevelopmentExpense"],
    "depreciation": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                     "DepreciationAmortizationAndAccretionNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "inventory": ["InventoryNet"],
    "receivables": ["AccountsReceivableNetCurrent"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "net_ppe": ["PropertyPlantAndEquipmentNet"],
    "total_assets": ["Assets"],
    "equity": ["StockholdersEquity"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "acquisitions": ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
    "dividends": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
}
# Balance-sheet totals that depend on how each company groups debt, leases and investments stay with Yahoo
# (cash, investments, debt, minority interest), so their definitions match across companies.


def _headers() -> dict:
    return {"User-Agent": os.getenv("SEC_USER_AGENT", "StoryNumbers educational valuation project")}


def _cik(symbol: str) -> int | None:
    table = cache.get("sec:tickers", max_age_hours=24 * 7)
    if table is None:
        r = httpx.get(TICKERS_URL, headers=_headers(), timeout=20)
        r.raise_for_status()
        table = {row["ticker"].upper(): row["cik_str"] for row in r.json().values()}
        cache.put("sec:tickers", table)
    return table.get(symbol.upper().replace("-", "."), table.get(symbol.upper()))


def _annual(facts: dict, concept: str) -> pd.Series | None:
    """10-K values for one concept keyed by fiscal-year label, latest filing winning (restatements)."""
    node = facts.get("facts", {}).get("us-gaap", {}).get(concept)
    if not node:
        return None
    unit = "USD" if "USD" in node["units"] else "shares" if "shares" in node["units"] else None
    if unit is None:
        return None
    rows = []
    for f in node["units"][unit]:
        if not f.get("form", "").startswith("10-K"):
            continue
        end = pd.Timestamp(f["end"])
        if "start" in f and not 350 <= (end - pd.Timestamp(f["start"])).days <= 380:
            continue  # quarterly or partial-period figures inside the 10-K
        rows.append((end, f["filed"], float(f["val"])))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["end", "filed", "val"]).sort_values(["end", "filed"])
    df = df.drop_duplicates("end", keep="last")
    return pd.Series(df["val"].values, index=[f"FY{e.year}" for e in df["end"]]).groupby(level=0).last()


def fetch(symbol: str) -> pd.DataFrame | None:
    """Standardised annual financials (rows = our field keys, columns = FY labels), or None if not an SEC filer."""
    if "." in symbol and not symbol.endswith((".A", ".B")):
        return None  # exchange suffix: not a US listing
    try:
        cik = _cik(symbol)
        if cik is None:
            return None
        r = httpx.get(FACTS_URL.format(cik=cik), headers=_headers(), timeout=30)
        r.raise_for_status()
        facts = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    rows = {}
    for key, concepts in CONCEPTS.items():
        # concepts are tried in order per year, so a company that switched tags keeps a continuous series
        series = [s for c in concepts if (s := _annual(facts, c)) is not None]
        if series:
            merged = series[0]
            for s in series[1:]:
                merged = merged.combine_first(s)
            rows[key] = merged
    if "revenue" not in rows:
        return None  # files under IFRS (20-F) or no usable revenue tag
    df = pd.DataFrame(rows).T
    for flip in ("capex", "acquisitions", "dividends"):
        if flip in df.index:
            df.loc[flip] = df.loc[flip].abs()
    return df.astype(float)
