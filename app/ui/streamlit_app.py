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
from app.engine.defaults import Setup, status_quo
from app.excel.workbook import build, units
from app.game import scoring, store
from app.game.challenges import CHALLENGES, FICTIONAL_TARGET, RANK, fictional_card
from app.llm import LLMError, get_provider
from app.story import story_numbers as sn
from app.story import target as tg
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


UNIT_SCALE = {"pct": (100, "%"), "x": (1, "x"), "n": (1, "{unit_name}"), "money": (1, "{cur} per {unit}"),
              "year": (1, "year")}


def manual_drivers(setup) -> sn.StoryDrivers:
    """A neutral starting sheet (status quo, generic units) for when no AI is available."""
    a = setup.assumptions

    def t(v, why):
        return {"value": v, "source": "inferred", "reason": why}
    return sn.StoryDrivers.model_validate({
        "headline": "Status quo, ready to edit", "market": "its market", "unit_name": "units",
        "market_units": t(1e6, "Placeholder market size"), "market_growth": t(a.growth_y2_5, "Status-quo growth"),
        "current_share": t(0.1, "Placeholder"), "target_share": t(0.1, "Placeholder: same share"),
        "share_year": t(5, "Placeholder"), "price_per_unit": t(a.revenue / 1e5, "Revenue / units today"),
        "price_growth": t(0.0, "Placeholder"), "target_margin": t(a.target_margin, "Status quo"),
        "margin_year": t(a.margin_year, "Status quo"), "sales_to_capital": t(a.sales_to_capital_1_5, "Status quo"),
        "red_flags": []})


