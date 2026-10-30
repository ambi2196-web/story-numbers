"""The DCF sheet: the same FCFF model as app.engine.dcf, written as live Excel formulas.

Change any blue assumption (growth, margin, beta...) and the value per share recalculates, exactly as the
Python engine would. Tested against the engine by recalculating in Excel.
"""
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook

from app.engine.dcf import YEARS, Valuation
from app.engine.defaults import Setup
from app.excel.workbook_style import FORMATS, INPUT_BLUE, header, title, widths

PCT, X, MONEY = "0.00%", '0.00"x"', FORMATS["money"]
BASE_COL = 2  # B = base year, C..L = years 1-10, M = terminal year
COL = {t: get_column_letter(BASE_COL + t) for t in range(YEARS + 2)}  # 0 = base, 11 = terminal


def add_dcf_sheet(wb: Workbook, setup: Setup, v: Valuation, scale: float, unit: str,
                  implied: dict[str, float | None] | None = None, growth_refs: list[str] | None = None) -> dict:
    """Returns the input cell addresses, so a story sheet can link to them. `growth_refs`: ten formulas (one per
    year) that replace the growth assumptions, e.g. links to the story sheet's units x price path."""
    a, w = v.assumptions, setup.wacc
    ws = wb.create_sheet("DCF", 1)
    title(ws, "Discounted cash flow (FCFF): live formulas",
          f"Damodaran-style 10-year DCF. Money in {unit}. Blue cells are inputs: change them and everything updates.")

    # ---- cost of capital, built up in US$ and converted with the inflation differential
    r = 4
    header(ws, r, ["Cost of capital", "Value", "Note"], first_numeric=2)
    cc_rows = [
        ("rf", "Risk-free rate (US$ Treasury)", w.riskfree_usd, PCT, "Damodaran January update"),
        ("erp", "Equity risk premium (country)", w.equity_risk_premium, PCT, "Mature-market ERP + country risk"),
        ("bu", "Unlevered beta (industry)", w.unlevered_beta, "0.00", "Damodaran, corrected for cash"),
        ("de", "Debt / equity (market)", w.debt_weight / (1 - w.debt_weight) if w.debt_weight < 1 else 0, PCT,
         "Total debt / market cap"),
        ("t", "Marginal tax rate", w.marginal_tax_rate, PCT, "Damodaran country table"),
        ("bl", "Levered beta", "={bu}*(1+(1-{t})*{de})", "0.00", "Unlevered beta x (1 + (1 - t) x D/E)"),
        ("ke", "Cost of equity (US$)", "={rf}+{bl}*{erp}", PCT, ""),
        ("spread", "Default spread (country + company)", w.default_spread, PCT,
         f"Synthetic rating {w.rating} from interest coverage"),
        ("kd", "Pre-tax cost of debt (US$)", "={rf}+{spread}", PCT, ""),
        ("wd", "Debt / capital", "={de}/(1+{de})", PCT, ""),
        ("wacc_usd", "Cost of capital (US$)", "=(1-{wd})*{ke}+{wd}*{kd}*(1-{t})", PCT, ""),
        ("term_usd", "Terminal cost of capital (US$)", "=MIN({wacc_usd},(1-{wd})*({rf}+{erp})+{wd}*{kd}*(1-{t}))",
         PCT, "Beta moves to 1, never above today's rate"),
        ("il", f"Expected inflation ({w.currency})", w.inflation_local, PCT, "Damodaran"),
        ("iu", "Expected inflation (US$)", w.inflation_usd, PCT, "Damodaran"),
        ("rf_local", f"Risk-free rate ({w.currency})", "=(1+{rf})*(1+{il})/(1+{iu})-1", PCT, "Inflation-adjusted"),
        ("wacc_local", f"Cost of capital ({w.currency})", "=(1+{wacc_usd})*(1+{il})/(1+{iu})-1", PCT, ""),
        ("term_local", f"Terminal cost of capital ({w.currency})", "=(1+{term_usd})*(1+{il})/(1+{iu})-1", PCT, ""),
    ]
    cells = {}
    for i, (key, *_rest) in enumerate(cc_rows, start=r + 1):
        cells[key] = f"$B${i}"
    for i, (key, label, val, fmt, note) in enumerate(cc_rows, start=r + 1):
        ws.cell(i, 1, label)
        cell = ws.cell(i, 2, val.format(**cells) if isinstance(val, str) else val)
        cell.number_format = fmt
        if not isinstance(val, str):
            cell.font = Font(color=INPUT_BLUE)
        ws.cell(i, 3, note).font = Font(italic=True, color="808080")

    # ---- the story's assumptions
    r = r + len(cc_rows) + 2
    header(ws, r, ["Assumptions", "Value", "Source"], first_numeric=2)
    linked = {"cost_of_capital": (w.cost_of_capital, cells["wacc_local"]),
              "terminal_cost_of_capital": (w.terminal_cost_of_capital, cells["term_local"]),
              "terminal_growth": (w.riskfree_local, cells["rf_local"])}
    inputs = [
        ("revenue", "Base-year revenue", a.revenue / scale, MONEY),
        ("operating_income", "Base-year operating income (EBIT)", a.operating_income / scale, MONEY),
        ("growth_y1", "Revenue growth, year 1", a.growth_y1, PCT),
        ("growth_y2_5", "Revenue growth, years 2-5 (fades to terminal growth by year 10)", a.growth_y2_5, PCT),
        ("target_margin", "Target operating margin", a.target_margin, PCT),
        ("margin_year", "Year the target margin is reached", a.margin_year, "0"),
        ("sales_to_capital_1_5", "Sales-to-capital, years 1-5", a.sales_to_capital_1_5, X),
        ("sales_to_capital_6_10", "Sales-to-capital, years 6-10", a.sales_to_capital_6_10, X),
        ("effective_tax_rate", "Effective tax rate (years 1-5, moves to marginal by year 10)", a.effective_tax_rate,
         PCT),
        ("marginal_tax_rate", "Marginal tax rate", a.marginal_tax_rate, PCT),
        ("cost_of_capital", "Cost of capital, years 1-5", a.cost_of_capital, PCT),
        ("terminal_cost_of_capital", "Cost of capital after year 10", a.terminal_cost_of_capital, PCT),
        ("terminal_growth", "Growth rate after year 10", a.terminal_growth, PCT),
        ("terminal_roic", "Return on capital after year 10", a.terminal_roic, PCT),
        ("tax_loss_carryforward", "Tax-loss carryforward", a.tax_loss_carryforward / scale, MONEY),
        ("failure_probability", "Probability of failure", a.failure_probability, PCT),
        ("distress_proceeds", "Proceeds if it fails (% of going-concern value)", a.distress_proceeds, PCT),
        ("cash", "Cash & short-term investments", a.cash / scale, MONEY),
        ("non_operating_assets", "Non-operating assets (investments, cross holdings)", a.non_operating_assets / scale,
         MONEY),
        ("debt", "Debt (incl. leases)", a.debt / scale, MONEY),
        ("minority_interest", "Minority interest", a.minority_interest / scale, MONEY),
        ("shares", "Shares outstanding (millions)", a.shares / 1e6, "#,##0.00"),
        ("price", "Current share price", a.price, "#,##0.00"),
    ]
    A = {}
    for i, (key, *_rest) in enumerate(inputs, start=r + 1):
        A[key] = f"$B${i}"
    for i, (key, label, val, fmt) in enumerate(inputs, start=r + 1):
        ws.cell(i, 1, label)
        if key in linked and abs(linked[key][0] - val) < 1e-12:
            cell = ws.cell(i, 2, f"={linked[key][1]}")  # follows the cost-of-capital build-up above
        elif key == "terminal_roic" and val is None:
            cell = ws.cell(i, 2, f"={A['terminal_cost_of_capital']}")
        else:
            cell = ws.cell(i, 2, val)
            cell.font = Font(color=INPUT_BLUE)
        cell.number_format = fmt
        ws.cell(i, 3, a.sources.get(key, "") or ("" if key not in linked else "Cost of capital build-up above")
                ).font = Font(italic=True, color="808080")

    # ---- ten-year projection
    r = r + len(inputs) + 2
    header(ws, r, ["Projection", "Base", *[str(t) for t in range(1, YEARS + 1)], "Terminal"], first_numeric=2)
    year_row = r + 1
    ws.cell(year_row, 1, "Year").font = Font(color="808080")
    for t in range(1, YEARS + 1):
        ws.cell(year_row, BASE_COL + t, t).font = Font(color="808080")
    lines = ["growth", "revenue", "margin", "ebit", "tax_rate", "nol", "taxes", "nopat", "s2c", "reinvestment",
             "fcff", "wacc", "discount", "pv"]
    R = {name: year_row + 1 + i for i, name in enumerate(lines)}
    labels = {"growth": ("Revenue growth", PCT), "revenue": ("Revenue", MONEY),
              "margin": ("Operating margin", PCT), "ebit": ("Operating income (EBIT)", MONEY),
              "tax_rate": ("Tax rate", PCT), "nol": ("Tax-loss carryforward (end of year)", MONEY),
              "taxes": ("Taxes", MONEY), "nopat": ("After-tax operating income", MONEY),
              "s2c": ("Sales-to-capital", X), "reinvestment": ("Reinvestment", MONEY),
              "fcff": ("Free cash flow to firm (FCFF)", MONEY), "wacc": ("Cost of capital", PCT),
              "discount": ("Cumulative discount factor", "0.0000"), "pv": ("Present value of FCFF", MONEY)}
    base_margin = f"{COL[0]}{R['margin']}"

    def put(name: str, t: int, formula: str) -> None:
        ws.cell(R[name], BASE_COL + t, formula).number_format = labels[name][1]

    for name, (label, _) in labels.items():
        ws.cell(R[name], 1, label).font = Font(bold=name in ("fcff", "pv"))
    put("revenue", 0, f"={A['revenue']}")
    put("ebit", 0, f"={A['operating_income']}")
    put("margin", 0, f"=IFERROR({A['operating_income']}/{A['revenue']},0)")
    put("tax_rate", 0, f"={A['effective_tax_rate']}")
    put("nol", 0, f"={A['tax_loss_carryforward']}")
    for t in range(1, YEARS + 1):
        c, p, yr = COL[t], COL[t - 1], f"{COL[t]}${year_row}"
        g1, g, gt = A["growth_y1"], A["growth_y2_5"], A["terminal_growth"]
        if growth_refs:
            put("growth", t, growth_refs[t - 1])
        elif a.growth_path is not None:
            put("growth", t, float(a.growth_path[t - 1]))
            ws.cell(R["growth"], BASE_COL + t).font = Font(color=INPUT_BLUE)
        else:
            put("growth", t, f"=IF({yr}=1,{g1},IF({yr}<=5,{g},{g}-({g}-{gt})*({yr}-5)/5))")
        put("revenue", t, f"={p}{R['revenue']}*(1+{c}{R['growth']})")
        put("margin", t, f"=IF({yr}>=MAX({A['margin_year']},1),{A['target_margin']},"
                         f"{base_margin}+({A['target_margin']}-{base_margin})*{yr}/MAX({A['margin_year']},1))")
        put("ebit", t, f"={c}{R['revenue']}*{c}{R['margin']}")
        eff, mar = A["effective_tax_rate"], A["marginal_tax_rate"]
        put("tax_rate", t, f"=IF({yr}>5,{eff}+({mar}-{eff})*({yr}-5)/5,{eff})")
        ebit, nol_prev = f"{c}{R['ebit']}", f"{p}{R['nol']}"
        put("nol", t, f"=IF({ebit}<0,{nol_prev}-{ebit},{nol_prev}-MIN({nol_prev},{ebit}))")
        put("taxes", t, f"=IF({ebit}<0,0,({ebit}-MIN({nol_prev},{ebit}))*{c}{R['tax_rate']})")
        put("nopat", t, f"={ebit}-{c}{R['taxes']}")
        put("s2c", t, f"=IF({yr}>5,{A['sales_to_capital_6_10']},{A['sales_to_capital_1_5']})")
        put("reinvestment", t, f"=({c}{R['revenue']}-{p}{R['revenue']})/{c}{R['s2c']}")
        put("fcff", t, f"={c}{R['nopat']}-{c}{R['reinvestment']}")
        w1, wt = A["cost_of_capital"], A["terminal_cost_of_capital"]
        put("wacc", t, f"=IF({yr}>5,{w1}+({wt}-{w1})*({yr}-5)/5,{w1})")
        put("discount", t, f"=1/(1+{c}{R['wacc']})" if t == 1 else f"={p}{R['discount']}/(1+{c}{R['wacc']})")
        put("pv", t, f"={c}{R['fcff']}*{c}{R['discount']}")
    T, L = YEARS + 1, COL[YEARS]
    tc = COL[T]
    put("growth", T, f"={A['terminal_growth']}")
    put("revenue", T, f"={L}{R['revenue']}*(1+{A['terminal_growth']})")
    put("margin", T, f"={A['target_margin']}")
    put("ebit", T, f"={tc}{R['revenue']}*{tc}{R['margin']}")
    put("tax_rate", T, f"={A['marginal_tax_rate']}")
    put("nopat", T, f"=IF({tc}{R['ebit']}>0,{tc}{R['ebit']}*(1-{tc}{R['tax_rate']}),{tc}{R['ebit']})")
    put("reinvestment", T, f"=IF({tc}{R['nopat']}>0,{tc}{R['nopat']}*{A['terminal_growth']}/{A['terminal_roic']},0)")
    put("fcff", T, f"={tc}{R['nopat']}-{tc}{R['reinvestment']}")
    put("wacc", T, f"={A['terminal_cost_of_capital']}")

    # ---- from operating assets to value per share
    r = R["pv"] + 2
    header(ws, r, ["Valuation", "Value", "Note"], first_numeric=2)
    vrows = [
        ("pv_fcff", "PV of FCFF, years 1-10", f"=SUM({COL[1]}{R['pv']}:{L}{R['pv']})", MONEY, ""),
        ("tv", "Terminal value (at year 10)",
         f"={tc}{R['fcff']}/({A['terminal_cost_of_capital']}-{A['terminal_growth']})", MONEY,
         "Terminal FCFF / (cost of capital - growth)"),
        ("pv_tv", "PV of terminal value", f"={{tv}}*{L}{R['discount']}", MONEY, ""),
        ("gc", "Value of operating assets (going concern)", "={pv_fcff}+{pv_tv}", MONEY, ""),
        ("op", "Adjusted for probability of failure",
         f"={{gc}}*(1-{A['failure_probability']})+{{gc}}*{A['distress_proceeds']}*{A['failure_probability']}", MONEY,
         ""),
        ("less_debt", "- Debt", f"=-{A['debt']}", MONEY, ""),
        ("less_mi", "- Minority interest", f"=-{A['minority_interest']}", MONEY, ""),
        ("plus_cash", "+ Cash", f"={A['cash']}", MONEY, ""),
        ("plus_nonop", "+ Non-operating assets", f"={A['non_operating_assets']}", MONEY, ""),
        ("equity", "Value of equity", "={op}+{less_debt}+{less_mi}+{plus_cash}+{plus_nonop}", MONEY, ""),
        ("vps", "Value per share", f"={{equity}}*{scale:g}/({A['shares']}*1e6)", "#,##0.00", ""),
        ("price", "Current share price", f'=IF(ISNUMBER({A["price"]}),{A["price"]},"")', "#,##0.00", ""),
        ("upside", "Value / price - 1", f'=IF(ISNUMBER({A["price"]}),{{vps}}/{A["price"]}-1,"")', "0.0%",
         "Positive = the story says the stock is cheap"),
    ]
    V = {key: f"$B${i}" for i, (key, *_r) in enumerate(vrows, start=r + 1)}
    for i, (key, label, formula, fmt, note) in enumerate(vrows, start=r + 1):
        ws.cell(i, 1, label).font = Font(bold=key in ("equity", "vps"))
        ws.cell(i, 2, formula.format(**V)).number_format = fmt
        ws.cell(i, 3, note).font = Font(italic=True, color="808080")

    # ---- reverse DCF results (static: computed by the app's solver)
    r = r + len(vrows) + 2
    if implied:
        header(ws, r, ["What today's price implies", "Value", "Note"], first_numeric=2)
        names = {"growth": ("Revenue growth, years 1-5", PCT), "target_margin": ("Target operating margin", PCT),
                 "sales_to_capital": ("Sales-to-capital", X), "terminal_roic": ("Return on capital after year 10", PCT)}
        for i, (key, x) in enumerate(implied.items(), start=r + 1):
            label, fmt = names[key]
            ws.cell(i, 1, label)
            ws.cell(i, 2, x if x is not None else "not reachable").number_format = fmt
            ws.cell(i, 3, "Solved by the app with the other assumptions unchanged (Excel: Data > What-If > "
                          "Goal Seek)").font = Font(italic=True, color="808080")
        r += len(implied) + 2
    for i, msg in enumerate(setup.warnings, start=r):
        ws.cell(i, 1, f"Note: {msg}").font = Font(italic=True, color="C00000")
    widths(ws, {"A": 58, "B": 14, "C": 13, **{COL[t]: 13 for t in range(2, YEARS + 2)}})
    ws.freeze_panes = "B4"
    return A
