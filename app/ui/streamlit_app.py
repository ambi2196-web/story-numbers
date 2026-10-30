"""Story ⇄ Numbers: search bar → 5-year financials → business profile → valuation → Excel.
Run: streamlit run app/ui/streamlit_app.py"""
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
from app.story.fictional import FictionalSpec, draft, setup_for
from app.story.market_story import market_story
from app.story.profile import apply_industry, build_profile, cached_profile

st.set_page_config(page_title="Story ⇄ Numbers", page_icon="📈", layout="wide")


@st.cache_data(ttl=3600, show_spinner=False)
def cached_search(query: str) -> list[dict]:
    return search(query)


@st.cache_resource
def llm():
    try:
        return get_provider()
    except LLMError:
        return None


def md(text: str) -> str:
    """AI text shown as Markdown: a '$' would otherwise start a LaTeX formula ("$500B ... $300B")."""
    return text.replace("$", "\\$")


def fmt_ratio(key: str, v: float) -> str:
    if pd.isna(v):
        return ""
    return {"pct": f"{v:.1%}", "x": f"{v:.2f}x"}.get(RATIO_FORMATS[key], f"{v:,.0f}")


def history_tabs(company, scale: float, unit: str) -> None:
    p, ratios = company.profile, compute(company.financials)
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


def show_profile(profile) -> None:
    st.markdown(f"**{md(profile.one_liner)}**")
    c1, c2 = st.columns([3, 2])
    with c1:
        st.dataframe(pd.DataFrame([{"Line of business": s.name,
                                    "Share of revenue": f"{s.share_of_revenue:.0%}" if s.share_of_revenue is not None else "",
                                    "What it is": s.description} for s in profile.segments]).set_index("Line of business"),
                     use_container_width=True)
    with c2:
        st.dataframe(pd.DataFrame([{"Driver": d.name, "Latest (AI estimate)":
                                    f"{d.latest_value:,.6g}" if d.latest_value is not None else "n/a", "Unit": d.unit}
                                   for d in profile.unit_drivers]).set_index("Driver"), use_container_width=True)
    st.markdown(md(f"**Market:** {profile.addressable_market}  \n**Position:** {profile.competitive_position}  \n"
                   "**Risks:**\n" + "\n".join(f"- {r}" for r in profile.key_risks)))


def valuation_section(company, setup, scale: float, unit: str, profile=None) -> tuple:
    """Status-quo (or story) valuation with editable drivers, the reverse DCF and the market's story."""
    p = company.profile
    for msg in setup.warnings:
        st.warning(msg)
    if setup.is_financial:
        return None, None, None
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
        return None, None, None

    cur = p.get("price_currency") or ""
    cols = st.columns(4)
    cols[0].metric(f"Value per share ({cur})", f"{max(valuation.value_per_share, 0):,.2f}")
    cols[1].metric(f"Price ({cur})", f"{a.price:,.2f}" if a.price else "n/a")
    cols[2].metric("Value vs price", f"{valuation.upside:+.0%}" if valuation.upside is not None else "n/a")
    cols[3].metric(f"Cost of capital ({w.currency})", f"{a.cost_of_capital:.2%}")
    if valuation.equity_value < 0:
        st.error(f"The cash flows in this story are worth less than nothing ({valuation.equity_value / scale:,.0f} "
                 f"{unit}): growth costs more than it earns. Shareholders cannot lose more than they put in, so "
                 "equity is shown as zero; only a better story (margins, capital efficiency) gives it value.")
    st.caption(f"Cost of capital: risk-free {w.riskfree_local:.2%} ({w.currency}) · levered beta {w.levered_beta:.2f} · "
               f"equity risk premium {w.equity_risk_premium:.2%} · synthetic rating {w.rating} · debt "
               f"{w.debt_weight:.0%} of capital. Terminal: growth {a.terminal_growth:.2%}, cost of capital "
               f"{a.terminal_cost_of_capital:.2%}." + (f" Terminal value is {valuation.terminal_share:.0%} of the "
               f"value." if 0 <= valuation.terminal_share <= 1 else "")
               + (f" Failure probability {a.failure_probability:.0%}." if a.failure_probability else ""))

    implied, story = None, None
    if a.price:
        bench = damodaran.benchmarks(p["damodaran_industry"], p["region"])
        implied = {d: solve(a, d) for d in ("growth", "target_margin", "sales_to_capital", "terminal_roic")}
        st.markdown("**What today's price implies** (one driver at a time, everything else unchanged)")
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
        if llm() is not None and profile is not None:
            with st.spinner("Writing the market's story…"):
                story = market_story(p["name"], p["symbol"], setup, valuation, implied, bench, profile, llm())
        else:
            story = market_story(p["name"], p["symbol"], setup, valuation, implied, bench, profile, None)
        st.markdown(f"#### 📖 The market's story today: {md(story.headline)}")
        st.markdown(md(story.story))
        st.markdown(f"**3P test: {story.verdict.upper()}.** {md(story.reasoning)}")

    with st.expander("10-year projection"):
        t = valuation.table
        pct_rows = ["Revenue growth", "Operating margin", "Tax rate", "Cost of capital"]
        shown = pd.DataFrame({col: [("" if pd.isna(x) else f"{x:.1%}") if r in pct_rows else
                                    ("" if pd.isna(x) else f"{x:.2f}" if r in ("Sales-to-capital",
                                     "Cumulative discount factor") else f"{x / scale:,.0f}")
                                    for r, x in t[col].items()] for col in t.columns}, index=t.index)
        st.dataframe(shown, use_container_width=True)
        st.caption(f"{unit}. FCFF = after-tax operating income - reinvestment; discounted at the cost of capital.")
    return valuation, implied, story


