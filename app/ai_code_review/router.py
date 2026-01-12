import os
import time
import uuid
import html
from typing import List, Dict, Any

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from app.ai_code_review.utils.zip_reader import (
    read_zip_in_memory,
    as_text_files,
    extract_binary,
)
from app.ai_code_review.utils.language_detect import detect_languages
from app.ai_code_review.utils.content_filter import filter_files_for_review

from app.ai_code_review.reviewers.base import Issue, ReviewResult
from app.ai_code_review.reviewers.python_ruff import PythonRuffReviewer
from app.ai_code_review.reviewers.llm_fallback import LLMFallbackReviewer

from app.ai_code_review.reviewers.power_platform import PowerPlatformReviewer
from app.ai_code_review.reviewers.canvas_msapp import CanvasMsappReviewer
from app.ai_code_review.reviewers.model_driven_app import ModelDrivenAppReviewer

from app.ai_code_review.reporting.pdf_report import build_pdf_report


# ============================================================
# Router (mounted at /ai-code-review by suite)
# ============================================================
router = APIRouter(tags=["AI Code Review"])

python_reviewer = PythonRuffReviewer()
llm_reviewer = LLMFallbackReviewer(model=os.getenv("REVIEW_MODEL", "gpt-4.1-mini"))

# Power Platform reviewers
powerplatform_reviewer = PowerPlatformReviewer()
model_driven_reviewer = ModelDrivenAppReviewer()
canvas_msapp_reviewer = CanvasMsappReviewer()

REPORT_TTL_SECONDS = 30 * 60
REPORT_CACHE: Dict[str, Dict[str, Any]] = {}


# ============================================================
# Helpers
# ============================================================
def _cleanup_cache():
    now = time.time()
    expired = [k for k, v in REPORT_CACHE.items() if now - v["created"] > REPORT_TTL_SECONDS]
    for k in expired:
        REPORT_CACHE.pop(k, None)


