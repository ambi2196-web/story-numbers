"""Company search bar backend: name -> ticker -> up to 5 years of standardised financials.

Yahoo Finance (via yfinance) covers NSE/BSE and US listings for free. It usually has only 4 complete years, so
Screener.in (Indian companies) and SEC EDGAR 10-K filings (US companies) add the fifth year and as-filed lines.
Everything is cached for a day so repeat lookups cost nothing.
"""
import warnings
from dataclasses import dataclass, field
from io import StringIO

import pandas as pd
import yfinance as yf
from pydantic import BaseModel

from app.data import cache, edgar, nse, screener
from app.data.net import SourceUnavailable, retry  # noqa: F401  (re-exported for the UI)
from app.data.industry_map import to_damodaran_industry, to_region

warnings.filterwarnings("ignore", module="yfinance")  # pandas deprecation noise from inside yfinance

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
    names = {m["name"].lower().rstrip(". ") for m in nse_hits}
    symbols = {m["symbol"].removesuffix(".NS") for m in nse_hits}
    # Yahoo adds non-Indian listings and BSE-only stocks; drop its copies of companies NSE already listed.
    others = [m for m in _yahoo_search(query, limit) if m["name"].lower().rstrip(". ") not in names
              and m["symbol"].split(".")[0] not in symbols and not (nse_hits and m["symbol"].endswith(".NS"))]
    return (nse_hits + others)[:limit]


def _yahoo_search(query: str, limit: int) -> list[dict]:
    quotes = retry(lambda: yf.Search(query, max_results=10).quotes, "Yahoo Finance search")
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


def _merge(yahoo: pd.DataFrame, primary: pd.DataFrame | None, name: str = "Screener.in") -> tuple[pd.DataFrame, dict]:
    """Each field comes from ONE source for every year (the primary source, Screener.in or SEC EDGAR, first when
    it has the field), so growth rates are never distorted by mixing definitions. Returns the last MAX_YEARS
    years and per-field sources."""
    frames = [yahoo] + ([primary] if primary is not None else [])
    years = sorted({y for df in frames for y in df.columns if pd.notna(df.loc["revenue"].get(y))})[-MAX_YEARS:]
    rows, sources = {}, {}
    for key, _, _, _ in FIELDS:
        if primary is not None and key in primary.index and primary.loc[key].reindex(years).notna().any():
            rows[key], sources[key] = primary.loc[key].reindex(years), name
        else:
            rows[key], sources[key] = yahoo.loc[key].reindex(years), "Yahoo Finance"
    df = pd.DataFrame(rows).T.astype(float)
    # Years the primary source does not cover at all (it shows fewer years) are taken whole from Yahoo, but only
    # when both sources agree on revenue in the years they share; otherwise mixing would distort growth.
    if primary is not None:
        missing = [y for y in years if y not in primary.columns or primary[y].isna().all()]
        shared = [y for y in years if y in primary.columns and pd.notna(primary.loc["revenue"].get(y))
                  and pd.notna(yahoo.loc["revenue"].get(y))]
        gap = (primary.loc["revenue", shared] / yahoo.loc["revenue", shared] - 1).abs().median() if shared else 1
        if missing and gap < 0.05:
            for y in missing:
                df[y] = yahoo[y].reindex(df.index) if y in yahoo.columns else df[y]
            sources["_years_from_yahoo"] = ", ".join(missing)
    return df, sources


_NOT_MONEY = ("share", "rate", "ratio")


def _needs_fx(yahoo: pd.DataFrame, screener_df: pd.DataFrame) -> bool:
    """Yahoo's currency label is unreliable (it says USD for HCL Tech's INR numbers), so compare revenues:
    a Screener/Yahoo ratio far above 1 for the same years means Yahoo's numbers are in a foreign currency."""
    ratio = (screener_df.loc["revenue"] / yahoo.loc["revenue"]).dropna()
    return bool(len(ratio)) and ratio.median() > 10