def story_section(company, setup, profile, scale: float, unit: str, status_quo_value: float):
    """Mode A: the user's story → AI driver sheet → editable → value, units table and story-vs-reality scorecard.
    Returns (story setup, valuation, StoryResult, (scorecard, score)) or None."""
    p = company.profile
    key = f"drivers:{p['symbol']}"
    st.markdown("### ✍️ Tell your story")
    text = st.text_area("Your story", key=f"story:{p['symbol']}", label_visibility="collapsed",
                        placeholder=f"e.g. {p['name']} takes 70% of its home market and 80% of what it sells is "
                                    "electric by 2035")
    with st.expander("Need prompts? Answer any of these (optional)"):
        g1, g2 = st.columns(2)
        hints = {"Market": g1.text_input("Which market, how big, how fast is it growing?"),
                 "Share": g2.text_input("What share does it win, by when?"),
                 "Pricing and mix": g1.text_input("Pricing and product mix (premium, EV, exports...)?"),
                 "Margins and capital": g2.text_input("Margins and investment (plants, stores, R&D)?")}
    full = " ".join([text.strip()] + [f"{k}: {v.strip()}." for k, v in hints.items() if v.strip()]).strip()
    c1, c2 = st.columns([2, 1])
    if c1.button(f"Turn my story into numbers{f' ({llm().name}, ~1 min)' if llm() else ''}", type="primary",
                 disabled=not full or llm() is None):
        with st.spinner("Reading your story: market, share, price per unit, margins, capital…"):
            try:
                st.session_state[key] = sn.draft(company, setup, full, llm(), profile).model_dump()
            except LLMError as exc:
                st.error(f"The AI could not read the story: {exc}")
    if c2.button("Fill the drivers myself"):
        st.session_state[key] = manual_drivers(setup).model_dump()
    if key not in st.session_state:
        return None
    d = sn.StoryDrivers.model_validate(st.session_state[key])

    st.markdown(f"#### {md(d.headline)}")
    st.caption(f"Market: {d.market}. Edit any value and everything recomputes; edited numbers count as yours.")
    cur = p.get("currency") or ""
    rows = []
    for k, label, kind in sn.DRIVER_ROWS:
        x, (mult, u) = getattr(d, k), UNIT_SCALE[kind]
        rows.append({"Driver": label, "Value": round(x.value * mult, 4),
                     "Unit": u.format(unit_name=d.unit_name, cur=cur, unit=d.unit_name.rstrip("s")),
                     "Source": "Your story" if x.source == "stated" else "AI inferred", "Why": x.reason})
    edited = st.data_editor(pd.DataFrame(rows).set_index("Driver"), disabled=["Unit", "Source", "Why"],
                            use_container_width=True, key=f"editor:{p['symbol']}:{d.headline}")
    changes = {}
    for (k, _label, kind), new in zip(sn.DRIVER_ROWS, edited["Value"]):
        x, mult = getattr(d, k), UNIT_SCALE[kind][0]
        if pd.notna(new) and abs(new - round(x.value * mult, 4)) > 1e-9:
            changes[k] = x.model_copy(update={"value": float(new) / mult, "source": "stated",
                                              "reason": "You edited this number"})
    d = d.model_copy(update=changes)
    if changes:
        st.caption("✏️ You changed: " + ", ".join(label for k, label, _ in sn.DRIVER_ROWS if k in changes)
                   + " (now counted as your story).")
    if min(d.current_share.value, d.price_per_unit.value, d.market_units.value) <= 0:
        st.error("Market size, today's share and price per unit must be above zero.")
        return None

    result = sn.build(company, setup, d)
    try:
        v = value(result.assumptions)
    except ValueError as exc:
        st.error(str(exc))
        return None
    card = sn.scorecard(company, setup, result, v)
    score = sn.story_score(card)
    a = result.assumptions
    m = st.columns(4)
    m[0].metric(f"Value per share on your story ({p.get('price_currency') or ''})",
                f"{max(v.value_per_share, 0):,.2f}",
                f"{v.value_per_share / status_quo_value - 1:+.0%} vs status quo" if status_quo_value > 0 else None)
    m[1].metric("Price", f"{a.price:,.2f}" if a.price else "n/a")
    m[2].metric("Value vs price", f"{v.upside:+.0%}" if v.upside is not None else "n/a")
    m[3].metric("Story score", f"{score}/100", help="Starts at 100; each stretch costs 10 and each red flag 25.")
    if v.equity_value < 0:
        st.error("On this story the cash flows are worth less than nothing, so equity is shown as zero.")

    path, t = result.path, v.table
    cols = ["Base", *range(1, 11)]
    st.dataframe(pd.DataFrame({
        f"Market ({d.unit_name})": [f"{x:,.0f}" for x in path["Market units"]],
        "Market share": [f"{x:.1%}" for x in path["Market share"]],
        f"Units sold ({d.unit_name})": [f"{x:,.0f}" for x in path["Units sold"]],
        f"Revenue per unit ({cur})": [f"{x:,.0f}" for x in path["Revenue per unit"]],
        **({f"Revenue from this market ({unit})": [f"{x / scale:,.0f}" for x in path["Revenue from this market"]],
            f"Other revenue, status quo ({unit})": [f"{x / scale:,.0f}" for x in path["Other revenue"]]}
           if d.revenue_share.value < 1 else {}),
        f"Revenue ({unit})": [f"{x / scale:,.0f}" for x in path["Revenue"]],
        "Operating margin": [f"{t.loc['Operating margin', c]:.1%}" for c in cols],
        f"Operating income ({unit})": [f"{t.loc['Operating income (EBIT)', c] / scale:,.0f}" for c in cols],
        f"FCFF ({unit})": [""] + [f"{t.loc['FCFF', c] / scale:,.0f}" for c in cols[1:]],
    }, index=["Today", *[f"Y{y}" for y in range(1, 11)]]).T, use_container_width=True)

    st.markdown(f"**Story vs reality** · score {score}/100")
    st.dataframe(card.set_index("Check"), use_container_width=True)
    if d.mix:
        st.markdown("**Product mix**\n" + "\n".join(
            md(f"- {x.name}: {x.share_of_units:.0%} of {d.unit_name}"
               + (f" (today {x.today:.0%})" if x.today is not None else "") + f". {x.effect}") for x in d.mix))
    if d.red_flags:
        st.markdown("**Red flags the AI noticed**\n" + "\n".join(md(f"- {f}") for f in d.red_flags))
    return Setup(a, setup.wacc, setup.warnings, setup.is_financial), v, result, (card, score)


VERDICT_ICON = {"probable": "🟢", "plausible": "🟡", "possible": "🟠", "out of reach": "🔴"}


