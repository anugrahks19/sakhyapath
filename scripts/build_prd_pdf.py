"""Render the editable teammate PRD Markdown into a shareable PDF."""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "SakhyaPath_PRD_Team_Handoff.md"
TARGET = ROOT / "output" / "pdf" / "SakhyaPath_PRD_Team_Handoff.pdf"
FONT_DIR = Path("C:/Windows/Fonts")


def inline(value: str) -> str:
    value = html.escape(value.strip())
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`([^`]+)`", r"<font name='ArialMono'>\1</font>", value)
    return value.replace("  ", " ")


def table_rows(block: list[str], styles: dict[str, ParagraphStyle], usable_width: float):
    rows = []
    for line in block:
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", p) for p in parts):
            continue
        rows.append(parts)
    if not rows:
        return []
    ncol = max(len(row) for row in rows)
    if ncol == 4 and "Current implementation" in rows[0]:
        fractions = [0.17, 0.28, 0.27, 0.28]
    elif ncol == 4:
        fractions = [0.15, 0.1, 0.35, 0.4]
    elif ncol == 3:
        fractions = [0.19, 0.34, 0.47]
    else:
        fractions = [1 / ncol] * ncol
    data = []
    for index, row in enumerate(rows):
        row += [""] * (ncol - len(row))
        data.append([Paragraph(inline(item), styles["th"] if index == 0 else styles["td"]) for item in row])
    table = LongTable(
        data,
        colWidths=[usable_width * fraction for fraction in fractions],
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F4EF")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAF9")]),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D6E4DF")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return [table, Spacer(1, 8)]


def footer(canvas, doc):
    canvas.saveState()
    page_w, _ = A4
    canvas.setStrokeColor(colors.HexColor("#D6E4DF"))
    canvas.line(19 * mm, 18 * mm, page_w - 19 * mm, 18 * mm)
    canvas.setFont("Arial", 8)
    canvas.setFillColor(colors.HexColor("#59706A"))
    canvas.drawString(19 * mm, 12 * mm, "SAKHYAPATH  /  TEAM HANDOFF  /  28 SEP 2026")
    canvas.drawRightString(page_w - 19 * mm, 12 * mm, str(doc.page))
    canvas.restoreState()


def build():
    pdfmetrics.registerFont(TTFont("Arial", str(FONT_DIR / "arial.ttf")))
    pdfmetrics.registerFont(TTFont("Arial-Bold", str(FONT_DIR / "arialbd.ttf")))
    pdfmetrics.registerFont(TTFont("ArialMono", str(FONT_DIR / "consola.ttf")))
    pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold")
    styles = getSampleStyleSheet()
    custom = {
        "title": ParagraphStyle("titlex", fontName="Arial-Bold", fontSize=21, leading=26, textColor=colors.HexColor("#103D39"), spaceAfter=13),
        "h2": ParagraphStyle("h2x", fontName="Arial-Bold", fontSize=13.1, leading=17, textColor=colors.HexColor("#126D60"), spaceBefore=15, spaceAfter=7, keepWithNext=True),
        "h3": ParagraphStyle("h3x", fontName="Arial-Bold", fontSize=10.5, leading=14, textColor=colors.HexColor("#274A46"), spaceBefore=10, spaceAfter=5, keepWithNext=True),
        "body": ParagraphStyle("bodyx", fontName="Arial", fontSize=9.2, leading=13.8, textColor=colors.HexColor("#253B38"), spaceAfter=7),
        "small": ParagraphStyle("smallx", fontName="Arial", fontSize=8.3, leading=11.8, textColor=colors.HexColor("#4C615D"), spaceAfter=7),
        "li": ParagraphStyle("lix", fontName="Arial", fontSize=9.1, leading=13.5, textColor=colors.HexColor("#253B38"), leftIndent=15, firstLineIndent=-10, spaceAfter=4),
        "td": ParagraphStyle("tdx", fontName="Arial", fontSize=7.7, leading=10.5, textColor=colors.HexColor("#253B38")),
        "th": ParagraphStyle("thx", fontName="Arial-Bold", fontSize=7.8, leading=10.8, textColor=colors.HexColor("#103D39")),
        "code": ParagraphStyle("codex", fontName="ArialMono", fontSize=7.2, leading=10, textColor=colors.HexColor("#28504A"), leftIndent=9, rightIndent=8, spaceAfter=2),
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(TARGET),
        pagesize=A4,
        rightMargin=19 * mm,
        leftMargin=19 * mm,
        topMargin=21 * mm,
        bottomMargin=23 * mm,
        title="SakhyaPath - Product Requirements Document and team handoff",
        author="SakhyaPath project team",
    )
    usable = A4[0] - 38 * mm
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    story = []
    i = 0
    in_code = False
    code_lines = []
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("```"):
            if in_code:
                story.append(KeepTogether([
                    Paragraph(html.escape(item).replace(" ", "&nbsp;"), custom["code"])
                    for item in code_lines
                ]))
                story.append(Spacer(1, 7))
                code_lines = []
            in_code = not in_code
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        if line.startswith("|"):
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(lines[i])
                i += 1
            story.extend(table_rows(block, custom, usable))
            continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), custom["title"]))
            story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#55B69C"), spaceAfter=12))
        elif line.startswith("## "):
            if line.startswith("## 18. "):
                story.append(PageBreak())
            story.append(Paragraph(inline(line[3:]), custom["h2"]))
        elif line.startswith("### "):
            story.append(Paragraph(inline(line[4:]), custom["h3"]))
        elif line.startswith("- ") or re.match(r"\d+\. ", line):
            content = re.sub(r"^(?:- |\d+\. )", "", line)
            story.append(Paragraph("&#8226; " + inline(content), custom["li"]))
        elif line.startswith("**Version:") or line.startswith("**Product stage:") or line.startswith("**Decision owner:"):
            story.append(Paragraph(inline(line), custom["small"]))
        else:
            paragraph = line
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"^(#|\||-|\d+\. |```)", lines[i + 1]):
                i += 1
                paragraph += " " + lines[i].strip()
            story.append(Paragraph(inline(paragraph), custom["body"]))
        i += 1
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(TARGET)


if __name__ == "__main__":
    build()
