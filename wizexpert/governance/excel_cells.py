from openpyxl.cell.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet


def write_literal_cell(ws: Worksheet, row: int, column: int, value) -> Cell:
    """Write report data without interpreting imported strings as Excel formulas."""
    cell = ws.cell(row=row, column=column, value=value)
    if isinstance(value, str):
        # A text number format alone does not stop openpyxl from creating formulas.
        cell.data_type = "s"
    return cell