def target_section(company, setup, profile, scale: float, unit: str):
    """Mode B: a target ("3x in 3 years") → what has to be true → AI stories calibrated to it and graded.
    Returns (Target, Setup, requirements, routes) for the Excel file, or None."""
    p, a = company.profile, setup.assumptions
    if not a.price:
        return None
    cur = p.get("price_currency") or ""
    st.markdown("### 🎯 Set a target: what has to be true?")
    c1, c2, c3 = st.columns([2, 2, 1])
    kind = c1.radio("Target", ["Multiple of today's price", "Share price", f"Market cap ({unit})"],
                    horizontal=False, label_visibility="collapsed")
    if kind.startswith("Multiple"):
        amount = c2.number_input("Multiple (x)", value=3.0, min_value=0.1, step=0.5)
        target = tg.Target("multiple", amount, 1)
    elif kind == "Share price":
        amount = c2.number_input(f"Target price ({cur})", value=round(a.price * 2, 0), min_value=0.01)
        target = tg.Target("price", amount, 1)
    else:
        amount = c2.number_input(f"Market cap ({unit})", value=round(a.price * a.shares * 2 / scale, 0), min_value=1.0)
        target = tg.Target("market_cap", amount * scale, 1)
    target.years = int(c3.number_input("In years", value=3, min_value=1, max_value=10))
    need = target.value_today(setup)
    sq = value(a).value_per_share
    w = setup.wacc
    m = st.columns(4)
    m[0].metric(f"Target price in {target.years} years", f"{target.price(a):,.2f}")
    m[1].metric("Return that implies", f"{target.annual_return(a):.0%} a year")
    m[2].metric("Value needed today", f"{need:,.2f}", help=f"Target price / (1 + {w.cost_of_equity:.1%} cost of "
                f"equity)^{target.years}: if the market prices it at fair value then, value must grow into the "
                "target at the return shareholders require.")
    m[3].metric("Status-quo value", f"{max(sq, 0):,.2f}", f"{need / sq:.1f}x needed" if sq > 0 else None,
                delta_color="off")
    if need <= sq:
        st.success("The status quo already gets there: no change in the story is needed.")

    reqs = tg.requirements(setup, need)
    fmt = {"growth": "{:.1%}", "target_margin": "{:.1%}", "sales_to_capital": "{:.2f}x", "terminal_roic": "{:.1%}"}
    st.markdown("**What has to be true, one driver at a time** (everything else at the status quo)")
    shown = pd.DataFrame([{
        "Driver": r["Driver"], "Required": fmt[r["key"]].format(r["Required"]) if pd.notna(r["Required"]) else "—",
        "Status quo": fmt[r["key"]].format(r["Status quo"]),
        "In plain terms": (f"revenue {r['Revenue year 5 vs today']:.1f}x today's by year 5"
                           if r["key"] == "growth" and pd.notna(r.get("Revenue year 5 vs today")) else ""),
        "Note": r.get("Note") if isinstance(r.get("Note"), str) else ""} for _, r in reqs.iterrows()])
    st.dataframe(shown.set_index("Driver"), use_container_width=True)

    key = f"routes:{p['symbol']}:{target.label()}"
    if st.button(f"Find stories that get there{f' ({llm().name}, ~2 min)' if llm() else ''}", type="primary",
                 disabled=llm() is None or need <= sq, key="find_routes"):
        with st.spinner("Writing 2-3 routes, then pushing each until it hits the target and grading it…"):
            try:
                routes = tg.draft_routes(company, setup, target, need, reqs, llm(), profile)
                st.session_state[key] = (routes.model_dump(), need)
            except LLMError as exc:
                st.error(f"The AI could not write the stories: {exc}")
    if llm() is None:
        st.caption("Stories need an AI backend; the requirements above work without one.")
    if key not in st.session_state:
        return target, setup, reqs, None
    routes = tg.Routes.model_validate(st.session_state[key][0])
    results = tg.evaluate(company, setup, routes, need)
    st.caption(f"Market: {routes.market}, {routes.market_units:,.0f} {routes.unit_name} a year; share today "
               f"{routes.current_share:.0%}; {md(routes.base_reason)}")
    for i, rr in enumerate(results):
        path, d = rr.result.path, rr.drivers
        lever = tg.LEVER_LABEL[rr.route.lever]
        head = f"{VERDICT_ICON[rr.verdict]} **{md(rr.route.name)}** · 3P: **{rr.verdict.upper()}** · score {rr.score}/100"
        with st.expander(head, expanded=i == 0):
            st.markdown(md(rr.route.pitch))
            if rr.lever_value is None:
                st.error(f"Out of reach: no {lever.lower()} gets this story to {need:,.2f} a share; at its own "
                         f"numbers it is worth {max(rr.valuation.value_per_share, 0):,.2f}.")
            else:
                st.markdown(f"To hit the target, **{lever.lower()}** has to be **{rr.lever_value:.1%}** "
                            f"(the AI's realistic version: {rr.lever_start:.1%}).")
            yrs = [0, target.years, 5, 10]
            st.dataframe(pd.DataFrame({
                f"Units sold ({routes.unit_name})": [f"{path['Units sold'].iloc[y]:,.0f}" for y in yrs],
                "Market share": [f"{path['Market share'].iloc[y]:.1%}" for y in yrs],
                f"Revenue ({unit})": [f"{path['Revenue'].iloc[y] / scale:,.0f}" for y in yrs],
                "Operating margin": [f"{rr.valuation.table.loc['Operating margin', 'Base' if y == 0 else y]:.1%}"
                                     for y in yrs],
            }, index=["Today", f"Year {target.years}", "Year 5", "Year 10"]).T, use_container_width=True)
            st.dataframe(rr.card.set_index("Check"), use_container_width=True)
            st.markdown("**What would break it:** " + md("; ".join(rr.route.risks)))
            if st.button("Open this story in *Tell your story* to edit it", key=f"use_route_{i}"):
                st.session_state[f"drivers:{p['symbol']}"] = d.model_dump()
                st.rerun()
    return target, setup, reqs, results


