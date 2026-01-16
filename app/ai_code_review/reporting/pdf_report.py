"""
PDF report generator for AI Code Review.

This version ensures:
- Table column headers have WHITE background
- Header text is BLACK + BOLD
- Header rows repeat on every page (repeatRows=1)
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)


# -------------------------
# Helpers
# -------------------------
def _get(d: Any, key: str, default: Any = "") -> Any:
    if isinstance(d, dict):
        return d.get(key, default)
    return getattr(d, key, default)


def _as_str(x: Any, default: str = "—") -> str:
    if x is None:
        return default
    s = str(x).strip()
    return s if s else default


def _issue_location(issue: Any) -> str:
    # Prefer location, else file_path:line_start, else file_path
    loc = _as_str(_get(issue, "location", ""), "")
    if loc:
        return loc

    fp = _as_str(_get(issue, "file_path", ""), "")
    ls = _as_str(_get(issue, "line_start", ""), "")
    if fp and ls and ls != "—":
        return f"{fp}:{ls}"
    if fp:
        return fp
    return "—"


def _normalize_languages(report: Any) -> str:
    langs = _get(report, "languages", None)
    if langs is None:
        return "Unknown"
    if isinstance(langs, (list, tuple)):
        return ", ".join([str(x) for x in langs]) if langs else "Unknown"
    return str(langs) if str(langs).strip() else "Unknown"


def _normalize_issues(context: Dict[str, Any]) -> List[Any]:
    # issues list can come in multiple shapes
    if isinstance(context.get("issues"), list):
        return context["issues"]

    report = context.get("report")
    if isinstance(report, dict) and isinstance(report.get("issues"), list):
        return report["issues"]

    result = context.get("result")
    if result is not None:
        iss = getattr(result, "issues", None)
        if isinstance(iss, list):
            return iss

    return []


def _normalize_checklist(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(context.get("checklist_rows"), list):
        return context["checklist_rows"]
    if isinstance(context.get("checklist"), list):
        return context["checklist"]

    report = context.get("report")
    if isinstance(report, dict) and isinstance(report.get("checklist"), list):
        return report["checklist"]

    result = context.get("result")
    if result is not None:
        cl = getattr(result, "checklist", None)
        if isinstance(cl, list):
            return cl  # could be item/result schema

    return []


# -------------------------
# Main generator
# -------------------------
def generate_pdf_bytes(
    *,
    report_id: str = "",
    project_name: str = "",
    prepared_by: str = "",
    report: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
    debug: Optional[Dict[str, Any]] = None,
    issues: Optional[List[Any]] = None,
    checklist_rows: Optional[List[Dict[str, Any]]] = None,
    checklist: Optional[List[Dict[str, Any]]] = None,
    result: Any = None,
) -> bytes:
    context: Dict[str, Any] = {
        "report_id": report_id,
        "project_name": project_name,
        "prepared_by": prepared_by,
        "report": report or {},
        "meta": meta or {},
        "debug": debug or {},
        "issues": issues,
        "checklist_rows": checklist_rows,
        "checklist": checklist,
        "result": result,
    }

    report_obj = context["report"]
    meta_obj = context["meta"]

    final_report_id = _as_str(context["report_id"] or _get(report_obj, "report_id", "") or _get(meta_obj, "report_id", ""), "—")
    final_project = _as_str(context["project_name"] or _get(meta_obj, "project_name", "") or _get(report_obj, "project_name", ""), "—")
    final_prepared_by = _as_str(context["prepared_by"] or _get(meta_obj, "prepared_by", ""), "Automation Factory")

    overall = _as_str(
        _get(report_obj, "overall", "") or _get(report_obj, "overall_status", "") or (getattr(result, "overall", "") if result else ""),
        "FAIL",
    )

    issue_list = _normalize_issues(context)
    checklist_list = _normalize_checklist(context)

    files_scanned = _get(report_obj, "files_scanned", None)
    if files_scanned is None:
        files_scanned = _get(report_obj, "files_scanned_text", None)
    if files_scanned is None and result is not None:
        files_scanned = getattr(result, "files_scanned", None)
    files_scanned = files_scanned if files_scanned is not None else 0

    languages = _normalize_languages(report_obj)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="AI Code Review Report",
        author=final_prepared_by,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "title",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        alignment=1,  # center
        textColor=colors.black,
    )

    h2_style = ParagraphStyle(
        "h2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        textColor=colors.black,
        spaceBefore=10,
        spaceAfter=6,
    )

    body_style = ParagraphStyle(
        "body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=colors.black,
    )

    cell_style = ParagraphStyle(
        "cell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=11,
        textColor=colors.black,
    )

    # ✅ Header cells now render BLACK text on WHITE header background
    header_style = ParagraphStyle(
        "header_cell",
        parent=cell_style,
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=colors.black,
    )

    # Styling colors
    GRID = colors.HexColor("#9CA3AF")    # gray-400
    ALT_ROW = colors.HexColor("#F3F4F6") # gray-100
    WHITE = colors.white

    story: List[Any] = []

    # Title
    story.append(Paragraph("AI Code Review Report", title_style))
    story.append(Spacer(1, 10))

    # Meta block
    meta_lines = [
        f"<b>Report ID:</b> {final_report_id}",
        f"<b>Project:</b> {final_project}",
        f"<b>Prepared by:</b> {final_prepared_by}",
        f"<b>Overall:</b> {overall}",
        f"<b>Total issues:</b> {len(issue_list)}",
        f"<b>Languages:</b> {languages}",
        f"<b>Files scanned (text):</b> {files_scanned}",
    ]
    for line in meta_lines:
        story.append(Paragraph(line, body_style))
    story.append(Spacer(1, 14))

    # Findings
    story.append(Paragraph("Findings", h2_style))
    story.append(Spacer(1, 6))

    if not issue_list:
        story.append(Paragraph("No issues found.", body_style))
    else:
        data: List[List[Any]] = [
            [
                Paragraph("#", header_style),
                Paragraph("Severity", header_style),
                Paragraph("Category", header_style),
                Paragraph("Title", header_style),
                Paragraph("Location", header_style),
                Paragraph("Remediation", header_style),
            ]
        ]

        for idx, i in enumerate(issue_list, start=1):
            sev = _as_str(_get(i, "severity", "MEDIUM"), "MEDIUM")
            cat = _as_str(_get(i, "category", ""), "—")
            title = _as_str(_get(i, "title", ""), "—")
            loc = _issue_location(i)
            rem = _as_str(_get(i, "remediation", ""), "—")

            data.append([
                Paragraph(str(idx), cell_style),
                Paragraph(sev, cell_style),
                Paragraph(cat, cell_style),
                Paragraph(title, cell_style),
                Paragraph(loc, cell_style),
                Paragraph(rem, cell_style),
            ])

        col_widths = [10 * mm, 22 * mm, 28 * mm, 60 * mm, 30 * mm, 28 * mm]
        tbl = Table(data, colWidths=col_widths, repeatRows=1)  # ✅ repeat header row

        tbl.setStyle(TableStyle([
            # ✅ WHITE HEADER ROW
            ("BACKGROUND", (0, 0), (-1, 0), WHITE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.black),  # strong header divider

            # Grid
            ("GRID", (0, 0), (-1, -1), 0.6, GRID),

            # Layout
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),

            # Zebra rows
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ALT_ROW]),
        ]))

        story.append(tbl)

    # Checklist
    story.append(PageBreak())
    story.append(Paragraph("Final Checklist", h2_style))
    story.append(Paragraph("Pass/Fail summary by category.", body_style))
    story.append(Spacer(1, 8))

    if not checklist_list:
        story.append(Paragraph("No checklist data available.", body_style))
    else:
        cdata: List[List[Any]] = [[
            Paragraph("Category", header_style),
            Paragraph("Check", header_style),
            Paragraph("Status", header_style),
            Paragraph("Evidence / Notes", header_style),
            Paragraph("Remediation", header_style),
        ]]

        for row in checklist_list:
            # support both schemas
            category = _as_str(_get(row, "category", ""), "—")
            check = _as_str(_get(row, "check", "") or _get(row, "item", ""), "—")
            status = _as_str(_get(row, "status", "") or _get(row, "result", ""), "—")
            evidence = _as_str(_get(row, "evidence", "") or _get(row, "notes", ""), "")
            remediation = _as_str(_get(row, "remediation", ""), "")

            cdata.append([
                Paragraph(category, cell_style),
                Paragraph(check, cell_style),
                Paragraph(status, cell_style),
                Paragraph(evidence, cell_style),
                Paragraph(remediation, cell_style),
            ])

        ctbl = Table(
            cdata,
            colWidths=[28 * mm, 60 * mm, 20 * mm, 45 * mm, 25 * mm],
            repeatRows=1,
        )

        ctbl.setStyle(TableStyle([
            # ✅ WHITE HEADER ROW
            ("BACKGROUND", (0, 0), (-1, 0), WHITE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.black),

            ("GRID", (0, 0), (-1, -1), 0.6, GRID),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, ALT_ROW]),
        ]))

        story.append(ctbl)

    doc.build(story)
    return buf.getvalue()


# Backward-compatible aliases (in case router imports older names)
def build_pdf_report(*args: Any, **kwargs: Any) -> bytes:
    return generate_pdf_bytes(**kwargs)


def build_pdf_bytes(*args: Any, **kwargs: Any) -> bytes:
    return generate_pdf_bytes(**kwargs)
