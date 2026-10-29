"""Story ⇄ Numbers: search bar → 5-year financials → Excel.   Run: streamlit run app/ui/streamlit_app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # let `streamlit run` find the app package

import pandas as pd
import streamlit as st

from app.data import damodaran
from app.data.collector import LABELS, CompanyNotFound, collect, resolve, search
from app.data.ratios import RATIO_FORMATS, RATIO_LABELS, compute
from app.engine.dcf import solve, value
from app.engine.defaults import status_quo
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

# ---------------------------------------------------------------- valuation (status quo story)
st.subheader("What is it worth if nothing changes?")
setup, valuation, implied = None, None, None
try:
    setup = status_quo(company)
except (KeyError, IndexError) as exc:
    st.info(f"No valuation: {exc}")
for msg in setup.warnings if setup else []:
    st.warning(msg)
if setup and not setup.is_financial:
    a0, w = setup.assumptions, setup.wacc
    with st.expander("Change the assumptions", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        growth = c1.number_input("Revenue growth, years 1-5 (%)", value=round(a0.growth_y2_5 * 100, 1), step=1.0)
        margin = c2.number_input("Target operating margin (%)", value=round(a0.target_margin * 100, 1), step=0.5)
        s2c = c3.number_input("Sales-to-capital (x)", value=round(a0.sales_to_capital_1_5, 2), step=0.1, min_value=0.05)
        wacc = c4.number_input("Cost of capital (%)", value=round(a0.cost_of_capital * 100, 2), step=0.25)
        st.caption("Defaults: " + " · ".join(f"**{k.replace('_', ' ')}**: {v}" for k, v in a0.sources.items()))
    a = a0  # untouched boxes keep the exact defaults (the boxes show them rounded)
    if growth != round(a0.growth_y2_5 * 100, 1):
        a = a.with_(growth_y1=growth / 100, growth_y2_5=growth / 100)
    if margin != round(a0.target_margin * 100, 1):
        a = a.with_(target_margin=margin / 100)
    if s2c != round(a0.sales_to_capital_1_5, 2):
        a = a.with_(sales_to_capital_1_5=s2c, sales_to_capital_6_10=s2c)
    if wacc != round(a0.cost_of_capital * 100, 2):
        a = a.with_(cost_of_capital=wacc / 100, terminal_cost_of_capital=min(a0.terminal_cost_of_capital, wacc / 100))
    try:
        valuation = value(a)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    cur = p.get("price_currency") or ""
    cols = st.columns(4)
    cols[0].metric(f"Value per share ({cur})", f"{valuation.value_per_share:,.2f}")
    cols[1].metric(f"Price ({cur})", f"{a.price:,.2f}" if a.price else "n/a")
    cols[2].metric("Value vs price", f"{valuation.upside:+.0%}" if valuation.upside is not None else "n/a")
    cols[3].metric(f"Cost of capital ({w.currency})", f"{a.cost_of_capital:.2%}")
    st.caption(f"Cost of capital: risk-free {w.riskfree_local:.2%} ({w.currency}) · levered beta {w.levered_beta:.2f} · "
               f"equity risk premium {w.equity_risk_premium:.2%} · synthetic rating {w.rating} · debt "
               f"{w.debt_weight:.0%} of capital. Terminal: growth {a.terminal_growth:.2%}, cost of capital "
               f"{a.terminal_cost_of_capital:.2%}." + (f" Terminal value is {valuation.terminal_share:.0%} of the "
               f"value." if 0 <= valuation.terminal_share <= 1 else ""))

    if a.price:
        st.markdown("**What today's price implies** (one driver at a time, everything else unchanged)")
        bench = damodaran.benchmarks(p["damodaran_industry"], p["region"])
        implied = {d: solve(a, d) for d in ("growth", "target_margin", "sales_to_capital", "terminal_roic")}
        roic_now = a.terminal_roic if a.terminal_roic is not None else a.terminal_cost_of_capital
        rows = [("Revenue growth, years 1-5", implied["growth"], a.growth_y2_5, None, "{:.1%}"),
                ("Target operating margin", implied["target_margin"], a.target_margin, bench["operating_margin"], "{:.1%}"),
                ("Sales-to-capital", implied["sales_to_capital"], a.sales_to_capital_1_5, bench["sales_to_capital"],
                 "{:.2f}x"),
                ("Return on capital after year 10", implied["terminal_roic"], roic_now, None, "{:.1%}")]
        st.dataframe(pd.DataFrame(
            [{"Driver": n, "Market-implied": f.format(x) if x is not None else "not reachable alone",
              "Status quo": f.format(cur_v), "Industry": f.format(ind) if ind is not None and pd.notna(ind) else ""}
             for n, x, cur_v, ind, f in rows]).set_index("Driver"), use_container_width=True)

    with st.expander("10-year projection"):
        t = valuation.table.copy()
        pct_rows = ["Revenue growth", "Operating margin", "Tax rate", "Cost of capital"]
        shown = pd.DataFrame({col: [("" if pd.isna(x) else f"{x:.1%}") if r in pct_rows else
                                    ("" if pd.isna(x) else f"{x:.2f}" if r in ("Sales-to-capital",
                                     "Cumulative discount factor") else f"{x / scale:,.0f}")
                                    for r, x in t[col].items()] for col in t.columns}, index=t.index)
        st.dataframe(shown, use_container_width=True)
        st.caption(f"{unit}. FCFF = after-tax operating income - reinvestment; discounted at the cost of capital.")

st.download_button("⬇ Download Excel (live formulas, incl. DCF)",
                   data=build(company, setup if valuation else None, valuation, implied),
                   file_name=f"{p['symbol']}_valuation.xlsx", type="primary",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.info("Next: tell a story (Mode A) or set a target (Mode B). Coming in Phases 4 and 5.", icon="🧭")
st.caption("Educational tool, not investment advice.")
