# app/ai_code_review/router.py
from __future__ import annotations

import os
import re
import time
import uuid
import base64
import urllib.parse
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

from .render import render
from .utils.zip_reader import read_zip_in_memory, as_text_files, extract_binary
from .utils.language_detect import detect_languages
from .utils.content_filter import filter_files_for_review

from .reviewers.base import Issue, ReviewResult
from .reviewers.python_ruff import PythonRuffReviewer
from .reviewers.llm_fallback import LLMFallbackReviewer
from .reviewers.power_platform import PowerPlatformReviewer
from .reviewers.canvas_msapp import CanvasMsappReviewer
from .reviewers.model_driven_app import ModelDrivenAppReviewer

from .reporting.pdf_report import build_pdf_report


# ============================================================
# Router (NO prefix – mounted by suite at /ai-code-review)
# ============================================================
router = APIRouter(tags=["AI Code Review"])


# ============================================================
# Reviewers
# ============================================================
python_reviewer = PythonRuffReviewer()
llm_reviewer = LLMFallbackReviewer(model=os.getenv("REVIEW_MODEL", "gpt-4.1-mini"))
powerplatform_reviewer = PowerPlatformReviewer()
model_driven_reviewer = ModelDrivenAppReviewer()
canvas_msapp_reviewer = CanvasMsappReviewer()


# ============================================================
# Cache & limits
# ============================================================
REPORT_TTL_SECONDS = 30 * 60
REPORT_CACHE: Dict[str, Dict[str, Any]] = {}
MAX_ZIP_MB_UPLOAD = int(os.getenv("MAX_ZIP_MB_UPLOAD", "35"))


def _cleanup_cache() -> None:
    now = time.time()
    for k in list(REPORT_CACHE.keys()):
        if now - REPORT_CACHE[k]["created"] > REPORT_TTL_SECONDS:
            REPORT_CACHE.pop(k, None)


# ============================================================
# IMPORTANT: Normalize repo ZIP structure to match uploaded ZIP
# Supports both:
#   - dict[path -> bytes]
#   - list[dataclass/dict-like] entries (including frozen dataclasses)
# ============================================================
def normalize_zip_entries(entries):
    """
    Normalize ZIP entry paths so repo downloads (often wrapped in a single root folder)
    behave the same as uploaded ZIPs.

    Strips the common single top-level folder if ALL entries share it:
      repo-main/app/main.py -> app/main.py

    Does NOT mutate frozen dataclasses; rebuilds safely.
    """
    if not entries:
        return entries

    # ----------------------------
    # Case A: dict[path -> bytes]
    # ----------------------------
    if isinstance(entries, dict):
        top_levels = set()
        for path in entries.keys():
            parts = path.split("/", 1)
            if len(parts) == 2:
                top_levels.add(parts[0])

        if len(top_levels) == 1:
            root = next(iter(top_levels))
            normalized = {}
            for path, data in entries.items():
                if path.startswith(root + "/"):
                    normalized[path[len(root) + 1 :]] = data
                else:
                    normalized[path] = data
            return normalized

        return entries

    # ----------------------------
    # Case B: list of (possibly frozen) dataclass entries
    # ----------------------------
    if isinstance(entries, list):

        def get_path(item) -> str:
            return (
                getattr(item, "path", None)
                or getattr(item, "name", None)
                or getattr(item, "filename", None)
                or ""
            )

        roots = set()
        for e in entries:
            p = get_path(e)
            if p and "/" in p:
                roots.add(p.split("/", 1)[0])

        if len(roots) != 1:
            return entries

        root = next(iter(roots))
        normalized_entries = []

        for e in entries:
            old_path = get_path(e)
            new_path = old_path[len(root) + 1 :] if old_path.startswith(root + "/") else old_path

            # dataclass: rebuild with same fields
            if hasattr(e, "__dataclass_fields__"):
                field_names = list(e.__dataclass_fields__.keys())
                kwargs = {f: getattr(e, f) for f in field_names}

                # update whichever field represents the path
                for pf in ("path", "name", "filename"):
                    if pf in kwargs:
                        kwargs[pf] = new_path
                        break

                normalized_entries.append(type(e)(**kwargs))
            else:
                # unknown type - keep as-is
                normalized_entries.append(e)

        return normalized_entries

    return entries


# ============================================================
# User-friendly errors
# ============================================================
class UserFacingRepoError(ValueError):
    """Errors safe to show directly to users."""


