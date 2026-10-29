"""Excel export: the company's 5-year financials with live ratio formulas and Damodaran industry benchmarks.

Sheets: Summary | DCF (when a valuation is passed) | Financials | Ratios (formulas) | Industry Benchmarks |
Raw - Income | Raw - Balance | Raw - Cash Flow
"""
from datetime import date
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from app.data import damodaran
from app.data.collector import LABELS, Company
from app.data.ratios import RATIOS, excel_formula
from app.excel.dcf_sheet import add_dcf_sheet
from app.excel.workbook_style import FORMATS, INPUT_BLUE, header as _header, title as _title, widths as _widths

FIRST_YEAR_COL = 3  # A = key, B = label, C.. = years


def units(currency: str | None) -> tuple[float, str]:
    """Indian companies are shown in ₹ crore (as in their annual reports); everything else in millions."""
    return (1e7, "₹ crore") if currency == "INR" else (1e6, f"{currency or ''} millions".strip())


def _financials_sheet(wb: Workbook, c: Company, scale: float, unit: str) -> dict[str, int]:
    ws = wb.create_sheet("Financials")
    _title(ws, f"{c.profile['name']}: standardised financials", f"{unit}. Blue = sourced data; Source column shows where.")
    years = list(c.financials.columns)
    _header(ws, 4, ["Key", "Line item", *years, "Source"])
    rows = {}
    shares_row = "diluted_shares"
    for i, key in enumerate(c.financials.index, start=5):
        rows[key] = i
        ws.cell(i, 1, key).font = Font(color="808080", size=8)
        ws.cell(i, 2, LABELS.get(key, key) + (" (millions)" if key == shares_row else ""))
        for j, y in enumerate(years):
            v = c.financials.loc[key, y]
            if pd.notna(v):
                cell = ws.cell(i, FIRST_YEAR_COL + j, float(v) / (1e6 if key == shares_row else scale))
                cell.number_format, cell.font = FORMATS["money"], Font(color=INPUT_BLUE)
        ws.cell(i, FIRST_YEAR_COL + len(years), c.profile.get("field_sources", {}).get(key, "")).font = Font(
            color="808080", italic=True)
    _widths(ws, {"A": 10, "B": 38, get_column_letter(FIRST_YEAR_COL + len(years)): 16})
    ws.freeze_panes = "C5"
    return rows


def _ratios_sheet(wb: Workbook, c: Company, fin_rows: dict[str, int], unit: str) -> dict[str, int]:
    ws = wb.create_sheet("Ratios")
    _title(ws, "Ratios: live formulas", f"Change any number on the Financials sheet and these update. Money in {unit}.")
    years = list(c.financials.columns)
    _header(ws, 4, ["Key", "Ratio", *years, "Average"])
    rows = {key: i for i, (key, *_) in enumerate(RATIOS, start=5)}

    def ref_for(col_idx: int):
        def ref(name: str, prev: bool) -> str | None:
            col = col_idx - 1 if prev else col_idx
            if col < FIRST_YEAR_COL:
                return None
            letter = get_column_letter(col)
            if name in rows:
                return f"{letter}{rows[name]}"
            return f"Financials!{letter}{fin_rows[name]}" if name in fin_rows else None
        return ref

    for key, label, expr, fmt in RATIOS:
        r = rows[key]
        ws.cell(r, 1, key).font = Font(color="808080", size=8)
        ws.cell(r, 2, label)
        for j in range(len(years)):
            col = FIRST_YEAR_COL + j
            formula = excel_formula(expr, ref_for(col))
            if formula:
                ws.cell(r, col, formula).number_format = FORMATS[fmt]
        first, last = get_column_letter(FIRST_YEAR_COL), get_column_letter(FIRST_YEAR_COL + len(years) - 1)
        avg = ws.cell(r, FIRST_YEAR_COL + len(years), f'=IFERROR(AVERAGE({first}{r}:{last}{r}),"")')
        avg.number_format, avg.font = FORMATS[fmt], Font(bold=True)
    _widths(ws, {"A": 10, "B": 62})
    ws.freeze_panes = "C5"
    return rows


