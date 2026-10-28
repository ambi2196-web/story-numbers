"""Company search bar backend: name -> ticker -> up to 5 years of standardised financials.

Yahoo Finance (via yfinance) covers NSE/BSE and US listings for free; for Indian companies Screener.in adds a
fifth year and the as-reported revenue line.
Everything is cached for a day so repeat lookups cost nothing.
"""
from dataclasses import dataclass, field
from io import StringIO

import pandas as pd
import yfinance as yf
from pydantic import BaseModel

from app.data import cache, nse, screener
from app.data.industry_map import to_damodaran_industry, to_region

MAX_YEARS = 5
# Prefer the primary listing when Yahoo returns several (e.g. NSE over BSE for Indian companies).
EXCHANGE_RANK = {"NSI": 0, "NMS": 1, "NYQ": 1, "NGM": 1, "NCM": 1, "ASE": 1, "BSE": 2}

# key, label, candidate Yahoo rows as "statement:Row Name" (first non-empty wins), flip sign to positive
FIELDS = [
    ("revenue", "Revenue", ["income:Total Revenue", "income:Operating Revenue"], False),
    ("cost_of_revenue", "Cost of revenue", ["income:Cost Of Revenue", "income:Reconciled Cost Of Revenue"], False),
    ("gross_profit", "Gross profit", ["income:Gross Profit"], False),
    ("sga", "Selling, general & admin", ["income:Selling General And Administration"], False),
    ("rnd", "Research & development", ["income:Research And Development"], False),
    ("depreciation", "Depreciation & amortisation",
     ["cashflow:Depreciation And Amortization", "income:Reconciled Depreciation"], False),
    ("operating_income", "Operating income (EBIT)", ["income:Operating Income", "income:EBIT"], False),
    ("interest_expense", "Interest expense", ["income:Interest Expense", "income:Interest Expense Non Operating"], False),
    ("pretax_income", "Pre-tax income", ["income:Pretax Income"], False),
    ("tax", "Income tax", ["income:Tax Provision"], False),
    ("net_income", "Net income to shareholders", ["income:Net Income Common Stockholders", "income:Net Income"], False),
    ("diluted_shares", "Diluted shares (avg)", ["income:Diluted Average Shares", "income:Basic Average Shares"], False),
    ("cash", "Cash & short-term investments",
     ["balance:Cash Cash Equivalents And Short Term Investments", "balance:Cash And Cash Equivalents"], False),
    ("financial_investments", "Long-term financial investments",
     ["balance:Investmentin Financial Assets", "balance:Available For Sale Securities"], False),
    ("equity_investments", "Investments in associates / JVs", ["balance:Long Term Equity Investment"], False),
    ("inventory", "Inventory", ["balance:Inventory"], False),
    ("receivables", "Receivables", ["balance:Accounts Receivable", "balance:Receivables"], False),
    ("current_assets", "Current assets", ["balance:Current Assets"], False),
    ("current_liabilities", "Current liabilities", ["balance:Current Liabilities"], False),
    ("current_debt", "Short-term debt (incl. leases)",
     ["balance:Current Debt And Capital Lease Obligation", "balance:Current Debt"], False),
    ("net_ppe", "Net PP&E", ["balance:Net PPE"], False),
    ("total_assets", "Total assets", ["balance:Total Assets"], False),
    ("total_debt", "Total debt (incl. leases)", ["balance:Total Debt"], False),
    ("equity", "Shareholders' equity", ["balance:Stockholders Equity", "balance:Common Stock Equity"], False),
    ("minority_interest", "Minority interest", ["balance:Minority Interest"], False),
    ("operating_cash_flow", "Cash from operations", ["cashflow:Operating Cash Flow"], False),
    ("capex", "Capital expenditure", ["cashflow:Capital Expenditure", "cashflow:Purchase Of PPE"], True),
    ("acquisitions", "Acquisitions", ["cashflow:Purchase Of Business"], True),
    ("dividends", "Dividends paid", ["cashflow:Cash Dividends Paid", "cashflow:Common Stock Dividend Paid"], True),
]
LABELS = {key: label for key, label, _, _ in FIELDS}


class CompanyNotFound(LookupError):
    pass


@dataclass
class Company:
    profile: dict
    financials: pd.DataFrame  # rows = FIELDS keys, columns = fiscal years oldest -> newest
    raw: dict[str, pd.DataFrame] = field(default_factory=dict)  # Yahoo's statements, as reported

    def to_cache(self) -> dict:
        return {"profile": self.profile, "financials": self.financials.to_json(),
                "raw": {k: v.to_json() for k, v in self.raw.items()}}

    @classmethod
    def from_cache(cls, data: dict) -> "Company":
        def load(s: str) -> pd.DataFrame:
            return pd.read_json(StringIO(s))
        return cls(data["profile"], load(data["financials"]), {k: load(v) for k, v in data["raw"].items()})


# ---------------------------------------------------------------- search

class _TickerGuess(BaseModel):
    ticker: str


def search(query: str, limit: int = 6) -> list[dict]:
    """Equity matches for a free-text name, best first: NSE's own names first, then other Yahoo listings."""
    nse_hits = nse.search(query, limit)
    seen = {m["name"].lower().rstrip(". ") for m in nse_hits}
    others = [m for m in _yahoo_search(query, limit)
              if not m["symbol"].endswith((".NS", ".BO")) and m["name"].lower().rstrip(". ") not in seen]
    return (nse_hits + others)[:limit]