# ============================================================
# HTTP helper
# ============================================================
def _http_get_bytes(url: str, headers: Dict[str, str]) -> bytes:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            if not data:
                raise UserFacingRepoError(
                    "Repository download succeeded but returned no files. Please verify the repository and branch."
                )
            return data

    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise UserFacingRepoError(
                "Access denied while downloading the repository. "
                "If this is a public repo, please re-check the URL; if it's private, credentials are required."
            )
        if e.code == 404:
            raise UserFacingRepoError(
                "Repository or branch not found. Please verify the repo path and branch name."
            )
        raise UserFacingRepoError(f"Repository download failed (HTTP {e.code}). Please try again.")

    except urllib.error.URLError:
        raise UserFacingRepoError(
            "Network error while accessing the repository. Please check your internet/VPN and try again."
        )


# ============================================================
# Azure DevOps helpers (Public-friendly: PAT optional)
# ============================================================
def _parse_azure_devops_repo(repo_path: str) -> Dict[str, str]:
    p = repo_path.strip()
    if not p.startswith("http"):
        p = "https://dev.azure.com/" + p.strip("/")

    m1 = re.match(r"^https://dev\.azure\.com/([^/]+)/([^/]+)/_git/([^/?#]+)", p, re.IGNORECASE)
    if m1:
        return {"org": m1.group(1), "project": m1.group(2), "repo": m1.group(3)}

    m2 = re.match(r"^https://([^/.]+)\.visualstudio\.com/([^/]+)/_git/([^/?#]+)", p, re.IGNORECASE)
    if m2:
        return {"org": m2.group(1), "project": m2.group(2), "repo": m2.group(3)}

    raise UserFacingRepoError(
        "Azure DevOps repo path format not recognised. Use: https://dev.azure.com/{org}/{project}/_git/{repo}"
    )