# ================================================================ game layer
TAG_ICON = {"Bull": "🐂", "Base": "⚖️", "Bear": "🐻", "Other": "📝"}


def celebrate() -> None:
    """The sidebar leaderboard is drawn before the submit button runs, so rerun to show the new entry."""
    st.session_state["celebrate"] = True
    st.rerun()


def sidebar():
    """Player name, challenge picker, how to play and the leaderboard. Returns (player, challenge or None)."""
    with st.sidebar:
        st.header("🎮 Play")
        player = st.text_input("Your name", key="player", placeholder="shown on the leaderboard").strip() or "Guest"
        pick = st.selectbox("Challenge", ["Free play"] + [c.title for c in CHALLENGES], key="challenge")
        ch = next((c for c in CHALLENGES if c.title == pick), None)
        if ch:
            st.info(f"**{ch.title}**\n\n{ch.brief}\n\n💡 {ch.hint}")
        with st.expander("How to play", expanded=ch is None):
            st.markdown("1. **Pick** a company, a fictional one, or a challenge.\n"
                        "2. **See** what it is worth if nothing changes, and the story today's price tells.\n"
                        "3. **Tell your story** (or set a target and let the AI find stories).\n"
                        "4. **Check** the story-vs-reality scorecard: ✅ OK, ⚠️ stretch, 🚩 red flag.\n"
                        "5. **Save** bull, base and bear scenarios and compare them.\n"
                        "6. **Score:** points = boldness × plausibility². Big moves every number can defend win.")
        st.markdown(f"**🏆 Leaderboard** · {ch.title if ch else 'all challenges'}")
        rows = store.leaderboard(ch.id if ch else None)
        if rows:
            st.dataframe(pd.DataFrame(rows).rename(columns=str.capitalize), hide_index=True,
                         use_container_width=True)
        else:
            st.caption("No entries yet: be the first.")
    return player, ch


def save_form(player: str, company, label: str, fields: dict, key: str) -> None:
    with st.form(key, clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 1, 1])
        name = c1.text_input("Scenario name", placeholder=label)
        tag = c2.selectbox("Case", list(TAG_ICON))
        if c3.form_submit_button("💾 Save scenario"):
            p = company.profile
            store.save_scenario(player=player, symbol=p["symbol"], company=p["name"], name=name or label, tag=tag,
                                currency=p.get("price_currency"), **fields)
            st.toast(f"Saved '{name or label}' as {tag}.")


