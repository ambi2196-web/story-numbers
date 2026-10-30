"""The "Your story" sheet: market size x share x price per unit, with live formulas that feed the DCF sheet's
revenue growth. Change the target share (or any blue driver) and the value per share on the DCF sheet moves."""
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook

from app.engine.dcf import YEARS
from app.excel.workbook_style import FORMATS, INPUT_BLUE, header, title, widths

SHEET = "Your story"
COL = {t: get_column_letter(2 + t) for t in range(YEARS + 1)}  # B = today, C..L = years 1-10
DRIVERS = [  # key on StoryDrivers (or a helper), label, number format
    ("market_units", "Market size today ({unit_name} a year)", "#,##0"),
    ("market_growth", "Market growth, years 1-5 (fades by year 10)", FORMATS["pct"]),
    ("current_share", "Market share today", FORMATS["pct"]),
    ("target_share", "Target market share", FORMATS["pct"]),
    ("share_year", "Year target share is reached", "0"),
    ("price_per_unit", "Revenue per unit today (full currency)", "#,##0"),
    ("price_growth", "Revenue per unit growth, years 1-5", FORMATS["pct"]),
    ("revenue_share", "Share of revenue from this market", FORMATS["pct"]),
    ("target_margin", "Target operating margin (on DCF sheet)", FORMATS["pct"]),
    ("margin_year", "Year target margin is reached (on DCF sheet)", "0"),
    ("sales_to_capital", "Sales-to-capital (on DCF sheet)", FORMATS["x"]),
]
FIRST = 5
D = {key: f"$B${FIRST + i}" for i, (key, *_r) in enumerate(DRIVERS)}
HELPERS = FIRST + len(DRIVERS)  # price growth and market growth that the fade ends at
D["k"] = f"$B${HELPERS}"
HEAD = HELPERS + 2
LINES = ["market_growth", "price_growth", "market", "share", "units", "price", "story_rev", "rest", "revenue",
         "growth"]
R = {name: HEAD + 2 + i for i, name in enumerate(LINES)}


def growth_refs() -> list[str]:
    """Formulas for the DCF sheet's revenue growth row, years 1-10."""
    return [f"='{SHEET}'!{COL[t]}{R['growth']}" for t in range(1, YEARS + 1)]