def _azure_devops_headers() -> Dict[str, str]:
    headers = {"Accept": "application/zip", "User-Agent": "AI-SDLC-Suite"}
    pat = os.getenv("ADO_PAT", "").strip()
    if pat:
        token = base64.b64encode(f":{pat}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    return headers


def _azure_devops_zip_url(org: str, project: str, repo: str, branch: str) -> str:
    b = branch.strip()
    if b.lower().startswith("refs/heads/"):
        b = b.split("/", 2)[-1]

    return (
        f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/items"
        f"?scopePath=/"
        f"&recursionLevel=Full"
        f"&versionDescriptor.version={urllib.parse.quote(b)}"
        f"&versionDescriptor.versionType=branch"
        f"&includeContent=true"
        f"&$format=zip"
        f"&api-version=7.0"
    )


# ============================================================
# GitHub helpers (Public-friendly: token optional)
# ============================================================
def _parse_github_repo(repo_path: str) -> Dict[str, str]:
    p = repo_path.strip()

    if p.startswith("http"):
        m = re.match(r"^https://github\.com/([^/]+)/([^/?#]+)", p, re.IGNORECASE)
        if not m:
            raise UserFacingRepoError("GitHub repo path format not recognised. Use https://github.com/{owner}/{repo}")
        owner, repo = m.group(1), m.group(2)
    else:
        parts = p.strip("/").split("/")
        if len(parts) != 2:
            raise UserFacingRepoError("GitHub repo path format not recognised. Use owner/repo")
        owner, repo = parts[0], parts[1]

    return {"owner": owner, "repo": repo.replace(".git", "")}


def _github_headers() -> Dict[str, str]:
    headers = {"Accept": "application/zip", "User-Agent": "AI-SDLC-Suite"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_zip_url(owner: str, repo: str, branch: str) -> str:
    b = branch.strip()
    if b.lower().startswith("refs/heads/"):
        b = b.split("/", 2)[-1]
    return f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{urllib.parse.quote(b)}"


# ============================================================
# Repo fetch (supports Public repos; tokens optional)
# ============================================================
async def fetch_repo_as_zip_bytes(repo_type: str, repo_path: str, branch_name: str) -> bytes:
    repo_type = (repo_type or "").strip().lower()
    repo_path = (repo_path or "").strip()
    branch_name = (branch_name or "").strip()

    if repo_type not in ("azure_devops", "git"):
        raise UserFacingRepoError("Please select repository type: GIT or Azure DevOps.")
    if not repo_path:
        raise UserFacingRepoError("Repository path is required.")
    if not branch_name:
        raise UserFacingRepoError("Branch name is required.")

    if repo_type == "azure_devops":
        ado = _parse_azure_devops_repo(repo_path)
        url = _azure_devops_zip_url(ado["org"], ado["project"], ado["repo"], branch_name)
        return _http_get_bytes(url, _azure_devops_headers())

    gh = _parse_github_repo(repo_path)
    url = _github_zip_url(gh["owner"], gh["repo"], branch_name)
    return _http_get_bytes(url, _github_headers())


# ============================================================
# Checklist helpers
# ============================================================
def _normalize_severity(sev: str) -> str:
    s = (sev or "").upper()
    return s if s in ("LOW", "MEDIUM", "HIGH", "CRITICAL") else "MEDIUM"


def _bucket_for_issue(issue: Issue, languages: List[str]) -> str:
    is_pp = "powerplatform" in (languages or [])
    rid = (getattr(issue, "rule_id", "") or "").upper()
    cat = (issue.category or "").strip().lower()
    title = (issue.title or "").strip().lower()
    detail = (issue.detail or "").strip().lower()

    if is_pp:
        if rid.startswith(("PP-", "MSAPP-")):
            return "ALM & Governance"
        if rid.startswith("MDA-"):
            return "Model-driven UX"
        if cat == "security" or ("secret" in title) or ("secret" in detail) or ("token" in detail):
            return "Security"
        if cat in ("reliability", "availability"):
            return "Reliability"
        if cat == "performance" or ("delegation" in title) or ("delegation" in detail):
            return "Performance"
        if cat in ("maintainability", "governance", "alm"):
            return "Maintainability"
        return "Maintainability"

    if cat == "security":
        return "Security"
    if cat in ("reliability", "availability"):
        return "Reliability"
    if cat == "performance":
        return "Performance"
    if cat == "maintainability":
        return "Maintainability"
    if ("style" in cat) or ("format" in cat) or ("lint" in cat):
        return "Style"
    return "Maintainability"


def make_checklist(issues: List[Issue], languages: List[str]) -> List[Dict[str, str]]:
    is_pp = "powerplatform" in (languages or [])

    bucket_counts: Dict[str, int] = {}
    bucket_high_crit: Dict[str, bool] = {}

    for it in issues:
        b = _bucket_for_issue(it, languages)
        bucket_counts[b] = bucket_counts.get(b, 0) + 1
        if _normalize_severity(it.severity) in ("HIGH", "CRITICAL"):
            bucket_high_crit[b] = True

    if is_pp:
        defs = [
            ("ALM & Governance", "Uses env vars + connection references; no hardcoded environment values"),
            ("Security", "No embedded secrets/tokens; connectors and references are used correctly"),
            ("Reliability", "Flows use Scopes/runAfter patterns; app formulas handle errors (IfError)"),
            ("Performance", "No obvious delegation/performance smells (ForAll/LookUp patterns)"),
            ("Maintainability", "Clear naming; solution metadata present; minimal bloat"),
            ("Model-driven UX", "Sitemap/navigation and key metadata present"),
        ]
    else:
        defs = [
            ("Security", "No hard-coded secrets or critical vulnerabilities"),
            ("Reliability", "Proper error handling and stability"),
            ("Maintainability", "Readable, modular, maintainable solution"),
            ("Performance", "No obvious performance bottlenecks"),
            ("Style", "Consistent standards and conventions"),
        ]

    rows: List[Dict[str, str]] = []
    for bucket, text in defs:
        c = bucket_counts.get(bucket, 0)
        if bucket == "Security":
            fail = c > 0 or bucket_high_crit.get(bucket, False)
        else:
            fail = c > 0

        rows.append(
            {
                "category": bucket,
                "item": text,
                "result": "FAIL" if fail else "PASS",
                "notes": f"{c} issue(s) found" if c else "",
            }
        )
    return rows


def overall_from_checklist(checklist: List[Dict[str, str]]) -> str:
    return "PASS" if all(r.get("result") == "PASS" for r in checklist) else "FAIL"


# ============================================================
# Template shaping (matches report.html)
# ============================================================
def _issues_for_template(issues: List[Issue]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in issues or []:
        out.append(
            {
                "category": it.category,
                "severity": it.severity,
                "title": it.title,
                "description": it.detail,
                "file": it.file_path,
                "line": it.line_start,
                "suggested_fix": it.remediation,
            }
        )
    return out


def _report_for_template(rr: ReviewResult, languages: List[str], files_scanned: int) -> Dict[str, Any]:
    checklist_rows = []
    for row in rr.checklist or []:
        checklist_rows.append(
            {
                "category": row.get("category", ""),
                "check": row.get("item", ""),
                "status": row.get("result", ""),
                "evidence": row.get("notes", ""),
                "remediation": "",
            }
        )

    return {
        "primary_language": (languages[0] if languages else "Unknown"),
        "files_scanned": files_scanned,
        "overall_checklist_status": rr.overall,
        "checklist": checklist_rows,
    }


# ============================================================
# Routes
# ============================================================
@router.get("/", response_class=HTMLResponse)
def home_page(request: Request):
    return render(request, "index.html", {})


@router.post("/review", response_class=HTMLResponse)
async def review(
    request: Request,
    source_type: str = Form("zip"),
    zip_file: Optional[UploadFile] = File(default=None),
    repo_type: str = Form(""),
    repo_path: str = Form(""),
    branch_name: str = Form(""),
    prepared_by: str = Form("Automation Factory"),
):
    _cleanup_cache()
    prepared_by = "Automation Factory"

    try:
        if source_type == "zip":
            if zip_file is None:
                raise UserFacingRepoError("Please choose a ZIP file.")
            zip_bytes = await zip_file.read()
            if not zip_bytes:
                raise UserFacingRepoError("Uploaded ZIP is empty.")
            if len(zip_bytes) > MAX_ZIP_MB_UPLOAD * 1024 * 1024:
                raise UserFacingRepoError(f"ZIP too large. Max allowed is {MAX_ZIP_MB_UPLOAD} MB.")
            project_display_name = zip_file.filename or "Uploaded ZIP"

        elif source_type == "repo":
            zip_bytes = await fetch_repo_as_zip_bytes(repo_type, repo_path, branch_name)

            # enforce SAME size limit for repo downloads
            if len(zip_bytes) > MAX_ZIP_MB_UPLOAD * 1024 * 1024:
                raise UserFacingRepoError(f"Repository ZIP too large. Max allowed is {MAX_ZIP_MB_UPLOAD} MB.")

            project_display_name = repo_path.strip()

        else:
            raise UserFacingRepoError("Invalid source selected.")

    except UserFacingRepoError as e:
        return render(request, "index.html", {"error": str(e)}, status_code=400)
    except Exception:
        return render(
            request,
            "index.html",
            {"error": "Something went wrong while processing your request. Please try again."},
            status_code=400,
        )

    entries = read_zip_in_memory(zip_bytes)
    entries = normalize_zip_entries(entries)

    text_files = as_text_files(entries)
    msapps = extract_binary(entries, ".msapp")

    if not text_files and not msapps:
        return render(
            request,
            "index.html",
            {"error": "No readable code or .msapp found in the provided source."},
            status_code=400,
        )

    languages = detect_languages(text_files)
    files_for_review = filter_files_for_review(text_files)

    issues: List[Issue] = []

    if "python" in languages:
        issues.extend(python_reviewer.review(files_for_review, "python"))

    if "powerplatform" in languages:
        issues.extend(powerplatform_reviewer.review(files_for_review, "powerplatform"))
        issues.extend(model_driven_reviewer.review(files_for_review, "powerplatform"))
        for msapp_name, msapp_bytes in msapps.items():
            issues.extend(canvas_msapp_reviewer.review_msapp(msapp_name, msapp_bytes))

    if os.getenv("OPENAI_API_KEY"):
        for lang in languages:
            if lang not in ("python", "powerplatform"):
                issues.extend(llm_reviewer.review(files_for_review, lang))

    checklist = make_checklist(issues, languages)
    overall = overall_from_checklist(checklist)

    rr = ReviewResult(
        issues=issues,
        checklist=checklist,
        overall=overall,
        summary=f"Platforms: {', '.join(languages) if languages else 'Unknown'} | Issues: {len(issues)}",
    )

    top_20_files = sorted(list(files_for_review.keys()))[:20]

    report_id = str(uuid.uuid4())
    meta: Dict[str, str] = {
        "project_name": project_display_name,
        "prepared_by": prepared_by,
        "source_type": source_type,
        "repo_type": repo_type if source_type == "repo" else "",
        "repo_path": repo_path if source_type == "repo" else "",
        "branch_name": branch_name if source_type == "repo" else "",
        "languages": ", ".join(languages) if languages else "Unknown",
        "files_analyzed": str(len(entries) if hasattr(entries, "__len__") else 0),
        "text_files": str(len(text_files)),
        "msapps": str(len(msapps)),
        "debug_file_count_after_filter": str(len(files_for_review)),
        "debug_top_20_files": "\n".join(top_20_files),
    }

    REPORT_CACHE[report_id] = {"created": time.time(), "result": rr, "meta": meta}

    report = _report_for_template(rr, languages, files_scanned=len(text_files))
    issues_for_ui = _issues_for_template(issues)

    return render(
        request,
        "report.html",
        {"report_id": report_id, "meta": meta, "report": report, "issues": issues_for_ui},
    )


@router.get("/report/{report_id}", response_class=HTMLResponse)
def report_html(request: Request, report_id: str):
    _cleanup_cache()
    item = REPORT_CACHE.get(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="Report expired")

    rr = item["result"]
    meta: Dict[str, str] = item["meta"]

    languages = [x.strip().lower() for x in (meta.get("languages") or "").split(",") if x.strip()]
    report = _report_for_template(rr, languages, files_scanned=int(meta.get("text_files", "0") or "0"))
    issues_for_ui = _issues_for_template(rr.issues)

    return render(
        request,
        "report.html",
        {"report_id": report_id, "meta": meta, "report": report, "issues": issues_for_ui},
    )


# ✅ FIXED PDF ROUTE (no ".pdf" suffix)
@router.get("/report/{report_id}/pdf")
def report_pdf(report_id: str):
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