def _yahoo_search(query: str, limit: int) -> list[dict]:
    quotes = yf.Search(query, max_results=10).quotes
    # Group listings of the same company (keeping Yahoo's relevance order between companies),
    # then pick the home listing in each group: NSE over a US ADR, either over BSE or foreign lines.
    groups: dict[str, list[dict]] = {}
    for q in quotes:
        if q.get("quoteType") == "EQUITY":
            name = q.get("longname") or q.get("shortname") or q["symbol"]
            groups.setdefault(name.lower().rstrip(". "), []).append(q | {"name": name})
    results = []
    for listings in groups.values():
        best = min(listings, key=lambda q: EXCHANGE_RANK.get(q.get("exchange"), 3))
        results.append({"symbol": best["symbol"], "name": best["name"],
                        "exchange": best.get("exchDisp") or best.get("exchange")})
    return results[:limit]


def resolve(query: str, llm=None) -> str:
    """Turn what the user typed into a Yahoo ticker. Tries Yahoo search, then optionally asks the LLM."""
    query = query.strip()
    matches = search(query)
    if matches:
        return matches[0]["symbol"]
    if llm is not None:
        guess = llm.complete_json(
            f"What is the Yahoo Finance ticker of the listed company '{query}'? Use the .NS suffix for "
            "NSE-listed Indian companies. If it is not a listed company, return an empty ticker.", _TickerGuess).ticker
        if guess and yf.Ticker(guess).info.get("longName"):
            return guess
    raise CompanyNotFound(f"No listed company found for '{query}'.")


# ---------------------------------------------------------------- fetch

def _pick(raw: dict[str, pd.DataFrame], candidates: list[str]) -> pd.Series | None:
    for cand in candidates:
        stmt, row = cand.split(":", 1)
        df = raw.get(stmt)
        if df is not None and row in df.index and df.loc[row].notna().any():
            return df.loc[row]
    return None


def _standardise(raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    years = [c for c in raw["income"].columns if pd.notna(raw["income"].get(c, pd.Series()).get("Total Revenue"))]
    years = sorted(years)[-MAX_YEARS:]
    rows = {}
    for key, _, candidates, flip in FIELDS:
        series = _pick(raw, candidates)
        values = series.reindex(years) if series is not None else pd.Series(index=years, dtype=float)
        rows[key] = values.abs() if flip else values
    df = pd.DataFrame(rows).T.astype(float)
    if df.loc["gross_profit"].isna().all():
        df.loc["gross_profit"] = df.loc["revenue"] - df.loc["cost_of_revenue"]
    df.columns = [f"FY{pd.Timestamp(c).year}" for c in years]
    return df


def _merge(yahoo: pd.DataFrame, screener_df: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    """Each field comes from ONE source for every year (Screener first when it has the field), so growth
    rates are never distorted by mixing definitions. Returns the last MAX_YEARS years and per-field sources."""
    frames = [yahoo] + ([screener_df] if screener_df is not None else [])
    years = sorted({y for df in frames for y in df.columns if pd.notna(df.loc["revenue"].get(y))})[-MAX_YEARS:]
    rows, sources = {}, {}
    for key, _, _, _ in FIELDS:
        if screener_df is not None and key in screener_df.index and screener_df.loc[key].reindex(years).notna().any():
            rows[key], sources[key] = screener_df.loc[key].reindex(years), "Screener.in"
        else:
            rows[key], sources[key] = yahoo.loc[key].reindex(years), "Yahoo Finance"
    return pd.DataFrame(rows).T.astype(float), sources


def _by_fiscal_year(df: pd.DataFrame) -> pd.DataFrame:
    """Oldest year first, columns labelled FY<year the fiscal year ends>."""
    df = df[sorted(df.columns)]
    df.columns = [f"FY{pd.Timestamp(c).year}" for c in df.columns]
    return df


def _profile(symbol: str, info: dict, years: list[str]) -> dict:
    country = info.get("country")
    region = to_region(country)
    return {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or symbol,
        "exchange": info.get("exchange"),
        "currency": info.get("financialCurrency") or info.get("currency"),
        "price_currency": info.get("currency"),
        "country": country,
        "region": region,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "damodaran_industry": to_damodaran_industry(info.get("industry"), region),
        "summary": info.get("longBusinessSummary"),
        "website": info.get("website"),
        "employees": info.get("fullTimeEmployees"),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "shares_outstanding": info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"),
        "market_cap": info.get("marketCap"),
        "beta": info.get("beta"),
        "years": years,
    }


def collect(query: str, refresh: bool = False, llm=None) -> Company:
    """Search bar entry point: returns profile + 5-year standardised financials (cached for 24h)."""
    symbol = resolve(query, llm)
    key = f"company:{symbol}"
    if not refresh and (hit := cache.get(key)):
        return Company.from_cache(hit)

    ticker = yf.Ticker(symbol)
    raw = {"income": ticker.income_stmt, "balance": ticker.balance_sheet, "cashflow": ticker.cash_flow}
    if raw["income"] is None or raw["income"].empty:
        raise CompanyNotFound(f"Yahoo Finance has no annual statements for {symbol}.")
    screener_df = screener.fetch(symbol)
    financials, sources = _merge(_standardise(raw), screener_df)
    raw = {k: _by_fiscal_year(v) for k, v in raw.items()}
    profile = _profile(symbol, ticker.info, list(financials.columns))
    profile["field_sources"] = sources
    profile["source"] = "Screener.in + Yahoo Finance" if screener_df is not None else "Yahoo Finance"
    company = Company(profile, financials, raw)
    cache.put(key, company.to_cache())
    return company