def add_your_story_sheet(wb: Workbook, result, card, score: int, dcf_cells: dict, scale: float, unit: str) -> None:
    d = result.drivers
    ws = wb.create_sheet(SHEET, 1)
    title(ws, f"Your story: {d.headline}",
          "Blue = your inputs. Revenue from this market = today's x (units / units today) x (price / price today); "
          "other revenue keeps the status-quo growth. Total revenue growth drives the DCF sheet.")
    header(ws, FIRST - 1, ["Story driver", "Value", "Source", "Why"], first_numeric=2)
    dcf_linked = {"target_margin", "margin_year", "sales_to_capital"}
    dcf_key = {"target_margin": "target_margin", "margin_year": "margin_year", "sales_to_capital": "sales_to_capital_1_5"}
    for i, (key, label, fmt) in enumerate(DRIVERS):
        r, tagged = FIRST + i, getattr(d, key)
        ws.cell(r, 1, label.format(unit_name=d.unit_name))
        if key in dcf_linked:
            cell = ws.cell(r, 2, f"=DCF!{dcf_cells[dcf_key[key]]}")
        else:
            cell = ws.cell(r, 2, tagged.value)
            cell.font = Font(color=INPUT_BLUE)
        cell.number_format = fmt
        ws.cell(r, 3, "Your story" if tagged.source == "stated" else "AI inferred").font = Font(
            bold=tagged.source == "stated")
        ws.cell(r, 4, tagged.reason).alignment = Alignment(wrap_text=False)
    gt = f"DCF!{dcf_cells['terminal_growth']}"
    mg, pg = D["market_growth"], D["price_growth"]
    ws.cell(HELPERS, 1, "Year-10 scaling of market and price growth").font = Font(color="808080")
    ws.cell(HELPERS, 2, f"=IFERROR(IF(ABS({mg}*{pg})<1E-12,{gt}/({mg}+{pg}),(-({mg}+{pg})+SQRT(({mg}+{pg})^2"
                        f"+4*{mg}*{pg}*{gt}))/(2*{mg}*{pg})),1)").number_format = "0.000"
    ws.cell(HELPERS, 4, "Both shrink in proportion so revenue growth at a constant share ends at the terminal "
                        "growth rate").font = Font(italic=True, color="808080")

    header(ws, HEAD, ["Units and revenue", "Today", *[str(t) for t in range(1, YEARS + 1)]], first_numeric=2)
    yr = HEAD + 1
    ws.cell(yr, 1, "Year").font = Font(color="808080")
    for t in range(YEARS + 1):
        ws.cell(yr, 2 + t, t).font = Font(color="808080")
    labels = {"market_growth": ("Market growth", FORMATS["pct"]), "price_growth": ("Revenue per unit growth", FORMATS["pct"]),
              "market": (f"Market ({d.unit_name})", "#,##0"), "share": ("Market share", FORMATS["pct"]),
              "units": (f"Units sold ({d.unit_name})", "#,##0"), "price": ("Revenue per unit", "#,##0"),
              "story_rev": (f"Revenue from this market ({unit})", FORMATS["money"]),
              "rest": (f"Other revenue, status-quo growth ({unit})", FORMATS["money"]),
              "revenue": (f"Revenue ({unit})", FORMATS["money"]), "growth": ("Revenue growth (to DCF)", FORMATS["pct"])}
    for name, (label, _) in labels.items():
        ws.cell(R[name], 1, label).font = Font(bold=name in ("units", "revenue"))

    def put(name, t, formula):
        ws.cell(R[name], 2 + t, formula).number_format = labels[name][1]

    sy = f"MAX(ROUND({D['share_year']},0),1)"
    put("market", 0, f"={D['market_units']}")
    put("share", 0, f"={D['current_share']}")
    put("units", 0, f"=B{R['market']}*B{R['share']}")
    put("price", 0, f"={D['price_per_unit']}")
    put("revenue", 0, f"=DCF!{dcf_cells['revenue']}")
    put("story_rev", 0, f"=B{R['revenue']}*{D['revenue_share']}")
    put("rest", 0, f"=B{R['revenue']}*(1-{D['revenue_share']})")
    g1, g, gt = (f"DCF!{dcf_cells[k]}" for k in ("growth_y1", "growth_y2_5", "terminal_growth"))
    for t in range(1, YEARS + 1):
        c, p, y = COL[t], COL[t - 1], f"{COL[t]}${yr}"
        fade = f"MAX(0,MIN(1,({y}-5)/5))"
        put("market_growth", t, f"={mg}+({D['k']}*{mg}-{mg})*{fade}")
        put("price_growth", t, f"={pg}+({D['k']}*{pg}-{pg})*{fade}")
        put("market", t, f"={p}{R['market']}*(1+{c}{R['market_growth']})")
        put("share", t, f"=IF({y}>={sy},{D['target_share']},{D['current_share']}+"
                        f"({D['target_share']}-{D['current_share']})*{y}/{sy})")
        put("units", t, f"={c}{R['market']}*{c}{R['share']}")
        put("price", t, f"={p}{R['price']}*(1+{c}{R['price_growth']})")
        put("story_rev", t, f"=$B{R['story_rev']}*({c}{R['units']}/$B{R['units']})*({c}{R['price']}/$B{R['price']})")
        put("rest", t, f"={p}{R['rest']}*(1+IF({y}=1,{g1},IF({y}<=5,{g},{g}-({g}-{gt})*({y}-5)/5)))")
        put("revenue", t, f"={c}{R['story_rev']}+{c}{R['rest']}")
        put("growth", t, f"={c}{R['revenue']}/{p}{R['revenue']}-1")

    r = R["growth"] + 2
    header(ws, r, ["Story vs reality", "Story", "Reality", "Verdict", "Why"], first_numeric=9)
    for _, row in card.iterrows():
        r += 1
        for col, key in enumerate(("Check", "Story", "Reality", "Verdict", "Why"), 1):
            ws.cell(r, col, row[key])
    r += 1
    ws.cell(r, 1, f"Story score: {score}/100").font = Font(bold=True)
    if d.mix:
        r += 2
        header(ws, r, ["Product mix", "Share of units", "Today", "Source", "Effect"], first_numeric=2)
        for m in d.mix:
            r += 1
            ws.cell(r, 1, m.name)
            ws.cell(r, 2, m.share_of_units).number_format = "0%"
            ws.cell(r, 3, m.today).number_format = "0%"
            ws.cell(r, 4, "Your story" if m.source == "stated" else "AI inferred")
            ws.cell(r, 5, m.effect)
    r += 2
    header(ws, r, ["Red flags the AI noticed", "", "", "", ""], first_numeric=9)
    for flag in d.red_flags:
        r += 1
        ws.cell(r, 1, flag)
    widths(ws, {"A": 48, "B": 16, "C": 18, "D": 14, **{COL[t]: 14 for t in range(3, YEARS + 1)}})
    ws.freeze_panes = "B4"
