from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI


def _read_txt_bytes(b: bytes) -> str:
    try:
        return b.decode("utf-8")
    except Exception:
        return b.decode("latin-1", errors="ignore")


def extract_text_from_docx(docx_bytes: bytes) -> str:
    try:
        from docx import Document  # python-docx
    except Exception as e:
        raise RuntimeError(
            "DOCX support is not available because python-docx is missing. "
            "Install it with: pip install python-docx"
        ) from e

    from io import BytesIO
    doc = Document(BytesIO(docx_bytes))
    parts: List[str] = []
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if t:
            parts.append(t)
    return "\n".join(parts).strip()


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    PDF text extraction (no OCR).
    Uses PyPDF2 if available.
    """
    try:
        import PyPDF2
    except Exception as e:
        raise RuntimeError(
            "PDF support is not available because PyPDF2 is missing. "
            "Install it with: pip install PyPDF2"
        ) from e

    from io import BytesIO
    reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
    parts: List[str] = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        txt = txt.strip()
        if txt:
            parts.append(txt)
    return "\n".join(parts).strip()


def extract_text(filename: str, content_type: str, content: bytes) -> str:
    name = (filename or "").lower()
    ctype = (content_type or "").lower()

    if name.endswith(".docx") or "word" in ctype or "officedocument" in ctype:
        return extract_text_from_docx(content)

    if name.endswith(".pdf") or "pdf" in ctype:
        return extract_text_from_pdf(content)

    # Default: treat as text
    return _read_txt_bytes(content)


def _safe_json_loads(s: str) -> Dict[str, Any]:
    """
    Extract first JSON object from a response that may contain extra text.
    """
    s = (s or "").strip()
    if not s:
        raise ValueError("Empty AI response.")

    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("AI response did not contain valid JSON.")
    raw = s[start : end + 1]
    return json.loads(raw)


def _build_prompt(jira_text: str, design_text: str, extra_text: str) -> Tuple[str, str]:
    system = """
You are a senior QA lead generating SIT (System Integration Testing) test cases.

Goals:
- Produce comprehensive SIT coverage based on Jira user stories + acceptance criteria + design document
- Include functional test cases, positive & negative scenarios, edge cases
- Include Gherkin scenarios (Given/When/Then)
- Make test steps clear, unambiguous, and implementable
- Consider integrations, data validation, error handling, permissions, audit/logging, performance basics

Output MUST be JSON only, matching the schema exactly.
Do not include markdown.
""".strip()

    schema = """
JSON schema (return exactly):
{
  "summary": {
    "scope_notes": "string",
    "assumptions": ["string", "..."],
    "out_of_scope": ["string", "..."]
  },
  "test_cases": [
    {
      "id": "TC-001",
      "category": "Functional|Negative|Edge|Integration|Security|Data|Performance|Regression",
      "title": "string",
      "story_refs": ["JIRA-123", "..."],
      "priority": "High|Medium|Low",
      "preconditions": ["string", "..."],
      "test_data": ["string", "..."],
      "steps": ["string", "..."],
      "expected_results": ["string", "..."],
      "notes": ["string", "..."],
      "gherkin": [
        {
          "feature": "string",
          "scenario": "string",
          "given": ["string", "..."],
          "when": ["string", "..."],
          "then": ["string", "..."]
        }
      ]
    }
  ]
}
""".strip()

    user = f"""
INPUTS:

1) Jira stories / requirements:
<<<JIRA>>>
{jira_text}
<<<END_JIRA>>>

2) Design document:
<<<DESIGN>>>
{design_text}
<<<END_DESIGN>>>

3) Other info (context, environments, constraints, APIs, data rules, etc.):
<<<EXTRA>>>
{extra_text}
<<<END_EXTRA>>>

INSTRUCTIONS:
- Generate a comprehensive SIT test suite.
- Ensure strong positive + negative + edge cases.
- Where possible, include integration-specific checks.
- For story_refs: extract Jira keys if present (like ABC-123). If not present, use ["N/A"].
- Gherkin should be included for each test case (at least 1 scenario).
- Keep steps atomic and testable.
- Output JSON only following the schema exactly.
""".strip()

    return system, schema + "\n\n" + user


def generate_sit_test_cases(
    jira_text: str,
    design_text: str,
    extra_text: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY environment variable. Please set it and restart the app.")

    client = OpenAI(api_key=api_key)

    system, user = _build_prompt(jira_text, design_text, extra_text)
    use_model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    resp = client.chat.completions.create(
        model=use_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
    )

    content = resp.choices[0].message.content if resp.choices else ""
    data = _safe_json_loads(content)

    # Basic validation
    if "test_cases" not in data or not isinstance(data["test_cases"], list):
        raise ValueError("AI output JSON was missing 'test_cases' list.")
    return data
