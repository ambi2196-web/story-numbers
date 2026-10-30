"""The Target sheet (Mode B): the target, the value today it needs, what each driver alone would need, and the
AI stories the engine calibrated to hit it, graded on the 3P test."""
from openpyxl.styles import Alignment, Font
from openpyxl.workbook import Workbook

from app.excel.workbook_style import FORMATS, INPUT_BLUE, header, title, widths


def add_target_sheet(wb: Workbook, name: str, target, setup, reqs, routes, scale: float, unit: str) -> None:
    a, w = setup.assumptions, setup.wacc
    ws = wb.create_sheet("Target", 1)
    title(ws, f"{name}: {target.label()} — what has to be true?",
          "If the market prices the company at fair value then, value must grow into the target at the cost of "
          "equity. Blue cells are inputs.")
    header(ws, 4, ["Target", "Value", "Note"], first_numeric=2)
    rows = [("Price today", a.price, "#,##0.00", ""),
            ("Target price", target.price(a), "#,##0.00", target.label()),
            ("Years", target.years, "0", ""),
            ("Cost of equity", w.cost_of_equity, FORMATS["pct"], "The return shareholders require"),
            ("Annual return to target", "=(B6/B5)^(1/B7)-1", FORMATS["pct"], ""),
            ("Value per share needed today", "=B6/(1+B8)^B7", "#,##0.00", "Target price / (1 + cost of equity)^years")]
    for i, (label, val, fmt, note) in enumerate(rows, start=5):
        ws.cell(i, 1, label)
        cell = ws.cell(i, 2, val)
        cell.number_format = fmt
        if not isinstance(val, str):
            cell.font = Font(color=INPUT_BLUE)
        ws.cell(i, 3, note).font = Font(italic=True, color="808080")

    r = 13
    header(ws, r, ["One driver alone (everything else at status quo)", "Required", "Status quo"], first_numeric=2)
    fmt = {"growth": FORMATS["pct"], "target_margin": FORMATS["pct"], "sales_to_capital": FORMATS["x"],
           "terminal_roic": FORMATS["pct"]}
    for _, row in reqs.iterrows():
        r += 1
        ws.cell(r, 1, row["Driver"])
        req = row["Required"]
        ws.cell(r, 2, req if req == req and req is not None else "not reachable alone").number_format = fmt[row["key"]]
        ws.cell(r, 3, row["Status quo"]).number_format = fmt[row["key"]]
    if routes:
        r += 2
        header(ws, r, ["Story", "3P verdict", "Score", "Lever", "AI start", "Needed", "Share yr 10",
                       "Units yr 10", f"Revenue yr 10 ({unit})", "Margin", "Value per share", "Pitch"],
               first_numeric=2)
        for rr in routes:
            r += 1
            path = rr.result.path
            pct = rr.route.lever != "sales_to_capital"
            vals = [rr.route.name, rr.verdict, rr.score, rr.route.lever.replace("_", " "), rr.lever_start,
                    rr.lever_value if rr.lever_value is not None else "out of reach", path["Market share"].iloc[10],
                    path["Units sold"].iloc[10], path["Revenue"].iloc[10] / scale,
                    rr.result.assumptions.target_margin, rr.valuation.value_per_share, rr.route.pitch]
            fmts = [None, None, "0", None, FORMATS["pct"] if pct else "0.00", FORMATS["pct"] if pct else "0.00",
                    FORMATS["pct"], "#,##0", FORMATS["money"], FORMATS["pct"], "#,##0.00", None]
            for col, (v, f) in enumerate(zip(vals, fmts), 1):
                c = ws.cell(r, col, v)
                if f:
                    c.number_format = f
            ws.cell(r, 12).alignment = Alignment(wrap_text=False)
        r += 2
        note = ("Each story's lever was set by the app so the story is worth exactly the value needed today. "
                "Verdict: any red flag = possible; no red flags = plausible; at most one stretch = probable.")
        ws.cell(r, 1, note).font = Font(italic=True, color="808080")
    widths(ws, {"A": 46, "B": 16, "C": 14, "D": 16, "E": 10, "F": 12, "G": 12, "H": 16, "I": 18, "J": 10,
                "K": 14, "L": 80})