def _benchmarks_sheet(wb: Workbook, c: Company) -> dict[str, str]:
    """Returns cell addresses of the key regional benchmarks, for the Summary sheet."""
    ws = wb.create_sheet("Industry Benchmarks")
    industry, region = c.profile["damodaran_industry"], c.profile["region"]
    _title(ws, f"Damodaran industry averages: {industry}",
           "Source: Aswath Damodaran, NYU Stern (pages.stern.nyu.edu/~adamodar), January data update.")
    regions = list(dict.fromkeys([region, "Global"]))
    _header(ws, 4, ["Metric", *[f"{r}" for r in regions]])
    metrics = [("firms", "Number of firms", "0"), ("operating_margin", "Pre-tax operating margin", "0.0%"),
               ("gross_margin", "Gross margin", "0.0%"), ("net_margin", "Net margin", "0.0%"),
               ("sales_to_capital", "Sales-to-capital", '0.00"x"'), ("beta", "Beta", "0.00"),
               ("cost_of_equity", "Cost of equity", "0.0%"), ("cost_of_capital", "Cost of capital", "0.0%"),
               ("debt_to_capital", "Debt / capital (market)", "0.0%"),
               ("effective_tax_rate", "Effective tax rate (money-making firms)", "0.0%")]
    data = {r: damodaran.benchmarks(industry, r) for r in regions}
    cells = {}
    for i, (key, label, fmt) in enumerate(metrics, start=5):
        ws.cell(i, 1, label)
        for j, r in enumerate(regions, start=2):
            value = data[r][key]
            cell = ws.cell(i, j, None if pd.isna(value) else value)  # Damodaran leaves some groups blank
            cell.number_format = fmt
        cells[key] = f"'Industry Benchmarks'!B{i}"
    row = len(metrics) + 7
    if c.profile.get("country"):
        try:
            risk = damodaran.country_risk(c.profile["country"])
            _header(ws, row, ["Country risk", c.profile["country"]])
            for i, (key, label, fmt) in enumerate([
                    ("rating", "Moody's sovereign rating", "@"), ("default_spread", "Default spread", "0.00%"),
                    ("equity_risk_premium", "Total equity risk premium", "0.00%"),
                    ("country_risk_premium", "Country risk premium", "0.00%"),
                    ("tax_rate", "Marginal corporate tax rate", "0.0%")], start=row + 1):
                ws.cell(i, 1, label)
                ws.cell(i, 2, risk[key]).number_format = fmt
                cells[key] = f"'Industry Benchmarks'!B{i}"
        except KeyError:
            pass
    _widths(ws, {"A": 42, "B": 16, "C": 16})
    return cells


