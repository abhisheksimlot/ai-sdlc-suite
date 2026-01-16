from __future__ import annotations

import os
import time
import uuid
import urllib.request
import urllib.parse
import urllib.error
from io import BytesIO
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

# ReportLab (PDF tables)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak

from app.ai_code_review.render import render
from app.ai_code_review.reviewers.base import Issue, ReviewResult
from app.ai_code_review.reviewers.python_ruff import PythonRuffReviewer
from app.ai_code_review.reviewers.power_platform import PowerPlatformReviewer
from app.ai_code_review.reviewers.model_driven_app import ModelDrivenAppReviewer
from app.ai_code_review.reviewers.canvas_msapp import CanvasMsappReviewer
from app.ai_code_review.reviewers.llm_fallback import LLMFallbackReviewer

from app.ai_code_review.utils.zip_reader import (
    read_zip_in_memory,
    normalize_zip_entries,
    as_text_files,
    extract_binary,
)
from app.ai_code_review.utils.language_detect import detect_languages
from app.ai_code_review.utils.content_filter import filter_files_for_review


# ✅ IMPORTANT: NO prefix here (your app.main likely sets the prefix already)
router = APIRouter(tags=["AI Code Review"])

python_reviewer = PythonRuffReviewer()
powerplatform_reviewer = PowerPlatformReviewer()
model_driven_reviewer = ModelDrivenAppReviewer()
canvas_msapp_reviewer = CanvasMsappReviewer()
llm_reviewer = LLMFallbackReviewer()

REPORT_CACHE: Dict[str, Dict[str, Any]] = {}
REPORT_TTL_SECONDS = 30 * 60
MAX_ZIP_MB_UPLOAD = int(os.getenv("MAX_ZIP_MB_UPLOAD", "500"))


def _cleanup_cache() -> None:
    now = time.time()
    for k in list(REPORT_CACHE.keys()):
        created = REPORT_CACHE[k].get("created", 0)
        if now - created > REPORT_TTL_SECONDS:
            REPORT_CACHE.pop(k, None)


def _download_github_zip(repo_url: str, branch: str) -> bytes:
    repo_url = (repo_url or "").strip().rstrip("/")
    if not repo_url.startswith("https://github.com/"):
        raise HTTPException(status_code=400, detail="Only public GitHub repos supported in this build.")

    parts = repo_url.replace("https://github.com/", "").split("/")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid GitHub repo URL.")

    org, repo = parts[0], parts[1]
    branch = (branch or "main").strip() or "main"
    url = f"https://github.com/{org}/{repo}/archive/refs/heads/{urllib.parse.quote(branch)}.zip"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-sdlc-suite"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"Failed to download repo ZIP (HTTP {e.code}).")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download repo ZIP: {e}")


