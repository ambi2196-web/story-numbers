"""Damodaran-style ratios, defined once and used twice: evaluated in Python, and turned into live Excel formulas.

Expression syntax:
  {field}        this year's value of a financials field or an earlier ratio
  {field@prev}   last year's value
  N(x)           treat a missing value as 0 (e.g. minority interest); anything else missing -> result is blank
"""
import math
import re

import pandas as pd

# key, label, expression, format ("pct" | "money" | "x")
RATIOS = [
    ("revenue_growth", "Revenue growth", "{revenue} / {revenue@prev} - 1", "pct"),
    ("gross_margin", "Gross margin", "{gross_profit} / {revenue}", "pct"),
    ("operating_margin", "Operating margin (EBIT / revenue)", "{operating_income} / {revenue}", "pct"),
    ("net_margin", "Net margin", "{net_income} / {revenue}", "pct"),
    ("effective_tax_rate", "Effective tax rate (tax / pre-tax income)", "{tax} / {pretax_income}", "pct"),
    ("nopat", "NOPAT = EBIT x (1 - tax rate)", "{operating_income} * (1 - {effective_tax_rate})", "money"),
    ("non_cash_working_capital", "Non-cash working capital",
     "({current_assets} - {cash}) - ({current_liabilities} - N({current_debt}))", "money"),
    ("invested_capital", "Invested capital (equity + debt - cash - non-operating investments)",
     "{equity} + {total_debt} + N({minority_interest}) - {cash} - N({financial_investments}) - N({equity_investments})",
     "money"),
    ("sales_to_capital", "Sales-to-capital (revenue / invested capital)", "{revenue} / {invested_capital}", "x"),
    ("roic", "ROIC (NOPAT / start-of-year invested capital)", "{nopat} / {invested_capital@prev}", "pct"),
    ("net_capex", "Net capex (capex - depreciation)", "{capex} - {depreciation}", "money"),
    ("change_in_wc", "Change in non-cash working capital",
     "{non_cash_working_capital} - {non_cash_working_capital@prev}", "money"),
    ("reinvestment", "Reinvestment (net capex + acquisitions + change in WC)",
     "{net_capex} + N({acquisitions}) + {change_in_wc}", "money"),
    ("reinvestment_rate", "Reinvestment rate (reinvestment / NOPAT)", "{reinvestment} / {nopat}", "pct"),
    ("fcff", "Free cash flow to the firm (NOPAT - reinvestment)", "{nopat} - {reinvestment}", "money"),
    ("debt_to_capital", "Debt / (debt + equity), book", "{total_debt} / ({total_debt} + {equity})", "pct"),
    ("interest_coverage", "Interest coverage (EBIT / interest)", "{operating_income} / {interest_expense}", "x"),
]
RATIO_LABELS = {key: label for key, label, _, _ in RATIOS}
RATIO_FORMATS = {key: fmt for key, _, _, fmt in RATIOS}

_TOKEN = re.compile(r"\{(\w+)(@prev)?\}")


def _N(x: float) -> float:
    return 0.0 if x is None or (isinstance(x, float) and math.isnan(x)) else x


def compute(financials: pd.DataFrame) -> pd.DataFrame:
    """Ratios for every year (rows = ratio keys, columns = the financials' years)."""
    years = list(financials.columns)
    values = {y: {k: float(v) for k, v in financials[y].items()} for y in years}
    nan = float("nan")
    for key, _, expr, _ in RATIOS:
        py_expr = _TOKEN.sub(lambda m: f'{"P" if m.group(2) else "V"}["{m.group(1)}"]', expr)
        for i, y in enumerate(years):
            if "@prev" in expr and i == 0:
                values[y][key] = nan
                continue
            scope = {"V": values[y], "P": values[years[i - 1]] if i else {}, "N": _N}
            try:
                values[y][key] = float(eval(py_expr, {"__builtins__": {}}, scope))  # expressions are our own constants
            except (ZeroDivisionError, KeyError):
                values[y][key] = nan
    return pd.DataFrame({y: {k: values[y][k] for k, *_ in RATIOS} for y in years})


def excel_formula(expr: str, ref) -> str | None:
    """Turn an expression into an Excel formula. `ref(name, prev)` returns a cell address or None if unavailable.

    Missing required inputs give a blank cell (not a misleading zero), matching compute()'s NaN behaviour.
    """
    required, missing = [], False

    def sub(m: re.Match, inside_n: bool) -> str:
        nonlocal missing
        cell = ref(m.group(1), bool(m.group(2)))
        if cell is None:
            missing = True
            return "0"
        if not inside_n:
            required.append(cell)
        return cell

    # References wrapped in N(...) may be blank; all others must be numbers.
    out = re.sub(r"N\((\{\w+(?:@prev)?\})\)", lambda m: "N(" + _TOKEN.sub(lambda t: sub(t, True), m.group(1)) + ")", expr)
    out = _TOKEN.sub(lambda m: sub(m, False), out)
    if missing:
        return None
    guard = f'COUNT({",".join(dict.fromkeys(required))})<{len(dict.fromkeys(required))}'
    return f'=IF({guard},"",IFERROR({out},""))'
