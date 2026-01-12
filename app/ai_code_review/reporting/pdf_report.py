import io
from typing import Dict, Any, List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.units import mm

from app.ai_code_review.reviewers.base import ReviewResult


def build_pdf_report(result: ReviewResult, meta: Optional[Dict[str, str]] = None) -> bytes:
    meta = meta or {}
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="AI Code Review Report",
        author=meta.get("prepared_by", ""),
    )

    styles = getSampleStyleSheet()

    # Slightly smaller readable font for tables
    cell_style = ParagraphStyle(
        "cell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=10.5,
        textColor=colors.HexColor("#0f172a"),  # slate-900
    )

    cell_style_small = ParagraphStyle(
        "cell_small",
        parent=cell_style,
        fontSize=8,
        leading=10,
    )

    header_style = ParagraphStyle(
        "header_cell",
        parent=cell_style,
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#0f172a"),
    )

    story: List[Any] = []

    # Title
    story.append(Paragraph("AI Code Review - Report", styles["Title"]))
    story.append(Spacer(1, 10))

    # ---------- Project details ----------
    details = [
        ["Project", meta.get("project_name", "Uploaded ZIP")],
        ["Prepared by", meta.get("prepared_by", "")],
        ["Languages", meta.get("languages", "Unknown")],
        ["Overall Result", result.overall],
        ["Summary", result.summary],
    ]

    details_tbl = Table(details, colWidths=[35 * mm, 145 * mm])
    details_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),  # slate-100
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#0f172a")),  # slate-900
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),  # slate-300
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(details_tbl)
    story.append(Spacer(1, 14))

    # ---------- Findings ----------
    story.append(Paragraph("Findings", styles["Heading2"]))
    story.append(Spacer(1, 6))

    if not result.issues:
        story.append(Paragraph("No issues found.", styles["BodyText"]))
    else:
        # Use Paragraph in cells so text WRAPS properly
        data: List[List[Any]] = [
            [
                Paragraph("Category", header_style),
                Paragraph("Severity", header_style),
                Paragraph("Finding", header_style),
                Paragraph("Location", header_style),
                Paragraph("Suggested resolution", header_style),
            ]
        ]

        for iss in result.issues:
            location = f"{iss.file_path} : {iss.line_start}"
            finding = f"<b>{iss.title}</b><br/>{iss.detail}"
            remediation = iss.remediation

            data.append([
                Paragraph(str(iss.category), cell_style_small),
                Paragraph(str(iss.severity), cell_style_small),
                Paragraph(finding, cell_style),
                Paragraph(location, cell_style_small),
                Paragraph(remediation, cell_style),  # ✅ wraps
            ])

        # Wider last column; use wrapping via Paragraph
        # Total printable width is approx A4(210mm) - margins(36mm) = ~174mm
        col_widths = [24 * mm, 18 * mm, 62 * mm, 28 * mm, 42 * mm]

        tbl = Table(data, colWidths=col_widths, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),  # header slate-200
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),

            # Helps wrapping behavior
            ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
        ]))

        story.append(tbl)

    # ---------- Checklist page ----------
    story.append(PageBreak())
    story.append(Paragraph("Code Review Checklist", styles["Heading2"]))
    story.append(Spacer(1, 6))

    cdata: List[List[Any]] = [
        [
            Paragraph("Category", header_style),
            Paragraph("Checklist item", header_style),
            Paragraph("Result", header_style),
            Paragraph("Notes", header_style),
        ]
    ]

    for item in result.checklist:
        cdata.append([
            Paragraph(str(item["category"]), cell_style_small),
            Paragraph(str(item["item"]), cell_style),
            Paragraph(str(item["result"]), cell_style_small),
            Paragraph(str(item.get("notes", "") or ""), cell_style),
        ])

    ctbl = Table(cdata, colWidths=[30 * mm, 90 * mm, 20 * mm, 34 * mm], repeatRows=1)
    ctbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("WORDWRAP", (0, 0), (-1, -1), "CJK"),
    ]))

    story.append(ctbl)

    doc.build(story)
    return buf.getvalue()