def _convert(raw: dict[str, pd.DataFrame], src: str, dst: str) -> dict[str, pd.DataFrame]:
    """Restate Yahoo's statements in another currency at each fiscal year-end's exchange rate.
    Needed when Yahoo reports an Indian company in USD (Infosys, HCL Tech) but Screener.in reports in INR."""
    dates = [pd.Timestamp(c) for df in raw.values() for c in df.columns]
    hist = yf.Ticker(f"{src}{dst}=X").history(start=min(dates) - pd.Timedelta(days=10),
                                               end=max(dates) + pd.Timedelta(days=3))["Close"]
    if hist.empty:
        raise CompanyNotFound(f"No {src}/{dst} exchange rate history to restate the statements.")
    hist.index = hist.index.tz_localize(None)
    out = {}
    for name, df in raw.items():
        rates = pd.Series({c: float(hist.asof(pd.Timestamp(c))) for c in df.columns})
        money = [r for r in df.index if not any(w in str(r).lower() for w in _NOT_MONEY)]
        df = df.copy()
        df.loc[money] = df.loc[money].astype(float).mul(rates, axis=1)
        out[name] = df
    return out


def _by_fiscal_year(df: pd.DataFrame) -> pd.DataFrame:
    """Oldest year first, columns labelled FY<year the fiscal year ends>."""
    df = df[sorted(df.columns)]
    df.columns = [f"FY{pd.Timestamp(c).year}" for c in df.columns]
    return df


def fiscal_year(label: str) -> int:
    return int(str(label)[2:])


def period_note(financials: pd.DataFrame) -> str | None:
    """Gaps in the fiscal years (a change of year-end leaves a short period neither source reports as a year)."""
    years = [fiscal_year(c) for c in financials.columns]
    gaps = [f"FY{y}" for y in range(min(years), max(years) + 1) if y not in years] if years else []
    blank = [c for c in financials.columns if pd.isna(financials.loc["revenue", c])]
    notes = []
    if gaps:
        notes.append(f"No figures for {', '.join(gaps)} (a change of fiscal year-end or a short period); growth "
                     "rates use the actual years between figures")
    if blank:
        notes.append(f"revenue missing for {', '.join(blank)}")
    return "; ".join(notes) + "." if notes else None


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
    raw = retry(lambda: {"income": ticker.income_stmt, "balance": ticker.balance_sheet,
                         "cashflow": ticker.cash_flow}, "Yahoo Finance")
    if raw["income"] is None or raw["income"].empty:
        raise CompanyNotFound(f"Yahoo Finance has no annual statements for {symbol} (delisted, or not a "
                              "company: funds and indices have none).")
    info = retry(lambda: ticker.info, "Yahoo Finance")
    screener_df = screener.fetch(symbol)
    reported = info.get("financialCurrency")
    converted = bool(screener_df is not None and reported and reported != "INR"
                     and _needs_fx(_standardise(raw), screener_df))
    if converted:
        raw = _convert(raw, reported, "INR")  # Screener is always INR; one currency per company
    if screener_df is not None:
        info = info | {"financialCurrency": "INR"}
    sec_df = edgar.fetch(symbol) if screener_df is None else None
    if sec_df is not None and info.get("financialCurrency", "USD") != "USD":
        sec_df = None  # only US-dollar filers, so the two sources share a currency
    primary, name = (screener_df, "Screener.in") if screener_df is not None else (sec_df, "SEC EDGAR")
    financials, sources = _merge(_standardise(raw), primary, name)
    raw = {k: _by_fiscal_year(v) for k, v in raw.items()}
    profile = _profile(symbol, info, list(financials.columns))
    if converted:
        profile["fx_note"] = f"Yahoo reports in {reported}; restated in INR at each fiscal year-end rate."
    if note := period_note(financials):
        profile["period_note"] = note
    if filled := sources.pop("_years_from_yahoo", None):
        profile["fx_note"] = "; ".join(filter(None, [profile.get("fx_note"),
                                                    f"{filled} from Yahoo Finance ({name} does not go back that far)"]))
    profile["field_sources"] = sources
    profile["source"] = f"{name} + Yahoo Finance" if primary is not None else "Yahoo Finance"
    company = Company(profile, financials, raw)
    cache.put(key, company.to_cache())
    return company