def _summary_sheet(wb: Workbook, c: Company, ratio_rows: dict[str, int], fin_rows: dict[str, int],
                   bench: dict[str, str], unit: str) -> None:
    ws = wb.active
    ws.title = "Summary"
    p = c.profile
    _title(ws, p["name"], f"{p['symbol']} · {p.get('exchange') or ''} · {p.get('country') or ''} · "
                          f"Generated {date.today():%d %b %Y}")
    years = list(c.financials.columns)
    first, last = get_column_letter(FIRST_YEAR_COL), get_column_letter(FIRST_YEAR_COL + len(years) - 1)
    n = len(years)

    def link(key: str) -> str | None:
        """Live link to a benchmark cell that stays blank (not 0) when Damodaran has no value."""
        ref = bench.get(key)
        return f'=IF(ISNUMBER({ref}),{ref},"")' if ref else None

    facts = [("Industry (Yahoo)", p.get("industry")), ("Damodaran industry group", p.get("damodaran_industry")),
             ("Benchmark region", p.get("region")), ("Reporting currency", p.get("currency")),
             ("Units", unit), ("Share price", p.get("price")), ("Shares outstanding (millions)",
             (p.get("shares_outstanding") or 0) / 1e6 or None),
             (f"Market cap ({unit})", (p.get("market_cap") or 0) / units(p.get("currency"))[0] or None),
             ("Beta (Yahoo)", p.get("beta")), ("Years covered", f"{years[0]} to {years[-1]}"),
             ("Data sources", p.get("source"))]
    _header(ws, 4, ["Company facts", ""])
    for i, (label, value) in enumerate(facts, start=5):
        ws.cell(i, 1, label)
        cell = ws.cell(i, 2, value)
        if isinstance(value, float):
            cell.number_format = "#,##0.00" if "price" in label.lower() or "Beta" in label else "#,##0"

    row = len(facts) + 6
    _header(ws, row, ["Key metrics (live)", "Company", "Industry", "Note"])
    metrics = [
        ("Latest revenue", f"=Financials!{last}{fin_rows['revenue']}", None, FORMATS["money"], unit),
        (f"Revenue CAGR ({years[0]}-{years[-1]})",
         f'=IFERROR((Financials!{last}{fin_rows["revenue"]}/Financials!{first}{fin_rows["revenue"]})^(1/{n - 1})-1,"")',
         None, "0.0%", ""),
        ("Operating margin (avg)", f"=Ratios!{get_column_letter(FIRST_YEAR_COL + n)}{ratio_rows['operating_margin']}",
         link("operating_margin"), "0.0%", "Damodaran: pre-tax lease-adjusted margin"),
        ("Operating margin (latest)", f"=Ratios!{last}{ratio_rows['operating_margin']}",
         link("operating_margin"), "0.0%", ""),
        ("Sales-to-capital (latest)", f"=Ratios!{last}{ratio_rows['sales_to_capital']}",
         link("sales_to_capital"), '0.00"x"', "Higher = less capital needed to grow"),
        ("ROIC (latest)", f"=Ratios!{last}{ratio_rows['roic']}", None, "0.0%", ""),
        ("Effective tax rate (avg)",
         f"=Ratios!{get_column_letter(FIRST_YEAR_COL + n)}{ratio_rows['effective_tax_rate']}",
         link("effective_tax_rate"), "0.0%", ""),
        ("Cost of capital (industry)", None, link("cost_of_capital"), "0.0%",
         "Local-currency where Damodaran provides it"),
        ("Equity risk premium (country)", None, link("equity_risk_premium"), "0.00%", ""),
    ]
    for i, (label, comp, ind, fmt, note) in enumerate(metrics, start=row + 1):
        ws.cell(i, 1, label)
        for col, value in ((2, comp), (3, ind)):
            if value:
                ws.cell(i, col, value).number_format = fmt
        ws.cell(i, 4, note).font = Font(italic=True, color="808080")

    row = row + len(metrics) + 2
    _header(ws, row, ["What the company does", ""])
    ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 1, end_column=4)
    cell = ws.cell(row + 1, 1, p.get("summary") or "")
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[row + 1].height = 150
    ws.cell(row + 3, 1, "Educational tool, not investment advice.").font = Font(italic=True, color="808080")
    _widths(ws, {"A": 34, "B": 30, "C": 16, "D": 44})


def _raw_sheet(wb: Workbook, name: str, df: pd.DataFrame, scale: float, unit: str) -> None:
    ws = wb.create_sheet(name)
    _title(ws, f"{name.replace('Raw - ', '')} statement as reported by Yahoo Finance",
           f"{unit}; share counts in millions; EPS and tax rates as reported")
    _header(ws, 4, ["Line item", *df.columns])
    for i, (label, values) in enumerate(df.iterrows(), start=5):
        ws.cell(i, 1, str(label))
        for j, v in enumerate(values, start=2):
            if pd.notna(v):
                # Per-share values and tax rates are shown as reported; share counts in millions.
                unscaled = any(s in str(label) for s in ("EPS", "Rate"))
                divisor = 1 if unscaled else 1e6 if "Share" in str(label) else scale
                ws.cell(i, j, float(v) / divisor).number_format = "0.00" if unscaled else FORMATS["money"]
    _widths(ws, {"A": 48})
    ws.freeze_panes = "B5"


def build(c: Company, setup=None, valuation=None, implied: dict | None = None) -> bytes:
    """Workbook bytes; pass the engine's Setup and Valuation to add the live DCF sheet."""
    scale, unit = units(c.profile.get("currency"))
    wb = Workbook()
    fin_rows = _financials_sheet(wb, c, scale, unit)
    ratio_rows = _ratios_sheet(wb, c, fin_rows, unit)
    bench = _benchmarks_sheet(wb, c)
    _summary_sheet(wb, c, ratio_rows, fin_rows, bench, unit)
    for key, name in (("income", "Raw - Income"), ("balance", "Raw - Balance"), ("cashflow", "Raw - Cash Flow")):
        if key in c.raw:
            _raw_sheet(wb, name, c.raw[key], scale, unit)
    wb.move_sheet("Summary", offset=-wb.sheetnames.index("Summary"))
    if setup is not None and valuation is not None:
        add_dcf_sheet(wb, setup, valuation, scale, unit, implied)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
