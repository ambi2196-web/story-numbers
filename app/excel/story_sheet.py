"""The Story sheet: the AI business profile and the market's story today, next to the numbers."""
from openpyxl.styles import Alignment, Font
from openpyxl.workbook import Workbook

from app.excel.workbook_style import header, title, widths


def add_story_sheet(wb: Workbook, name: str, profile=None, story=None) -> None:
    ws = wb.create_sheet("Story", 1)
    title(ws, f"{name}: the story behind the numbers",
          "Written by AI from the data in this file; figures marked as AI estimates need checking.")
    r = 4

    def para(label: str, text: str) -> None:
        nonlocal r
        ws.cell(r, 1, label).font = Font(bold=True)
        cell = ws.cell(r, 2, text)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = max(15, 15 * (len(text) // 95 + 1))
        r += 1

    if story is not None:
        header(ws, r, ["The market's story today", ""], first_numeric=9)
        r += 1
        para("Headline", story.headline)
        para("Story", story.story)
        para("3P verdict", f"{story.verdict.capitalize()}: {story.reasoning}")
        r += 1
    if profile is not None:
        header(ws, r, ["Business profile", ""], first_numeric=9)
        r += 1
        para("In one line", profile.one_liner)
        para("Market", profile.addressable_market)
        para("Competitive position", profile.competitive_position)
        para("Industry group", f"{profile.damodaran_industry}: {profile.industry_reason}")
        para("Key risks", "; ".join(profile.key_risks))
        r += 1
        header(ws, r, ["Line of business", "Share of revenue", "What it is"], first_numeric=2)
        for seg in profile.segments:
            r += 1
            ws.cell(r, 1, seg.name)
            ws.cell(r, 2, seg.share_of_revenue).number_format = "0%"
            ws.cell(r, 3, seg.description).alignment = Alignment(wrap_text=True, vertical="top")
        r += 2
        header(ws, r, ["Unit driver (AI estimate)", "Latest value", "Unit", "Note"], first_numeric=2)
        for d in profile.unit_drivers:
            r += 1
            ws.cell(r, 1, d.name)
            ws.cell(r, 2, d.latest_value).number_format = "#,##0.##"
            ws.cell(r, 3, d.unit)
            ws.cell(r, 4, d.note).alignment = Alignment(wrap_text=True, vertical="top")
    widths(ws, {"A": 34, "B": 95, "C": 50, "D": 60})
