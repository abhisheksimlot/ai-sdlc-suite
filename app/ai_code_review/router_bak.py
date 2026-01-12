import os
import time
import uuid
import html
from typing import List, Dict, Any

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from app.ai_code_review.utils.zip_reader import read_zip_in_memory, as_text_files
from app.ai_code_review.utils.language_detect import detect_languages
from app.ai_code_review.utils.content_filter import filter_files_for_review

from app.ai_code_review.reviewers.base import Issue, ReviewResult
from app.ai_code_review.reviewers.python_ruff import PythonRuffReviewer
from app.ai_code_review.reviewers.llm_fallback import LLMFallbackReviewer
from app.ai_code_review.reviewers.power_platform import PowerPlatformReviewer

from app.ai_code_review.reporting.pdf_report import build_pdf_report

from app.ai_code_review.utils.zip_reader import read_zip_in_memory, as_text_files, extract_binary
from app.ai_code_review.reviewers.canvas_msapp import CanvasMsappReviewer


# ============================================================
# Router (mounted at /ai-code-review by suite)
# ============================================================
router = APIRouter(tags=["AI Code Review"])

python_reviewer = PythonRuffReviewer()
llm_reviewer = LLMFallbackReviewer(model=os.getenv("REVIEW_MODEL", "gpt-4.1-mini"))
powerplatform_reviewer = PowerPlatformReviewer()

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


def _category_counts(issues: List[Issue]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for i in issues:
        out[i.category] = out.get(i.category, 0) + 1
    return out


def make_checklist(issues: List[Issue], languages: List[str]) -> ReviewResult:
    checklist_defs = [
        ("Security", "No hard-coded secrets or critical vulnerabilities"),
        ("Reliability", "Proper error handling and stability"),
        ("Maintainability", "Readable, modular, maintainable solution"),
        ("Performance", "No obvious performance bottlenecks"),
        ("Style", "Consistent standards and conventions"),
    ]

    by_cat: Dict[str, List[Issue]] = {}
    for i in issues:
        by_cat.setdefault(i.category, []).append(i)

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
        f"Languages / Platforms detected: {', '.join(languages) if languages else 'Unknown'}. "
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
        <tr class="border-t border-slate-800">
          <td class="py-2">{html.escape(i.category)}</td>
          <td class="py-2">{html.escape(i.severity)}</td>
          <td class="py-2"><b>{html.escape(i.title)}</b><br/>{html.escape(i.detail)}</td>
          <td class="py-2">{html.escape(i.file_path)} : {i.line_start}</td>
          <td class="py-2">{html.escape(i.remediation)}</td>
        </tr>
        """

    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Code Review Result</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100">
<div class="max-w-6xl mx-auto px-6 py-8">

<h1 class="text-3xl font-bold mb-4">Code Review Result</h1>

<div class="mb-6">
  <b>Project:</b> {html.escape(meta.get("project_name",""))}<br/>
  <b>Prepared by:</b> {html.escape(meta.get("prepared_by",""))}<br/>
  <b>Languages:</b> {html.escape(meta.get("languages",""))}<br/>
  <b>Overall:</b> {rr.overall}
</div>

<h2 class="text-xl font-semibold mb-2">Findings</h2>

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

<div class="mt-6 flex gap-4">
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
<form action="/ai-code-review/review" method="post" enctype="multipart/form-data" class="mt-4">
<input type="file" name="project_zip" required class="block w-full"/>
<button class="mt-4 bg-indigo-600 px-4 py-2 rounded">Generate</button>
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

    entries = read_zip_in_memory(zip_bytes)
    text_files = as_text_files(entries)
    if not text_files:
        raise HTTPException(status_code=400, detail="No readable files found")

    languages = detect_languages(text_files)
    files_for_review = filter_files_for_review(text_files)

    issues: List[Issue] = []

    if "python" in languages:
        issues.extend(python_reviewer.review(files_for_review, "python"))

    if "powerplatform" in languages:
        issues.extend(powerplatform_reviewer.review(files_for_review, "powerplatform"))

    if os.getenv("OPENAI_API_KEY"):
        for lang in languages:
            if lang not in ("python", "powerplatform"):
                issues.extend(llm_reviewer.review(files_for_review, lang))

    rr = make_checklist(issues, languages)

    report_id = str(uuid.uuid4())
    meta = {
        "project_name": project_zip.filename or "Uploaded ZIP",
        "prepared_by": os.getenv("REPORT_PREPARED_BY", "Abhishek Simlot"),
        "languages": ", ".join(languages),
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