def game_panel(company, setup, mode_a, sq_value: float, player: str, ch) -> None:
    """Points for the current story, the challenge check, saving scenarios and comparing them."""
    p, a0 = company.profile, setup.assumptions
    st.markdown("### 🎮 Score it, save it, compare it")
    if mode_a:
        story_setup, v, result, (card, score) = mode_a
        verdict = tg.verdict(card, True)
        bold, pts = scoring.boldness(v.value_per_share, sq_value), scoring.points(v.value_per_share, sq_value, score)
        c1, c2, c3 = st.columns(3)
        c1.progress(bold, text=f"Boldness {bold:.0%} (vs status quo)")
        c2.progress(score / 100, text=f"Plausibility {score}/100 · 3P: {verdict}")
        c3.metric("Points", f"{pts:,}", help="1000 × boldness × plausibility². A 3x move (or a fall to a third) "
                                            "is fully bold; each stretch or red flag costs plausibility.")
        if ch and ch.symbol:
            if ch.symbol != p["symbol"]:
                st.caption(f"This company is not part of the challenge '{ch.title}' (that is {ch.query}).")
            else:
                ok, msg = ch.check(v.value_per_share, verdict, a0.price)
                (st.success if ok else st.warning)(msg)
                if ok and st.button(f"🏆 Submit to the leaderboard as {player} "
                                    f"({scoring.challenge_points(score):,} points)", type="primary"):
                    store.submit(player, ch.id, scoring.challenge_points(score), v.value_per_share, score, verdict,
                                 result.drivers.headline)
                    celebrate()
        path, sa = result.path, story_setup.assumptions
        save_form(player, company, result.drivers.headline, dict(
            kind="Your story", value_per_share=v.value_per_share, price=a0.price, status_quo=sq_value,
            growth=(path["Revenue"].iloc[5] / path["Revenue"].iloc[0]) ** 0.2 - 1, target_margin=sa.target_margin,
            sales_to_capital=sa.sales_to_capital_1_5, cost_of_capital=sa.cost_of_capital,
            share_y10=path["Market share"].iloc[10], units_y10=path["Units sold"].iloc[10],
            unit_name=result.drivers.unit_name, score=score, verdict=verdict, points=pts,
            headline=result.drivers.headline, drivers=result.drivers.model_dump()), "save_story")
    else:
        st.caption("Tell a story above (or fill the drivers yourself) to score it and save it.")
    if st.button("💾 Save the status quo as a scenario"):
        store.save_scenario(player=player, symbol=p["symbol"], company=p["name"], name="Status quo", tag="Base",
                            kind="Status quo", currency=p.get("price_currency"), value_per_share=sq_value,
                            price=a0.price, status_quo=sq_value, growth=a0.growth_y2_5, target_margin=a0.target_margin,
                            sales_to_capital=a0.sales_to_capital_1_5, cost_of_capital=a0.cost_of_capital)
        st.toast("Saved the status quo.")
    scenarios_section(company, player)


def scenarios_section(company, player: str) -> None:
    p = company.profile
    saved = store.scenarios(p["symbol"], player)
    st.markdown(f"#### 📊 {player}'s scenarios for {p['name']}")
    if not saved:
        st.caption("No saved scenarios yet. Save a bull, a base and a bear case to compare them side by side.")
        return
    order = {"Bull": 0, "Base": 1, "Bear": 2, "Other": 3}
    saved.sort(key=lambda s: (order.get(s["tag"], 3), -(s["value_per_share"] or 0)))

    def f(x, spec):
        return "" if x is None else spec.format(x)

    def short(s):
        name = s["name"] if len(s["name"]) <= 26 else s["name"][:25] + "…"
        return f"{TAG_ICON.get(s['tag'], '')} {name}"
    cols = {f"{short(s)} (#{s['id']})": {
        "Kind": s["kind"], "Value per share": f(max(s["value_per_share"], 0), "{:,.2f}"),
        "Vs price": f(s["value_per_share"] / s["price"] - 1 if s["price"] else None, "{:+.0%}"),
        "Revenue growth, years 1-5": f(s["growth"], "{:.1%}"), "Target margin": f(s["target_margin"], "{:.1%}"),
        "Sales-to-capital": f(s["sales_to_capital"], "{:.2f}x"), "Cost of capital": f(s["cost_of_capital"], "{:.2%}"),
        "Market share, year 10": f(s["share_y10"], "{:.0%}"),
        "Units sold, year 10": f(s["units_y10"], "{:,.0f}") + (f" {s['unit_name']}" if s["unit_name"] else ""),
        "Story score": f(s["score"], "{}/100"), "3P": s["verdict"] or "", "Points": f(s["points"], "{:,}"),
    } for s in saved}
    st.dataframe(pd.DataFrame(cols), use_container_width=True)
    price = saved[0]["price"]
    chart = pd.DataFrame({"Value per share": [max(s["value_per_share"], 0) for s in saved]},
                         index=[f"{short(s)} (#{s['id']})" for s in saved])
    if price:
        chart["Today's price"] = price
    st.bar_chart(chart, stack=False, height=260)
    pick = st.selectbox("Saved scenario", saved, format_func=lambda s: f"#{s['id']} {s['name']}",
                        label_visibility="collapsed")
    c1, c2 = st.columns(2)
    if pick["drivers"] and c1.button("Open in Tell your story"):
        st.session_state[f"drivers:{p['symbol']}"] = pick["drivers"]
        st.rerun()
    if c2.button("🗑 Delete this scenario"):
        store.delete_scenario(pick["id"])
        st.rerun()