def _issues_to_ui(issues: List[Issue]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in issues or []:
        fp = getattr(it, "file_path", "") or ""
        ls = getattr(it, "line_start", 1) or 1
        le = getattr(it, "line_end", ls) or ls

        location = "—"
        if fp:
            location = f"{fp}:{ls}" if le == ls else f"{fp}:{ls}-{le}"

        remediation = getattr(it, "remediation", "") or "—"

        out.append(
            {
                "severity": getattr(it, "severity", "") or "MEDIUM",
                "category": getattr(it, "category", "") or "Maintainability",
                "title": getattr(it, "title", "") or "Issue",
                "location": location,
                "remediation": remediation,
            }
        )
    return out


def _make_checklist(issues: List[Issue]) -> List[Dict[str, str]]:
    buckets = {"Security": 0, "Reliability": 0, "Maintainability": 0, "Performance": 0, "Style": 0}

    def norm(cat: str) -> str:
        c = (cat or "").strip()
        return c if c in buckets else "Maintainability"

    for it in issues or []:
        buckets[norm(getattr(it, "category", ""))] += 1

    def row(cat: str, check: str) -> Dict[str, str]:
        count = buckets.get(cat, 0)
        return {
            "category": cat,
            "check": check,
            "status": "FAIL" if count else "PASS",
            "evidence": f"{count} issue(s) found" if count else "",
            "remediation": "",
        }

    return [
        row("Security", "No hard-coded secrets or critical vulnerabilities"),
        row("Reliability", "Proper error handling and stability"),
        row("Maintainability", "Readable, modular, maintainable solution"),
        row("Performance", "No obvious performance bottlenecks"),
        row("Style", "Consistent standards and conventions"),
    ]


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    _cleanup_cache()
    return render(request, "index.html", {})


@router.post("/review", response_class=HTMLResponse)
async def review(
    request: Request,
    source_type: str = Form("zip"),
    prepared_by: str = Form(""),
    project_name: str = Form(""),
    project_zip: Optional[UploadFile] = File(None),
    repo_url: str = Form(""),
    repo_path: str = Form(""),
    branch: str = Form("main"),
    repository_type: str = Form("GIT"),
):
    _cleanup_cache()

    # support both repo_url and repo_path (your UI uses repo_path)
    repo = (repo_url or "").strip() or (repo_path or "").strip()
    source = (source_type or "zip").lower()

    # Read bytes
    if source == "zip":
        if not project_zip:
            return render(request, "index.html", {"error": "Please upload a ZIP file."}, status_code=400)

        zip_bytes = await project_zip.read()
        max_bytes = MAX_ZIP_MB_UPLOAD * 1024 * 1024
        if len(zip_bytes) > max_bytes:
            return render(request, "index.html", {"error": f"ZIP too large. Max allowed is {MAX_ZIP_MB_UPLOAD} MB."}, status_code=400)

        display_name = project_zip.filename or project_name.strip() or "Project"
    else:
        if not repo:
            return render(request, "index.html", {"error": "Please enter a GitHub repo URL."}, status_code=400)

        zip_bytes = _download_github_zip(repo, branch)
        display_name = project_name.strip() or repo.rstrip("/").split("/")[-1]

    # ZIP -> files
    entries = normalize_zip_entries(read_zip_in_memory(zip_bytes))
    text_files = as_text_files(entries)
    msapps = extract_binary(entries, extensions={".msapp"})
    files = filter_files_for_review(text_files)

    languages = detect_languages(files)
    issues: List[Issue] = []

    if "python" in languages:
        issues.extend(python_reviewer.review(files, "python"))

    if "powerplatform" in languages:
        issues.extend(powerplatform_reviewer.review(files, "powerplatform"))
        issues.extend(model_driven_reviewer.review(files, "powerplatform"))
        for name, blob in (msapps or {}).items():
            issues.extend(canvas_msapp_reviewer.review_msapp(name, blob))

    if os.getenv("OPENAI_API_KEY"):
        # run LLM once with hint
        issues.extend(llm_reviewer.review(files, ", ".join(languages) if languages else "unknown"))

    checklist = _make_checklist(issues)
    overall = "FAIL" if any(r["status"] == "FAIL" for r in checklist) else "PASS"

    rr = ReviewResult(
        issues=issues,
        checklist=checklist,
        overall=overall,
        summary=f"Platforms: {', '.join(languages) if languages else 'Unknown'} | Issues: {len(issues)}",
    )

    report_id = str(uuid.uuid4())
    issues_ui = _issues_to_ui(issues)

    meta = {
        "project_name": display_name,
        "prepared_by": prepared_by.strip() or "Unknown",
        "source_type": source_type,
        "repo_url": repo,
        "branch": branch,
        "repository_type": repository_type,
    }

    debug = {
        "source": "repo" if source != "zip" else "zip",
        "repo": repo,
        "branch": branch,
        "files_after_filter": len(files),
        "top_files": sorted(list(files.keys()))[:20],
        "languages": languages,
    }

    REPORT_CACHE[report_id] = {
        "created": time.time(),
        "issues_ui": issues_ui,
        "checklist": checklist,
        "result": rr,
        "meta": meta,
        "debug": debug,
    }

    report = {
        "overall": overall,
        "languages": ", ".join(languages) if languages else "Unknown",
        "files_scanned": len(files),
        "summary": rr.summary,
    }

    return render(
        request,
        "report.html",
        {
            "report_id": report_id,
            "issues": issues_ui,
            "checklist": checklist,
            "checklist_rows": checklist,
            "final_checklist": checklist,
            "report": report,
            "meta": meta,
            "debug": debug,
            "result": rr,
        },
    )


# ✅ PDF TABLE ENDPOINT (works at /ai-code-review/report/{id}/pdf once router is mounted with prefix)
@router.get("/report/{report_id}/pdf")
def report_pdf(report_id: str):
    _cleanup_cache()
    item = REPORT_CACHE.get(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="Report not found or expired.")

    issues = item.get("issues_ui", []) or []
    checklist = item.get("checklist", []) or []
    meta = item.get("meta", {}) or {}
    rr: ReviewResult = item.get("result")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="AI Code Review Report",
        author=str(meta.get("prepared_by", "Unknown")),
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=9, leading=11)

    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=10)
    cell_bold = ParagraphStyle("cell_bold", parent=cell, fontName="Helvetica-Bold")

    story: List[Any] = []

    # Header
    story.append(Paragraph("AI Code Review Report", title_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Report ID:</b> {report_id}", small))
    story.append(Paragraph(f"<b>Project:</b> {meta.get('project_name','')}", small))
    story.append(Paragraph(f"<b>Prepared by:</b> {meta.get('prepared_by','Unknown')}", small))
    story.append(Paragraph(f"<b>Overall:</b> {(rr.overall if rr else '')}", small))
    story.append(Paragraph(f"<b>Total issues:</b> {len(issues)}", small))
    story.append(Spacer(1, 10))

    # Findings Table
    story.append(Paragraph("Findings", styles["Heading2"]))
    story.append(Spacer(1, 6))

    if not issues:
        story.append(Paragraph("No issues found 🎉", styles["BodyText"]))
    else:
        data = [[
            Paragraph("<b>#</b>", cell_bold),
            Paragraph("<b>Severity</b>", cell_bold),
            Paragraph("<b>Category</b>", cell_bold),
            Paragraph("<b>Title</b>", cell_bold),
            Paragraph("<b>Location</b>", cell_bold),
            Paragraph("<b>Remediation</b>", cell_bold),
        ]]

        max_rows = int(os.getenv("PDF_MAX_ISSUES", "250"))
        for idx, it in enumerate(issues[:max_rows], start=1):
            data.append([
                Paragraph(str(idx), cell),
                Paragraph(str(it.get("severity", "—")), cell),
                Paragraph(str(it.get("category", "—")), cell),
                Paragraph(str(it.get("title", "—")), cell),
                Paragraph(str(it.get("location", "—")), cell),
                Paragraph(str(it.get("remediation", "—")), cell),
            ])

        col_widths = [10 * mm, 18 * mm, 22 * mm, 55 * mm, 28 * mm, 47 * mm]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#334155")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAFC"), colors.HexColor("#EEF2FF")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(t)

    # Checklist on new page
    story.append(PageBreak())
    story.append(Paragraph("Final Checklist", styles["Heading2"]))
    story.append(Paragraph("Pass/Fail summary by category.", small))
    story.append(Spacer(1, 8))

    cdata = [[
        Paragraph("<b>Category</b>", cell_bold),
        Paragraph("<b>Check</b>", cell_bold),
        Paragraph("<b>Status</b>", cell_bold),
        Paragraph("<b>Evidence</b>", cell_bold),
        Paragraph("<b>Remediation</b>", cell_bold),
    ]]

    for row in checklist:
        cdata.append([
            Paragraph(str(row.get("category", "—")), cell),
            Paragraph(str(row.get("check", "—")), cell),
            Paragraph(str(row.get("status", "—")), cell),
            Paragraph(str(row.get("evidence", "")), cell),
            Paragraph(str(row.get("remediation", "")), cell),
        ])

    ccol_widths = [26 * mm, 65 * mm, 18 * mm, 35 * mm, 36 * mm]
    ct = Table(cdata, colWidths=ccol_widths, repeatRows=1)
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#334155")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F8FAFC"), colors.HexColor("#EEF2FF")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(ct)

    doc.build(story)
    buf.seek(0)

    filename = f"code_review_{report_id}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