def download(company, setup, valuation, implied, profile, story, name: str) -> None:
    st.download_button("⬇ Download Excel (live formulas, DCF and story)",
                       data=build(company, setup if valuation else None, valuation, implied, profile, story),
                       file_name=f"{name}_valuation.xlsx", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ================================================================ page
st.title("Story ⇄ Numbers")
st.caption("Damodaran-style valuation game. Pick a company; every valuation is a story told in numbers.")
mode = st.radio("What do you want to value?", ["A listed company", "A fictional company"], horizontal=True,
                label_visibility="collapsed")

if mode == "A fictional company":
    st.subheader("Build a fictional company")
    text = st.text_area("Describe it in a sentence or two",
                        placeholder="A quick-commerce grocery startup in Pune doing ₹50 crore revenue, losing 30% on "
                                    "sales, aiming to be the Blinkit of tier-2 cities")
    if st.button("Draft the numbers with AI", disabled=not text or llm() is None):
        with st.spinner("Drafting a starting point…"):
            try:
                st.session_state["spec"] = draft(text, llm())
            except LLMError as exc:
                st.error(f"The AI could not draft it: {exc}")
    if llm() is None:
        st.caption("No AI backend configured; fill in the numbers below yourself.")
    spec = st.session_state.get("spec") or FictionalSpec(
        name="My startup", description=text or "A fictional company.", country="India", currency="INR",
        damodaran_industry="Retail (Grocery and Food)", revenue_millions=500, operating_margin=-0.2,
        invested_capital_millions=500, growth_next_5_years=0.3, target_margin=0.08, failure_probability=0.2)
    with st.form("fictional"):
        c1, c2, c3 = st.columns(3)
        industries = damodaran.industries("Global")
        fields = dict(
            name=c1.text_input("Name", spec.name),
            country=c2.text_input("Country", spec.country),
            currency=c3.text_input("Currency (ISO)", spec.currency),
            damodaran_industry=c1.selectbox("Industry (Damodaran group)", industries,
                                            index=industries.index(spec.damodaran_industry)
                                            if spec.damodaran_industry in industries else 0),
            revenue_millions=c2.number_input("Revenue (millions)", value=float(spec.revenue_millions)),
            operating_margin=c3.number_input("Operating margin today (%)", value=spec.operating_margin * 100) / 100,
            invested_capital_millions=c1.number_input("Invested capital (millions)",
                                                      value=float(spec.invested_capital_millions)),
            cash_millions=c2.number_input("Cash (millions)", value=float(spec.cash_millions)),
            debt_millions=c3.number_input("Debt (millions)", value=float(spec.debt_millions)),
            shares_millions=c1.number_input("Shares (millions)", value=float(spec.shares_millions), min_value=0.001),
            growth_next_5_years=c2.number_input("Revenue growth, years 1-5 (%)",
                                                value=spec.growth_next_5_years * 100) / 100,
            target_margin=c3.number_input("Target operating margin (%)", value=spec.target_margin * 100) / 100,
            years_to_target_margin=int(c1.number_input("Years to reach it", value=spec.years_to_target_margin,
                                                       min_value=1, max_value=10)),
            failure_probability=c2.number_input("Probability of failure (%)", value=spec.failure_probability * 100,
                                                min_value=0.0, max_value=100.0) / 100,
        )
        st.form_submit_button("Value it")
    spec = spec.model_copy(update=fields)
    st.caption(md(spec.description))
    try:
        company, setup = setup_for(spec)
    except (KeyError, IndexError) as exc:
        st.error(f"Cannot value it: {exc}")
        st.stop()
    scale, unit = units(spec.currency)
    st.subheader(f"What is {spec.name} worth on this story?")
    valuation, implied, story = valuation_section(company, setup, scale, unit)
    download(company, setup, valuation, implied, None, None, "fictional")
    st.caption("Educational tool, not investment advice.")
    st.stop()

query = st.text_input("Company name or ticker", placeholder="e.g. Maruti Suzuki, Tata Motors, Apple")
if not query:
    st.stop()

with st.spinner("Searching…"):
    matches = cached_search(query)
if not matches:
    # Renamed or misspelt companies (e.g. Zomato is now Eternal): ask the AI for the ticker.
    with st.spinner("Not found in NSE or Yahoo search; asking the AI…"):
        try:
            if llm() is None:
                raise CompanyNotFound(query)
            symbol = resolve(query, llm=llm())
            matches = [{"symbol": symbol, "name": symbol, "exchange": "found by AI"}]
        except (CompanyNotFound, LLMError):
            st.warning(f"No listed company found for '{query}'. Try **A fictional company** above to value it anyway.")
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

# The AI profile can move the company to a better Damodaran group, so it comes before any benchmark or valuation.
profile = cached_profile(p["symbol"], llm().name) if llm() is not None else None
if profile:
    apply_industry(company, profile)

st.subheader(f"{p['name']}  ·  {p['symbol']}")
cols = st.columns(4)
cols[0].metric(f"Share price ({p.get('price_currency') or ''})", f"{p.get('price') or 0:,.2f}")
cols[1].metric(f"Market cap ({unit})", f"{(p.get('market_cap') or 0) / scale:,.0f}")
cols[2].metric(f"Revenue {latest} ({unit})", f"{company.financials.loc['revenue', latest] / scale:,.0f}")
cols[3].metric(f"Operating margin {latest}", fmt_ratio("operating_margin", ratios.loc["operating_margin", latest]))
industry_note = (f" (picked by AI; rule-based mapping was {p['rule_based_industry']})"
                 if p.get("rule_based_industry") else "")
st.caption(f"{p.get('industry')} → Damodaran group **{p.get('damodaran_industry')}**{industry_note} ({p.get('region')}) · "
           f"Data: {p.get('source')}" + (f" · {p['fx_note']}" if p.get("fx_note") else ""))

st.markdown("### The business")
if profile:
    show_profile(profile)
else:
    st.markdown(md(p.get("summary") or "No description available."))
    if llm() is not None and st.button(f"✨ Write the business profile with AI ({llm().name}, ~30 s)"):
        with st.spinner("Reading the business: segments, unit drivers, competitive position…"):
            try:
                build_profile(company, llm())
                st.rerun()
            except LLMError as exc:
                st.error(f"The AI could not write the profile: {exc}")

history_tabs(company, scale, unit)

st.markdown("### What is it worth if nothing changes?")
try:
    setup = status_quo(company)
except (KeyError, IndexError) as exc:
    st.info(f"No valuation: {exc}")
    st.stop()
valuation, implied, story = valuation_section(company, setup, scale, unit, profile)
download(company, setup, valuation, implied, profile, story, p["symbol"])
st.info("Next: tell your own story (Mode A) or set a target price (Mode B). Coming in Phases 4 and 5.", icon="🧭")
st.caption("Educational tool, not investment advice.")