def fictional_challenge(spec, company, valuation, player: str, ch) -> None:
    if not ch or ch.symbol or ch.query is not None or valuation is None:
        return
    st.markdown(f"### 🎮 Challenge: {ch.title}")
    margin = damodaran.benchmarks(spec.damodaran_industry, company.profile["region"])["operating_margin"]
    card = fictional_card(spec, margin)
    score = sn.story_score(card)
    verdict = tg.verdict(card, True)
    st.dataframe(card.set_index("Check"), use_container_width=True)
    if spec.currency.upper() != "INR":
        st.warning("This challenge is in rupees: set the currency to INR.")
        return
    equity = valuation.equity_value
    hit, believable = equity >= FICTIONAL_TARGET, RANK[verdict] >= RANK[ch.needs]
    if hit and believable:
        st.success(f"Challenge met: equity worth ₹{equity / 1e7:,.0f} crore with a {verdict} story.")
        if st.button(f"🏆 Submit as {player} ({scoring.challenge_points(score):,} points)", type="primary"):
            store.submit(player, ch.id, scoring.challenge_points(score), equity / 1e7, score, verdict, spec.name)
            celebrate()
    else:
        st.warning("Not yet: " + " and ".join(
            ([f"equity is ₹{max(equity, 0) / 1e7:,.0f} crore, below ₹1,000 crore"] if not hit else [])
            + ([f"the story is only {verdict} (no red flags allowed)"] if not believable else [])) + ".")


def download(company, setup, valuation, implied, profile, story, name: str, mode_a=None, mode_b=None) -> None:
    your_story, card, score = None, None, None
    if mode_a:  # the file follows your story: its DCF runs on the units x price path
        setup, valuation, your_story, (card, score) = mode_a
        implied = None
    st.download_button("⬇ Download Excel (live formulas, DCF and story)",
                       data=build(company, setup if valuation else None, valuation, implied, profile, story,
                                  your_story, card, score, mode_b),
                       file_name=f"{name}_valuation.xlsx", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ================================================================ page
st.title("Story ⇄ Numbers")
st.caption("Damodaran-style valuation game. Pick a company; every valuation is a story told in numbers.")
player, challenge = sidebar()
if st.session_state.pop("celebrate", False):
    st.balloons()
    st.toast("🏆 On the leaderboard!")
mode = st.radio("What do you want to value?", ["A listed company", "A fictional company"], horizontal=True,
                label_visibility="collapsed",
                index=1 if challenge and challenge.symbol is None and challenge.query is None else 0)

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
    fictional_challenge(spec, company, valuation, player, challenge)
    download(company, setup, valuation, implied, None, None, "fictional")
    st.caption("Educational tool, not investment advice.")
    st.stop()

query = st.text_input("Company name or ticker", placeholder="e.g. Maruti Suzuki, Tata Motors, Apple",
                      value=challenge.query if challenge and challenge.query else "")
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
mode_a = mode_b = None
if valuation is not None:
    mode_a = story_section(company, setup, profile, scale, unit, valuation.value_per_share)
    game_panel(company, setup, mode_a, valuation.value_per_share, player, challenge)
    mode_b = target_section(company, setup, profile, scale, unit)
download(company, setup, valuation, implied, profile, story, p["symbol"], mode_a, mode_b)
st.caption("Educational tool, not investment advice.")
