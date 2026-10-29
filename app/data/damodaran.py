"""Aswath Damodaran's free industry datasets: the 'industry standards' every story is checked against.

Source: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html (updated each January).
Raw .xls files are downloaded to data/damodaran/raw/ and parsed into small CSVs in data/damodaran/parsed/,
which are committed so the deployed app never has to download anything.

Refresh once a year:  python -m app.data.damodaran refresh
"""
import re
import sys

import httpx
import pandas as pd

from app.config import DATA_DIR

BASE_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/"
RAW_DIR = DATA_DIR / "damodaran" / "raw"
PARSED_DIR = DATA_DIR / "damodaran" / "parsed"

# Region label -> file-name suffix used on Damodaran's site ("" is the US file).
REGIONS = {"US": "", "India": "India", "Global": "Global", "Emerging": "emerg",
           "Europe": "Europe", "China": "China", "Japan": "Japan"}
DATASETS = ["margin", "wacc", "capex", "beta", "taxrate"]
COUNTRY_FILE = "ctryprem.xlsx"


def _file_name(dataset: str, region: str) -> str:
    if dataset == "beta" and region == "US":
        return "betas.xls"
    return f"{dataset}{REGIONS[region]}.xls"


def _clean(name) -> str:
    return re.sub(r"\s+", " ", str(name)).strip()