def _severity_rank(s: str) -> int:
    return {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get((s or "").upper(), 0)


def _normalize_issue_severity(i: Issue) -> str:
    s = (i.severity or "").upper()
    return s if s in ("LOW", "MEDIUM", "HIGH", "CRITICAL") else "MEDIUM"


def make_checklist(issues: List[Issue], languages: List[str]) -> ReviewResult:
    is_powerplatform = "powerplatform" in (languages or [])

    by_cat: Dict[str, List[Issue]] = {}
    for i in issues:
        by_cat.setdefault(i.category, []).append(i)

    def count(cat: str) -> int:
        return len(by_cat.get(cat, []))

    def any_sev(cat: str, severities: set[str]) -> bool:
        for it in by_cat.get(cat, []):
            if _normalize_issue_severity(it) in severities:
                return True
        return False

    if is_powerplatform:
        checklist_defs = [
            ("ALM & Governance", "Uses environment variables and connection references; no hardcoded environment values"),
            ("Security", "No embedded secrets/tokens; connectors are properly referenced"),
            ("Reliability", "Flows have error handling (runAfter/Scope patterns); Canvas uses IfError for Patch"),
            ("Performance", "No obvious delegation/performance smells (ForAll/LookUp patterns; heavy navigation)"),
            ("Maintainability", "Apps/flows have clear naming; solution metadata present; minimal bloat"),
            ("Model-driven UX", "Model-driven app has sitemap/navigation and clear metadata"),
        ]

        checklist = []
        for cat, text in checklist_defs:
            if cat == "Security":
                fail = any_sev("Security", {"HIGH", "CRITICAL"}) or count("Security") > 0
                notes = f"{count('Security')} issue(s)" if count("Security") else ""
            elif cat == "Reliability":
                fail = count("Reliability") > 0
                notes = f"{count('Reliability')} issue(s)" if count("Reliability") else ""
            elif cat == "Performance":
                fail = count("Performance") > 0
                notes = f"{count('Performance')} issue(s)" if count("Performance") else ""
            elif cat == "Maintainability":
                fail = count("Maintainability") > 0
                notes = f"{count('Maintainability')} issue(s)" if count("Maintainability") else ""
            elif cat == "Model-driven UX":
                mda_hits = [x for x in issues if (x.rule_id or "").startswith("MDA-")]
                fail = len(mda_hits) > 0
                notes = f"{len(mda_hits)} model-driven issue(s)" if mda_hits else ""
            else:  # ALM & Governance
                alm_hits = [x for x in issues if (x.rule_id or "").startswith(("PP-", "MDA-", "MSAPP-"))]
                fail = len(alm_hits) > 0
                notes = f"{len(alm_hits)} governance issue(s)" if alm_hits else ""

            checklist.append({
                "category": cat,
                "item": text,
                "result": "FAIL" if fail else "PASS",
                "notes": notes,
            })

        overall = "PASS" if all(i["result"] == "PASS" for i in checklist) else "FAIL"
        summary = (
            f"Platforms detected: {', '.join(languages) if languages else 'Unknown'}. "
            f"Total issues found: {len(issues)}."
        )

        return ReviewResult(
            issues=issues,
            checklist=checklist,
            overall=overall,
            summary=summary,
        )

    checklist_defs = [
        ("Security", "No hard-coded secrets or critical vulnerabilities"),
        ("Reliability", "Proper error handling and stability"),
        ("Maintainability", "Readable, modular, maintainable solution"),
        ("Performance", "No obvious performance bottlenecks"),
        ("Style", "Consistent standards and conventions"),
    ]

    checklist = []
    for cat, text in checklist_defs:
        cat_issues = by_cat.get(cat, [])
        if cat == "Security":
            fail = any(_normalize_issue_severity(i) in ("HIGH", "CRITICAL") for i in cat_issues)
        else:
            fail = len(cat_issues) > 0

        checklist.append({
            "category": cat,
            "item": text,
            "result": "FAIL" if fail else "PASS",
            "notes": f"{len(cat_issues)} issue(s) found" if cat_issues else "",
        })

    overall = "PASS" if all(i["result"] == "PASS" for i in checklist) else "FAIL"
    summary = (
        f"Platforms detected: {', '.join(languages) if languages else 'Unknown'}. "
        f"Total issues found: {len(issues)}."
    )

    return ReviewResult(
        issues=issues,
        checklist=checklist,
        overall=overall,
        summary=summary,
    )


# ============================================================
# Report rendering (HTML)
# ============================================================
def _render_report_page(report_id: str, meta: Dict[str, str], rr: ReviewResult) -> str:
    rows = ""
    for i in sorted(
        rr.issues,
        key=lambda x: (-_severity_rank(_normalize_issue_severity(x)), x.category, x.file_path, x.line_start),
    ):
        rows += f"""
        <tr class="border-t border-slate-800 align-top">
          <td class="p-2">{html.escape(i.category)}</td>
          <td class="p-2">{html.escape(i.severity)}</td>
          <td class="p-2"><b>{html.escape(i.title)}</b><br/>{html.escape(i.detail)}</td>
          <td class="p-2 whitespace-nowrap">{html.escape(i.file_path)} : {i.line_start}</td>
          <td class="p-2">{html.escape(i.remediation)}</td>
        </tr>
        """

    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>AI Code Review Result</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100">
<div class="max-w-6xl mx-auto px-6 py-8">

<h1 class="text-3xl font-bold mb-4">AI Code Review Result</h1>

<div class="mb-6 text-sm text-slate-300">
  <div><b>Project:</b> {html.escape(meta.get("project_name",""))}</div>
  <div><b>Prepared by:</b> {html.escape(meta.get("prepared_by",""))}</div>
  <div><b>Platforms:</b> {html.escape(meta.get("languages",""))}</div>
  <div><b>Overall:</b> {rr.overall}</div>
</div>

<h2 class="text-xl font-semibold mb-2">Findings</h2>

<div class="overflow-x-auto">
<table class="w-full text-sm border border-slate-800">
<thead class="bg-slate-800">
<tr>
<th class="p-2 text-left">Category</th>
<th class="p-2 text-left">Severity</th>
<th class="p-2 text-left">Finding</th>
<th class="p-2 text-left">Location</th>
<th class="p-2 text-left">Suggested resolution</th>
</tr>
</thead>
<tbody>
{rows if rows else '<tr><td colspan="5" class="p-4">No issues found</td></tr>'}
</tbody>
</table>
</div>

<div class="mt-6 flex gap-4 text-sm">
<a class="text-emerald-400 underline" href="/ai-code-review/report/{report_id}.html">Download HTML</a>
<a class="text-indigo-400 underline" href="/ai-code-review/report/{report_id}.pdf">Download PDF</a>
</div>

</div>
</body>
</html>
"""


# ============================================================
# UI: Upload page
# ============================================================
@router.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>AI Code Review</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100">
<div class="max-w-3xl mx-auto px-6 py-10">
  <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
    <h1 class="text-2xl font-bold">AI Code Review</h1>
    <p class="text-slate-300 mt-1 text-sm">
      Python, Power Platform (Canvas + Model-Driven). Fully in-memory.
    </p>

    <form action="/ai-code-review/review" method="post" enctype="multipart/form-data" class="mt-4">
      <input type="file" name="project_zip" required class="block w-full"/>
      <button class="mt-4 bg-indigo-600 px-4 py-2 rounded font-semibold hover:bg-indigo-500">
        Generate Report
      </button>
    </form>
  </div>
</div>
</body>
</html>
""")


