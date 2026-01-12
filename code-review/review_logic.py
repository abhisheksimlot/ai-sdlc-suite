import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from openai import OpenAI


# -----------------------------
# Errors
# -----------------------------
class StandardsDocInvalidError(Exception):
    pass


# -----------------------------
# Config
# -----------------------------
MODEL_VALIDATE = "gpt-4.1-mini"
MODEL_REVIEW = "gpt-4.1-mini"

EXCLUDE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "node_modules", "dist", "build"
}
MAX_FILES = 180
MAX_FILE_CHARS = 35_000  # keep token usage sane


# -----------------------------
# Utilities
# -----------------------------
def _read_docx_text(docx_path: Path) -> str:
    doc = Document(str(docx_path))
    parts: List[str] = []
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if t:
            parts.append(t)
    return "\n".join(parts)


def _iter_py_files(repo_root: Path) -> List[Path]:
    out: List[Path] = []
    for p in repo_root.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        out.append(p)
        if len(out) >= MAX_FILES:
            break
    return out


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="ignore")


def _rel(repo_root: Path, f: Path) -> str:
    return str(f.relative_to(repo_root)).replace("\\", "/")


def _line_number(text: str, idx: int) -> int:
    return text[:idx].count("\n") + 1


def _extract_json_object(text: str) -> str:
    """
    Extract first JSON object between first { and last }.
    """
    if not text:
        return ""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start:end + 1]


def _get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=api_key)


# -----------------------------
# Stage 1: LLM validation
# -----------------------------
def llm_validate_standards_doc(doc_text: str) -> Dict[str, Any]:
    """
    Returns:
      {
        "is_standards_doc": bool,
        "confidence": 0-1,
        "reasons": [..],
        "document_type": "python_coding_standards" | "generic_tech_doc" | ...
      }
    """
    client = _get_client()

    system = (
        "You are a senior software engineering standards reviewer. "
        "Your task is to judge whether the provided text is a genuine "
        "Python coding standards / best practices / engineering guidelines document. "
        "Return ONLY JSON."
    )

    user = f"""
Decide if the following text looks like a Python best-practices / coding standards / engineering guidelines document.

Requirements:
- It should contain normative language: MUST/SHOULD/SHALL/DO/DON'T, rules, conventions, standards, checklists.
- It should have structure: sections about formatting, naming, testing, security, logging, error handling, architecture, etc.
- If it looks like an unrelated document (meeting notes, transcript, generic content), mark invalid.

Return JSON strictly in this schema:
{{
  "is_standards_doc": true/false,
  "confidence": 0.0-1.0,
  "document_type": "python_coding_standards" | "generic_tech_doc" | "transcript" | "requirements" | "other",
  "reasons": ["short reason 1", "short reason 2", ...],
  "missing_expected_sections": ["security", "testing", ...]
}}

TEXT:
\"\"\"{doc_text[:9000]}\"\"\"
"""

    resp = client.chat.completions.create(
        model=MODEL_VALIDATE,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
    )

    raw = resp.choices[0].message.content or ""
    js = _extract_json_object(raw)
    if not js:
        # be strict: if model didn't comply, treat as invalid
        return {
            "is_standards_doc": False,
            "confidence": 0.0,
            "document_type": "other",
            "reasons": ["Could not parse validator output as JSON."],
            "missing_expected_sections": [],
        }

    try:
        data = json.loads(js)
    except Exception:
        return {
            "is_standards_doc": False,
            "confidence": 0.0,
            "document_type": "other",
            "reasons": ["Validator returned invalid JSON."],
            "missing_expected_sections": [],
        }

    return data


