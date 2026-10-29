"""Shared look for every sheet: navy headers, blue inputs, number formats."""
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

NAVY, LIGHT, INPUT_BLUE = "1F3864", "D9E2F3", "0000FF"
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor=NAVY)
SECTION_FILL = PatternFill("solid", fgColor=LIGHT)
FORMATS = {"pct": "0.0%", "money": "#,##0;(#,##0)", "x": '0.00"x"'}


def header(ws: Worksheet, row: int, values: list, first_numeric: int = 3) -> None:
    for col, v in enumerate(values, 1):
        cell = ws.cell(row, col, v)
        cell.font, cell.fill = HEADER_FONT, HEADER_FILL
        cell.alignment = Alignment(horizontal="center" if col >= first_numeric else "left")


def title(ws: Worksheet, text: str, subtitle: str) -> None:
    ws["A1"] = text
    ws["A1"].font = Font(bold=True, size=14, color=NAVY)
    ws["A2"] = subtitle
    ws["A2"].font = Font(italic=True, color="595959")


def widths(ws: Worksheet, sizes: dict[str, float]) -> None:
    for col, w in sizes.items():
        ws.column_dimensions[col].width = w
