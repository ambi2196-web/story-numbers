"""Story ⇄ Numbers: search bar → 5-year financials → Excel.   Run: streamlit run app/ui/streamlit_app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # let `streamlit run` find the app package

import pandas as pd
import streamlit as st

from app.data import damodaran
from app.data.collector import LABELS, CompanyNotFound, collect, resolve, search
from app.data.ratios import RATIO_FORMATS, RATIO_LABELS, compute
from app.excel.workbook import build, units
from app.llm import LLMError, get_provider

st.set_page_config(page_title="Story ⇄ Numbers", page_icon="📈", layout="wide")


@st.cache_data(ttl=3600, show_spinner=False)
def cached_search(query: str) -> list[dict]:
    return search(query)


def fmt_ratio(key: str, v: float) -> str:
    if pd.isna(v):
        return ""
    return {"pct": f"{v:.1%}", "x": f"{v:.2f}x"}.get(RATIO_FORMATS[key], f"{v:,.0f}")


st.title("Story ⇄ Numbers")
st.caption("Damodaran-style valuation game. Pick a company; every valuation is a story told in numbers.")

query = st.text_input("Company name or ticker", placeholder="e.g. Maruti Suzuki, Tata Motors, Apple")
if not query:
    st.stop()

with st.spinner("Searching…"):
    matches = cached_search(query)
if not matches:
    # Renamed or misspelt companies (e.g. Zomato is now Eternal): ask the AI for the ticker.
    with st.spinner("Not on Yahoo search; asking the AI…"):
        try:
            symbol = resolve(query, llm=get_provider())
            matches = [{"symbol": symbol, "name": symbol, "exchange": "found by AI"}]
        except (CompanyNotFound, LLMError):
            st.warning(f"No listed company found for '{query}'. Fictional companies arrive in Phase 3.")
            st.stop()

choice = st.selectbox("Did you mean", matches, format_func=lambda m: f"{m['name']}  ·  {m['symbol']}  ·  {m['exchange']}")

with st.spinner(f"Collecting 5 years of financials for {choice['name']}…"):
    try:
        company = collect(choice["symbol"])
    except CompanyNotFound as exc:
        st.error(str(exc))
        st.stop()

p = company.profile
scale, unit = units(p.get("currency"))
ratios = compute(company.financials)
latest = company.financials.columns[-1]

st.subheader(f"{p['name']}  ·  {p['symbol']}")
cols = st.columns(4)
cols[0].metric(f"Share price ({p.get('price_currency') or ''})", f"{p.get('price') or 0:,.2f}")
cols[1].metric(f"Market cap ({unit})", f"{(p.get('market_cap') or 0) / scale:,.0f}")
cols[2].metric(f"Revenue {latest} ({unit})", f"{company.financials.loc['revenue', latest] / scale:,.0f}")
cols[3].metric(f"Operating margin {latest}", fmt_ratio("operating_margin", ratios.loc["operating_margin", latest]))
st.caption(f"{p.get('industry')} → Damodaran group **{p.get('damodaran_industry')}** ({p.get('region')}) · "
           f"Data: {p.get('source')}")

with st.expander("What the company does", expanded=True):
    st.write(p.get("summary") or "No description available.")

tab_fin, tab_ratios, tab_bench = st.tabs(["Financials", "Ratios", "Industry benchmarks"])
with tab_fin:
    table = (company.financials / scale).rename(index=LABELS)
    table.loc[LABELS["diluted_shares"]] = company.financials.loc["diluted_shares"] / 1e6
    st.dataframe(table.style.format("{:,.0f}", na_rep=""), use_container_width=True)
    st.caption(f"{unit}; shares in millions.")
with tab_ratios:
    shown = pd.DataFrame({y: {RATIO_LABELS[k]: fmt_ratio(k, ratios.loc[k, y] / (scale if RATIO_FORMATS[k] == "money" else 1))
                              for k in ratios.index} for y in ratios.columns})
    st.dataframe(shown, use_container_width=True)
with tab_bench:
    try:
        b = damodaran.benchmarks(p["damodaran_industry"], p["region"])
        avg = ratios.mean(axis=1)
        st.dataframe(pd.DataFrame({
            "Company (5Y avg)": [fmt_ratio("operating_margin", avg["operating_margin"]),
                                 fmt_ratio("sales_to_capital", avg["sales_to_capital"]),
                                 fmt_ratio("effective_tax_rate", avg["effective_tax_rate"]), ""],
            f"Industry ({p['region']})": [fmt_ratio("operating_margin", b["operating_margin"]) or "n/a",
                                          fmt_ratio("sales_to_capital", b["sales_to_capital"]) or "n/a",
                                          fmt_ratio("effective_tax_rate", b["effective_tax_rate"]) or "n/a",
                                          fmt_ratio("roic", b["cost_of_capital"]) or "n/a"],
        }, index=["Operating margin", "Sales-to-capital", "Effective tax rate", "Cost of capital"]),
            use_container_width=True)
        st.caption("Source: Aswath Damodaran's industry datasets (NYU Stern).")
    except KeyError as exc:
        st.info(str(exc))

st.download_button("⬇ Download Excel (live formulas)", data=build(company),
                   file_name=f"{p['symbol']}_financials.xlsx", type="primary",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.info("Next: tell a story (Mode A) or set a target (Mode B). Coming in Phases 4 and 5.", icon="🧭")
st.caption("Educational tool, not investment advice.")