# -----------------------------
# Build compact code pack (token-safe)
# -----------------------------
def build_code_pack(repo_root: Path) -> Dict[str, Any]:
    """
    Collects:
    - file list
    - quick heuristics findings to provide evidence/snippets
    - small snippets of important files
    """
    py_files = _iter_py_files(repo_root)

    file_index: List[Dict[str, Any]] = []
    snippets: List[Dict[str, Any]] = []
    quick_findings: List[Dict[str, Any]] = []

    secret_rx = re.compile(r"(?i)\b(api[_-]?key|secret|password)\b\s*=\s*['\"][^'\"]+['\"]")
    print_rx = re.compile(r"(?m)^\s*print\(")
    todo_rx = re.compile(r"(?i)\b(TODO|FIXME)\b")
    bare_except_rx = re.compile(r"except\s*:\s*")
    broad_except_rx = re.compile(r"except\s+Exception\s*:")

    for f in py_files:
        rel = _rel(repo_root, f)
        txt = _read_text(f)[:MAX_FILE_CHARS]
        lines = txt.splitlines()

        file_index.append({
            "path": rel,
            "lines": len(lines),
            "chars": len(txt),
        })

        # Snippet: header + first 80 lines is usually enough for LLM context
        head = "\n".join(lines[:80])
        snippets.append({"path": rel, "snippet_type": "head", "content": head})

        # Quick pattern hits with line numbers
        for rx, rule_name in [
            (secret_rx, "possible_secret"),
            (print_rx, "print_statement"),
            (todo_rx, "todo_fixme"),
            (bare_except_rx, "bare_except"),
            (broad_except_rx, "broad_exception"),
        ]:
            m = rx.search(txt)
            if m:
                ln = _line_number(txt, m.start())
                evidence = txt[m.start():m.start()+140].replace("\n", " ")
                quick_findings.append({
                    "path": rel,
                    "rule": rule_name,
                    "line": ln,
                    "evidence": evidence
                })

    # Keep size under control
    snippets = snippets[:50]
    quick_findings = quick_findings[:120]

    return {
        "file_index": file_index,
        "snippets": snippets,
        "quick_findings": quick_findings,
        "stats": {
            "python_files_scanned": len(py_files),
        }
    }


# -----------------------------
# Stage 2: LLM standards-driven review
# -----------------------------
def llm_generate_review_report(
    standards_text: str,
    code_pack: Dict[str, Any],
    project_name: str,
    prepared_by: str,
) -> Dict[str, Any]:
    """
    Returns strict JSON:
    {
      "project_name": str,
      "overall_status": "Pass"|"Fail",
      "summary": str,
      "issues": [
        {
          "category": str,
          "severity": "Critical"|"High"|"Medium"|"Low",
          "title": str,
          "description": str,
          "file_path": str|null,
          "line": int|null,
          "recommendation": str
        }
      ],
      "checklist": [
        {
          "category": str,
          "check": str,
          "status": "Pass"|"Fail"|"Not Found",
          "evidence": str|null,
          "remediation": str|null
        }
      ]
    }
    """
    client = _get_client()

    system = (
        "You are an enterprise code reviewer. "
        "Use the provided coding standards text as the rubric. "
        "Assess the code evidence and produce a detailed code review report. "
        "Return ONLY valid JSON. Do not include markdown."
    )

    # Keep standards truncated but representative; you can chunk/RAG later.
    standards_for_prompt = standards_text[:12000]

    user = f"""
You are given:
1) CODING STANDARDS (rubric) text
2) A CODE PACK (file list + representative snippets + quick pattern findings)

Task:
- Generate a DETAILED code review report guided by the standards.
- Categorise issues/checks, assign severity, and provide suggested resolution.
- Provide a final checklist with Pass/Fail/Not Found.
- Provide overall Pass/Fail.

Severity guidance (enterprise):
- Critical: security/credential exposure, RCE/injection, major compliance breach
- High: serious reliability/security concerns likely to cause incidents
- Medium: maintainability/test gaps, error handling weaknesses
- Low: style/readability/nits
Checklist status rules (VERY IMPORTANT):
- Use "Fail" only when you have evidence of a violation in the code pack.
- Use "Pass" only when you have positive evidence that the project meets the check.
- Use "Not Found" when you cannot find evidence either way (e.g., no README found, no CI config found, no tests folder found).
- Do NOT mark checks as "Fail" just because evidence is missing.

Output JSON schema EXACTLY:
{{
  "project_name": "{project_name}",
  "prepared_by": "{prepared_by}",
  "overall_status": "Pass" | "Fail",
  "summary": "string",
  "issues": [
    {{
      "category": "Security|Reliability|Maintainability|Testing|Performance|Architecture|Observability|Code Style|DevOps|Documentation|Other",
      "severity": "Critical|High|Medium|Low",
      "title": "string",
      "description": "string",
      "file_path": "string or null",
      "line": "number or null",
      "recommendation": "string"
    }}
  ],
  "checklist": [
    {{
      "category": "string",
      "check": "string",
      "status": "Pass|Fail|Not Found",
      "evidence": "string or null",
      "remediation": "string or null"
    }}
  ]
}}

CODING STANDARDS:
\"\"\"{standards_for_prompt}\"\"\"

CODE PACK (JSON):
{json.dumps(code_pack, ensure_ascii=False)[:12000]}
"""

    resp = client.chat.completions.create(
        model=MODEL_REVIEW,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )

    raw = resp.choices[0].message.content or ""
    js = _extract_json_object(raw)
    if not js:
        raise RuntimeError("LLM did not return valid JSON for the review report.")
    try:
        data = json.loads(js)
    except Exception:
        raise RuntimeError("LLM returned invalid JSON for the review report.")

    # Minimal sanity checks
    if "overall_status" not in data or "issues" not in data or "checklist" not in data:
        raise RuntimeError("LLM report JSON missing required fields.")

    return data