def _download(file_name: str) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    resp = httpx.get(BASE_URL + file_name, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    (RAW_DIR / file_name).write_bytes(resp.content)


def _parse_industry_file(file_name: str) -> pd.DataFrame:
    """Damodaran files have a few title rows, then a header row starting with 'Industry Name'."""
    raw = pd.read_excel(RAW_DIR / file_name, sheet_name="Industry Averages", header=None, engine="calamine")
    header_row = raw.index[raw.iloc[:, 0].astype(str).str.strip().str.lower() == "industry name"][0]
    df = raw.iloc[header_row + 1 :].copy()
    names, seen = ["Industry Name"], {}
    for c in raw.iloc[header_row, 1:]:
        c = _clean(c)
        seen[c] = seen.get(c, 0) + 1
        names.append(c if seen[c] == 1 else f"{c} ({seen[c]})")  # some files repeat a header
    df.columns = names
    df = df.loc[:, [c for c in df.columns if c and not c.startswith("nan")]]
    df = df.dropna(subset=["Industry Name"])
    df["Industry Name"] = df["Industry Name"].map(_clean)
    for col in df.columns[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.reset_index(drop=True)


def _parse_country_file() -> pd.DataFrame:
    raw = pd.read_excel(RAW_DIR / COUNTRY_FILE, sheet_name="Regional breakdown", engine="calamine")
    raw.columns = [_clean(c) for c in raw.columns]
    df = raw.rename(columns={"Equity Risk Premium": "ERP", "Country Risk Premium": "CRP",
                             "Corporate Tax Rate": "Tax Rate", "Adj. Default Spread": "Default Spread"})
    df = df[["Country", "Region", "Moody's rating", "Default Spread", "ERP", "CRP", "Tax Rate"]].dropna(subset=["Country"])
    df["Country"] = df["Country"].map(_clean)
    return df.reset_index(drop=True)


# Header cells of each wacc file: the market-wide inputs behind that region's cost of capital.
_MARKET_LABELS = {"treasury_rate": "long term treasury bond rate", "equity_risk_premium": "risk premium to use for equity",
                  "default_spread": "global default spread", "marginal_tax_rate": "enter the marginal tax rate",
                  "inflation_usd": "expected inflation rate in us $", "inflation_local": "expected inflation rate in"}


def _parse_market_inputs(file_name: str) -> dict:
    raw = pd.read_excel(RAW_DIR / file_name, sheet_name="Industry Averages", header=None, engine="calamine")
    out = {}
    for _, row in raw.head(20).iterrows():
        label = str(row.iloc[0]).lower()
        value = next((v for v in row.iloc[1:] if isinstance(v, (int, float)) and pd.notna(v)), None)
        key = next((k for k, text in _MARKET_LABELS.items() if text in label and k not in out), None)
        if key and value is not None:
            out[key] = float(value)
    return out


def _write_market_inputs(regions: list[str]) -> None:
    rows = [{"region": r} | _parse_market_inputs(_file_name("wacc", r)) for r in regions]
    pd.DataFrame(rows).to_csv(PARSED_DIR / "market_inputs.csv", index=False)


def market_inputs(region: str = "Global") -> dict:
    """Treasury rate, ERP, default spread, marginal tax and inflation Damodaran used for a region's data."""
    df = pd.read_csv(PARSED_DIR / "market_inputs.csv").set_index("region")
    return {k: float(v) for k, v in df.loc[region].dropna().items()}


def refresh(regions: list[str] | None = None) -> None:
    """Download and parse every dataset for the given regions (default: all)."""
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    for region in regions or list(REGIONS):
        for dataset in DATASETS:
            name = _file_name(dataset, region)
            _download(name)
            _parse_industry_file(name).to_csv(PARSED_DIR / f"{dataset}_{region}.csv", index=False)
            print(f"  {dataset:8} {region}")
    _write_market_inputs(regions or list(REGIONS))
    _download(COUNTRY_FILE)
    _parse_country_file().to_csv(PARSED_DIR / "country_risk.csv", index=False)
    print("  market inputs and country risk premiums")


def load_industry(dataset: str, region: str = "Global") -> pd.DataFrame:
    path = PARSED_DIR / f"{dataset}_{region}.csv"
    if not path.exists():
        refresh([region])
    return pd.read_csv(path)


def load_country_risk() -> pd.DataFrame:
    path = PARSED_DIR / "country_risk.csv"
    if not path.exists():
        _download(COUNTRY_FILE)
        PARSED_DIR.mkdir(parents=True, exist_ok=True)
        _parse_country_file().to_csv(path, index=False)
    return pd.read_csv(path)


def industries(region: str = "Global") -> list[str]:
    return load_industry("margin", region)["Industry Name"].tolist()


def _col(df: pd.DataFrame, *prefixes: str) -> str | None:
    """First column whose name starts with any prefix (case-insensitive); Damodaran renames columns over the years."""
    for prefix in prefixes:
        for col in df.columns:
            if col.lower().startswith(prefix.lower()):
                return col
    return None


def benchmarks(industry: str, region: str = "Global") -> dict:
    """Industry averages used as defaults and as plausibility limits for a story."""
    def row(dataset: str) -> pd.Series:
        df = load_industry(dataset, region)
        match = df[df["Industry Name"].str.lower() == industry.lower()]
        if match.empty:
            raise KeyError(f"Industry '{industry}' not in Damodaran {region} data")
        return match.iloc[0]

    margin, wacc, capex, tax = row("margin"), row("wacc"), row("capex"), row("taxrate")
    wacc_df, capex_df, margin_df, tax_df = (load_industry(d, region) for d in ("wacc", "capex", "margin", "taxrate"))
    coc_col = _col(wacc_df, "Cost of Capital (Local") or _col(wacc_df, "Cost of Capital")

    values = {
        "firms": margin[_col(margin_df, "Number of firms")],
        "gross_margin": margin[_col(margin_df, "Gross Margin")],
        "operating_margin": margin[_col(margin_df, "Pre-tax Lease adjusted", "Pre-tax Unadjusted Operating")],
        "net_margin": margin[_col(margin_df, "Net Margin")],
        "sales_to_capital": capex[_col(capex_df, "Sales/ Invested Capital", "Sales/Invested Capital")],
        "beta": wacc[_col(wacc_df, "Beta")],
        "cost_of_equity": wacc[_col(wacc_df, "Cost of Equity")],
        "cost_of_capital": wacc[coc_col],
        "debt_to_capital": wacc[_col(wacc_df, "D/(D+E)")],
        # The money-making-firms average is blank for some small groups; fall back to the aggregate rate.
        "effective_tax_rate": next((tax[c] for c in (_col(tax_df, "Average across only money-making"),
                                                     _col(tax_df, "Aggregate tax rate"))
                                    if c and pd.notna(tax[c])), float("nan")),
    }
    return {"industry": industry, "region": region} | {k: float(v) for k, v in values.items()}


def country_risk(country: str) -> dict:
    df = load_country_risk()
    match = df[df["Country"].str.lower() == country.lower()]
    if match.empty:
        raise KeyError(f"Country '{country}' not in Damodaran country risk data")
    r = match.iloc[0]
    return {"country": r["Country"], "rating": r["Moody's rating"], "default_spread": float(r["Default Spread"]),
            "equity_risk_premium": float(r["ERP"]), "country_risk_premium": float(r["CRP"]),
            "tax_rate": float(r["Tax Rate"])}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        refresh(sys.argv[2:] or None)
    else:
        print(benchmarks(sys.argv[1] if len(sys.argv) > 1 else "Auto & Truck", "India"))
        print(country_risk("India"))
