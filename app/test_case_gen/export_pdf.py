from __future__ import annotations

from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def _p(text: str, style) -> Paragraph:
    return Paragraph((text or "").replace("\n", "<br/>"), style)


def _bullets(items: List[str], style) -> Paragraph:
    if not items:
        return Paragraph("-", style)
    html = "<br/>".join([f"• {i}" for i in items if (i or "").strip()])
    return Paragraph(html, style)


def write_testcases_pdf(payload: Dict[str, Any], out_path: str) -> None:
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Heading1"], spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceAfter=6)
    normal = styles["BodyText"]

    doc = SimpleDocTemplate(out_path, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story: List[Any] = []

    story.append(_p("SIT Test Cases Report", title))
    summary = payload.get("summary", {}) or {}

    story.append(_p("Scope Notes", h2))
    story.append(_p(summary.get("scope_notes", "-"), normal))
    story.append(Spacer(1, 10))

    story.append(_p("Assumptions", h2))
    story.append(_bullets(summary.get("assumptions", []) or [], normal))
    story.append(Spacer(1, 10))

    story.append(_p("Out of Scope", h2))
    story.append(_bullets(summary.get("out_of_scope", []) or [], normal))
    story.append(PageBreak())

    # Table of test cases (summary)
    story.append(_p("Test Case Summary", h2))
    rows = [["ID", "Category", "Priority", "Title", "Story Refs"]]
    for tc in payload.get("test_cases", []):
        rows.append([
            tc.get("id", ""),
            tc.get("category", ""),
            tc.get("priority", ""),
            tc.get("title", ""),
            ", ".join(tc.get("story_refs", []) or []),
        ])

    tbl = Table(rows, colWidths=[55, 80, 60, 220, 80])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
    ]))
    story.append(tbl)
    story.append(PageBreak())

    # Detailed per test case
    story.append(_p("Detailed Test Cases", h2))
    story.append(Spacer(1, 6))

    for tc in payload.get("test_cases", []):
        story.append(_p(f"{tc.get('id','')} — {tc.get('title','')}", styles["Heading3"]))
        story.append(_p(f"<b>Category:</b> {tc.get('category','')} &nbsp;&nbsp; <b>Priority:</b> {tc.get('priority','')}", normal))
        story.append(_p(f"<b>Story Refs:</b> {', '.join(tc.get('story_refs', []) or [])}", normal))
        story.append(Spacer(1, 6))

        story.append(_p("<b>Preconditions</b>", normal))
        story.append(_bullets(tc.get("preconditions", []) or [], normal))
        story.append(Spacer(1, 6))

        story.append(_p("<b>Test Data</b>", normal))
        story.append(_bullets(tc.get("test_data", []) or [], normal))
        story.append(Spacer(1, 6))

        story.append(_p("<b>Steps</b>", normal))
        story.append(_bullets(tc.get("steps", []) or [], normal))
        story.append(Spacer(1, 6))

        story.append(_p("<b>Expected Results</b>", normal))
        story.append(_bullets(tc.get("expected_results", []) or [], normal))
        story.append(Spacer(1, 6))

        gherkins = tc.get("gherkin", []) or []
        if gherkins:
            story.append(_p("<b>Gherkin</b>", normal))
            for g in gherkins:
                story.append(_p(f"<b>Feature:</b> {g.get('feature','')}", normal))
                story.append(_p(f"<b>Scenario:</b> {g.get('scenario','')}", normal))
                story.append(_p("<b>Given</b>", normal)); story.append(_bullets(g.get("given", []) or [], normal))
                story.append(_p("<b>When</b>", normal)); story.append(_bullets(g.get("when", []) or [], normal))
                story.append(_p("<b>Then</b>", normal)); story.append(_bullets(g.get("then", []) or [], normal))
                story.append(Spacer(1, 8))

        notes = tc.get("notes", []) or []
        if notes:
            story.append(_p("<b>Notes</b>", normal))
            story.append(_bullets(notes, normal))

        story.append(Spacer(1, 12))

    doc.build(story)
