"""Screener.in public company pages: 10+ years of headline financials for NSE/BSE companies (in ₹ crore).

Used for Indian companies because Yahoo usually has only 4 complete years and reports a slightly different
revenue line. One request per company per day (results are cached by the collector); personal/educational use.
"""
import re
from io import StringIO

import httpx
import pandas as pd
from lxml import html

CRORE = 1e7
URL = "https://www.screener.in/company/{code}/{view}"
HEADERS = {"User-Agent": "Mozilla/5.0 (educational valuation project)"}


def _table(doc, section: str) -> pd.DataFrame | None:
    nodes = doc.xpath(f'//section[@id="{section}"]//table')
    if not nodes:
        return None
    df = pd.read_html(StringIO(html.tostring(nodes[0], encoding="unicode")))[0]
    df = df.set_index(df.columns[0])
    df.index = [re.sub(r"\s*[+\-]\s*$", "", str(i)).strip() for i in df.index]
    # "Mar 2024" -> "FY2024"; drop TTM and anything that is not a fiscal-year column
    years = {c: f"FY{c.split()[-1]}" for c in df.columns if re.fullmatch(r"[A-Za-z]{3} \d{4}", str(c))}
    df = df[list(years)].rename(columns=years)
    df = df.loc[:, ~df.columns.duplicated(keep="last")]
    return df.apply(lambda col: pd.to_numeric(col.astype(str).str.replace(",", "").str.rstrip("%"), errors="coerce"))


def _row(df: pd.DataFrame | None, *names: str) -> pd.Series | None:
    if df is None:
        return None
    for name in names:
        if name in df.index:
            return df.loc[name]
    return None


def fetch(symbol: str) -> pd.DataFrame | None:
    """Standardised fields (same keys as collector.FIELDS, base currency units) or None if unavailable."""
    if not symbol.endswith((".NS", ".BO")):
        return None
    code = symbol.rsplit(".", 1)[0]
    for view in ("consolidated/", ""):
        try:
            resp = httpx.get(URL.format(code=code, view=view), headers=HEADERS, follow_redirects=True, timeout=20)
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            continue
        doc = html.fromstring(resp.text)
        pl, bs, cf = (_table(doc, s) for s in ("profit-loss", "balance-sheet", "cash-flow"))
        sales = _row(pl, "Sales", "Revenue")
        if sales is not None and sales.notna().sum() >= 3:
            return _standardise(pl, bs, cf)
    return None


def _standardise(pl, bs, cf) -> pd.DataFrame:
    r = lambda df, *n: _row(df, *n)  # noqa: E731
    sales, op, dep = r(pl, "Sales", "Revenue"), r(pl, "Operating Profit", "Financing Profit"), r(pl, "Depreciation")
    pbt, tax_pct, net = r(pl, "Profit before tax"), r(pl, "Tax %"), r(pl, "Net Profit")
    payout = r(pl, "Dividend Payout %")
    equity_cap, reserves = r(bs, "Equity Capital"), r(bs, "Reserves")
    fixed, cwip = r(bs, "Fixed Assets"), r(bs, "CWIP")
    cfo, fcf = r(cf, "Cash from Operating Activity"), r(cf, "Free Cash Flow")

    def both(a, b, fn):
        return fn(a, b) if a is not None and b is not None else None

    rows = {
        "revenue": sales,
        "depreciation": dep,
        "operating_income": both(op, dep, lambda a, b: a - b),
        "interest_expense": r(pl, "Interest"),
        "pretax_income": pbt,
        "tax": both(pbt, tax_pct, lambda a, b: a * b / 100),
        "net_income": net,
        "total_debt": r(bs, "Borrowings", "Borrowing"),
        "equity": both(equity_cap, reserves, lambda a, b: a + b),
        "total_assets": r(bs, "Total Assets"),
        "net_ppe": both(fixed, cwip, lambda a, b: a + b.fillna(0)),
        "operating_cash_flow": cfo,
        "capex": both(cfo, fcf, lambda a, b: a - b),
        "dividends": both(net, payout, lambda a, b: a * b / 100),
    }
    df = pd.DataFrame({k: v for k, v in rows.items() if v is not None}).T * CRORE
    return df.astype(float)
