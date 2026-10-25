"""Raster charts matching the approved executive-dashboard image-chart treatment."""

from __future__ import annotations

import math
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from wizexpert.governance.dashboard_data import require

NAVY = "#16324F"
BASE_BAR = "#123A61"
CYAN = "#009FDC"
GREEN = "#00B388"
MUTED = "#5B6B7A"
GRID = "#D5E3EF"


def chart_fonts(directory: Path) -> tuple[Path, Path]:
    regular, bold = directory / "calibri.ttf", directory / "calibrib.ttf"
    require(
        regular.is_file() and bold.is_file(),
        f"Approved chart fonts are missing in {directory}. "
        "Supply --font-dir with calibri.ttf and calibrib.ttf.",
    )
    return regular, bold


def canvas(size: tuple[int, int]):
    image = Image.new("RGB", size, "white")
    return image, ImageDraw.Draw(image)


def text(draw, xy, value, font, fill=NAVY, anchor="lt"):
    draw.text(xy, str(value), font=font, fill=fill, anchor=anchor)


def png(image: Image.Image) -> BytesIO:
    stream = BytesIO()
    image.save(stream, format="PNG")
    stream.seek(0)
    return stream


def scale_top(maximum: int) -> tuple[int, int]:
    step = max(25, math.ceil(maximum / 125) * 25)
    return max(125, math.ceil((maximum + 5) / step) * step), step


def line_chart(points: dict[date, int], subtitle: str, fonts: tuple[Path, Path]) -> BytesIO:
    require(
        2 <= len(points) <= 24,
        "Approved chart layout supports 2-24 monthly points; a longer trend needs layout approval.",
    )
    image, draw = canvas((1343, 513))
    regular, bold = fonts
    title_font = ImageFont.truetype(str(bold), 36)
    label_font = ImageFont.truetype(str(regular), 24 if len(points) <= 12 else 18)
    number_font = ImageFont.truetype(str(bold), 24 if len(points) <= 12 else 18)
    tick_font = ImageFont.truetype(str(regular), 20)
    text(draw, (96, 72), "Open backlog trend", title_font)
    text(draw, (96, 110), subtitle, ImageFont.truetype(str(regular), 23), MUTED)
    top, step = scale_top(max(points.values()))
    left, right, upper, bottom = 96, 1288, 134, 434
    positions = []
    for i, (_day, value) in enumerate(points.items()):
        x = 150 + i * (1235 - 150) / (len(points) - 1)
        y = bottom - value / top * (bottom - upper)
        positions.append((x, y))
    draw.polygon(
        [(positions[0][0], bottom), *positions, (positions[-1][0], bottom)], fill="#EDF9FD"
    )
    for value in range(0, top + 1, step):
        y = bottom - value / top * (bottom - upper)
        draw.line((left, y, right, y), fill=GRID, width=2)
        text(draw, (86, y), value, tick_font, MUTED, "rm")
    draw.line(positions, fill=CYAN, width=8, joint="curve")
    for i, ((day, value), (x, y)) in enumerate(zip(points.items(), positions, strict=False)):
        last = i == len(points) - 1
        draw.ellipse(
            (x - 10, y - 10, x + 10, y + 10),
            fill=GREEN if last else "white",
            outline="white" if last else CYAN,
            width=6,
        )
        text(draw, (x, y - 14), value, number_font, GREEN if last else NAVY, "mb")
        month = day.strftime("%b %d")
        if len({d.year for d in points}) > 1:
            month = day.strftime("%b '%y")
        # PIL's anchor keeps the label centered without changing the template chart box.
        text(draw, (x, bottom + 8), month, label_font, NAVY, "mt")
    return png(image)


def severity_chart(
    latest: date,
    current: dict[str, int],
    fonts: tuple[Path, Path],
    baseline: dict[str, int],
    baseline_on: date,
) -> BytesIO:
    image, draw = canvas((1283, 430))
    regular, bold = fonts
    text(draw, (96, 72), "Open findings remaining by severity", ImageFont.truetype(str(bold), 36))
    top, step = scale_top(max(*baseline.values(), *current.values()))
    upper, bottom = 140, 350
    for value in range(0, top + 1, step):
        y = bottom - value / top * (bottom - upper)
        draw.line((96, y, 1230, y), fill=GRID, width=2)
        text(draw, (86, y), value, ImageFont.truetype(str(regular), 20), MUTED, "rm")
    legend_font = ImageFont.truetype(str(regular), 23)
    draw.rectangle((440, 126, 482, 141), fill=BASE_BAR)
    text(draw, (500, 122), f"{baseline_on:%b} {baseline_on.day} baseline", legend_font, "#000000")
    draw.rectangle((697, 126, 739, 141), fill=GREEN)
    text(draw, (757, 122), latest.strftime("%b %d latest"), legend_font, "#000000")
    for severity, center in (("CRITICAL", 349), ("HIGH", 979)):
        for value, x, color in (
            (baseline[severity], center - 203, BASE_BAR),
            (current[severity], center, GREEN),
        ):
            y = bottom - value / top * (bottom - upper)
            if value:
                draw.rectangle((x, y, x + 200, bottom - 1), fill=color)
            text(draw, (x + 100, y - 5), value, ImageFont.truetype(str(bold), 24), NAVY, "mb")
        text(
            draw, (center, 356), severity.title(), ImageFont.truetype(str(regular), 27), NAVY, "mt"
        )
    return png(image)