# ============================================================
# POST: Run review
# ============================================================
@router.post("/review", response_class=HTMLResponse)
async def review_zip(project_zip: UploadFile = File(...)):
    _cleanup_cache()

    zip_bytes = await project_zip.read()
    if not zip_bytes:
        raise HTTPException(status_code=400, detail="Empty ZIP uploaded")

    # Read ZIP fully in memory (binary + text)
    entries = read_zip_in_memory(zip_bytes)

    # Extract Canvas Apps (.msapp) as raw bytes for Option A parsing
    msapps = extract_binary(entries, ".msapp")

    # Decode text files for language detection and XML/JSON review
    text_files = as_text_files(entries)
    if not text_files:
        raise HTTPException(status_code=400, detail="No readable files found")

    languages = detect_languages(text_files)
    files_for_review = filter_files_for_review(text_files)

    issues: List[Issue] = []

    # ---- Python review ----
    if "python" in languages:
        issues.extend(python_reviewer.review(files_for_review, "python"))

    # ---- Power Platform review (ORDER MATTERS) ----
    if "powerplatform" in languages:
        # 1) Solution-level checks (NO .msapp placeholder logic here)
        issues.extend(powerplatform_reviewer.review(files_for_review, "powerplatform"))

        # 2) Model-driven app checks
        issues.extend(model_driven_reviewer.review(files_for_review, "powerplatform"))

        # 3) Canvas app checks (.msapp) - ONLY place where .msapp is analyzed
        for msapp_name, msapp_bytes in msapps.items():
            issues.extend(canvas_msapp_reviewer.review_msapp(msapp_name, msapp_bytes))

    # ---- LLM fallback ----
    if os.getenv("OPENAI_API_KEY"):
        for lang in languages:
            if lang not in ("python", "powerplatform"):
                issues.extend(llm_reviewer.review(files_for_review, lang))

    rr = make_checklist(issues, languages)

    report_id = str(uuid.uuid4())
    meta = {
        "project_name": project_zip.filename or "Uploaded ZIP",
        "prepared_by": os.getenv("REPORT_PREPARED_BY", "Abhishek Simlot"),
        "languages": ", ".join(languages) if languages else "Unknown",
    }

    REPORT_CACHE[report_id] = {
        "created": time.time(),
        "result": rr,
        "meta": meta,
    }

    return HTMLResponse(_render_report_page(report_id, meta, rr))


# ============================================================
# Download endpoints
# ============================================================
@router.get("/report/{report_id}.html", response_class=HTMLResponse)
def download_html(report_id: str):
    _cleanup_cache()
    item = REPORT_CACHE.get(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="Report expired")

    return HTMLResponse(
        _render_report_page(report_id, item["meta"], item["result"]),
        headers={"Content-Disposition": f"attachment; filename=code_review_{report_id}.html"},
    )


@router.get("/report/{report_id}.pdf")
def download_pdf(report_id: str):
    _cleanup_cache()
    item = REPORT_CACHE.get(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="Report expired")

    pdf_bytes = build_pdf_report(item["result"], meta=item["meta"])
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=code_review_{report_id}.pdf"},
    )