# -----------------------------
# Public entrypoint used by main.py
# -----------------------------
def generate_code_review_report(
    standards_docx_path: Path,
    repo_root: Path,
    project_name: str,
    prepared_by: str,
) -> Dict[str, Any]:
    standards_text = _read_docx_text(standards_docx_path)

    # Stage 1: Validate standards doc using LLM
    verdict = llm_validate_standards_doc(standards_text)

    # Tune threshold as desired
    if not verdict.get("is_standards_doc", False) or float(verdict.get("confidence", 0.0)) < 0.55:
        raise StandardsDocInvalidError()

    # Stage 2: Build token-safe code pack and run standards-driven review
    code_pack = build_code_pack(repo_root)

    report = llm_generate_review_report(
        standards_text=standards_text,
        code_pack=code_pack,
        project_name=project_name,
        prepared_by=prepared_by,
    )
    # ✅ Normalize checklist first (convert NA -> Not Found etc.)
    normalize_checklist(report)

    # ✅ Recompute overall status using our policy
        # (Not Found will NOT fail)
    report["overall_status"] = compute_overall_status(report)

    

    # Keep validator verdict for audit (don’t display it on UI unless you want)
    report["_standards_validation"] = {
        "document_type": verdict.get("document_type"),
        "confidence": verdict.get("confidence"),
        "reasons": verdict.get("reasons", []),
        "missing_expected_sections": verdict.get("missing_expected_sections", []),
    }
    return report
def normalize_checklist(report: Dict[str, Any]) -> None:
    """
    Converts any non-standard checklist status to:
    Pass / Fail / Not Found
    """
    checklist = report.get("checklist") or []

    for c in checklist:
        s = (c.get("status") or "").strip().lower()

        if s in {"na", "n/a", "notfound", "not_found", ""}:
            c["status"] = "Not Found"
        elif s == "pass":
            c["status"] = "Pass"
        elif s == "fail":
            c["status"] = "Fail"
        elif s == "not found":
            c["status"] = "Not Found"
        else:
            c["status"] = "Not Found"

def compute_overall_status(report: Dict[str, Any]) -> str:
    """
    Computes overall Pass/Fail using app policy.
    IMPORTANT: 'Not Found' checklist items do NOT fail the review.
    """

    issues = report.get("issues") or []
    checklist = report.get("checklist") or []

    # Rule 1: Any Critical issue => Fail
    if any((i.get("severity") or "").strip() == "Critical" for i in issues):
        return "Fail"

    # Rule 2: If you want, define a threshold for High issues
    high_count = sum(1 for i in issues if (i.get("severity") or "").strip() == "High")
    if high_count >= 2:
        return "Fail"

    # Rule 3: Checklist Fail => Fail
    # Not Found DOES NOT count
    if any((c.get("status") or "").strip() == "Fail" for c in checklist):
        return "Fail"

    # Otherwise Pass
    return "Pass"
