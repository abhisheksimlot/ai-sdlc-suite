# ai-sdlc-suite/app/ai_code_review/reviewers/llm_fallback.py
from __future__ import annotations

import json
import os
from typing import Dict, List, Tuple

from openai import OpenAI

from .base import Reviewer, Issue


def _extract_first_json_object(text: str) -> str:
    if not text:
        return ""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start:end + 1]


def _stable_items(files: Dict[str, str]) -> List[Tuple[str, str]]:
    items = [(k, v) for k, v in (files or {}).items() if k and isinstance(v, str)]
    items.sort(key=lambda x: x[0])
    return items


def _chunk_files(
    files: Dict[str, str],
    *,
    max_total_chars_per_chunk: int = 55_000,
    max_chars_per_file: int = 12_000,
    max_chunks: int = 6,
) -> List[Dict[str, str]]:
    chunks: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    used = 0

    for path, content in _stable_items(files):
        if len(chunks) >= max_chunks:
            break

        lp = path.lower()
        if lp.endswith((".png", ".jpg", ".jpeg", ".gif", ".dll", ".exe", ".zip", ".pdf", ".pyc")):
            continue

        text = (content or "").strip()
        if not text:
            continue

        if len(text) > max_chars_per_file:
            text = text[:max_chars_per_file] + "\n\n[TRUNCATED: file too long]"

        if used + len(text) > max_total_chars_per_chunk and current:
            chunks.append(current)
            current = {}
            used = 0

        current[path] = text
        used += len(text)

    if current and len(chunks) < max_chunks:
        chunks.append(current)

    return chunks


def _default_remediation(category: str, title: str) -> str:
    c = (category or "").lower()
    t = (title or "").lower()

    if c == "security":
        if "secret" in t or "key" in t or "token" in t:
            return "Move secrets to environment variables/Key Vault. Rotate any exposed credentials."
        if "subprocess" in t:
            return "Validate/sanitize inputs and avoid shell=True. Prefer safe APIs and allowlists."
        return "Follow secure coding practices; validate inputs and reduce attack surface."

    if c == "performance":
        if "timeout" in t:
            return "Add timeouts to external calls/subprocess. Avoid unbounded waits."
        return "Profile hotspots; reduce repeated work; use caching/streaming where appropriate."

    if c == "reliability":
        if "silent" in t or "swallow" in t:
            return "Do not swallow exceptions. Log the error and return a clear, user-friendly message."
        return "Improve error handling and add logging/tests for failure paths."

    if c == "style":
        return "Align with coding standards (formatting, naming, lint rules) and run auto-formatters."

    # maintainability
    return "Refactor into smaller functions/modules, remove duplication, and add tests/documentation."


def _normalize_issue_dict(raw: dict) -> dict:
    """
    Accept common key variations from the model and normalize to Issue schema.
    Ensures file_path/line_start/line_end/remediation are always present.
    """
    file_path = (
        raw.get("file_path")
        or raw.get("file")
        or raw.get("path")
        or raw.get("filename")
        or ""
    )

    # line numbers
    line_start = raw.get("line_start") or raw.get("line") or raw.get("start_line") or 1
    line_end = raw.get("line_end") or raw.get("end_line") or line_start

    # remediation variations
    remediation = (
        raw.get("remediation")
        or raw.get("recommendation")
        or raw.get("fix")
        or raw.get("resolution")
        or ""
    )

    category = raw.get("category") or "Maintainability"
    title = raw.get("title") or raw.get("issue") or "LLM finding"
    detail = raw.get("detail") or raw.get("description") or title

    severity = (raw.get("severity") or "MEDIUM").upper()
    if severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        severity = "MEDIUM"

    confidence = raw.get("confidence") or "Medium"
    if confidence not in {"High", "Medium", "Low"}:
        confidence = "Medium"

    # If remediation still empty, generate a safe default
    if not remediation.strip():
        remediation = _default_remediation(category, title)

    # Ensure file_path is never empty (so UI doesn’t show —)
    if not str(file_path).strip():
        file_path = "UNKNOWN"

    # Normalize ints
    try:
        line_start = int(line_start)
    except Exception:
        line_start = 1
    try:
        line_end = int(line_end)
    except Exception:
        line_end = line_start

    if line_start <= 0:
        line_start = 1
    if line_end < line_start:
        line_end = line_start

    return {
        "language": raw.get("language") or "",
        "file_path": str(file_path),
        "line_start": line_start,
        "line_end": line_end,
        "severity": severity,
        "category": category,
        "title": title,
        "detail": detail,
        "remediation": remediation,
        "confidence": confidence,
        "rule_id": raw.get("rule_id") or raw.get("rule") or None,
    }


def _dedupe_issues(issues: List[Issue]) -> List[Issue]:
    seen = set()
    out: List[Issue] = []
    for it in issues:
        key = (
            (it.language or "").lower(),
            (it.file_path or "").lower(),
            int(it.line_start or 0),
            int(it.line_end or 0),
            (it.category or "").lower(),
            (it.title or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


class LLMFallbackReviewer(Reviewer):
    name = "llm-fallback"

    def __init__(self, model: str = "gpt-4.1-mini"):
        self.model = os.getenv("OPENAI_MODEL", model)
        self.client = OpenAI()

    def supports(self, language: str) -> bool:
        return True

    def review(self, files: Dict[str, str], language: str) -> List[Issue]:
        if not files:
            return []

        # Chunk to avoid truncation
        chunks = _chunk_files(files)

        system_prompt = (
            "You are a Senior Principal Engineer performing an enterprise code review.\n"
            "Return ONLY valid JSON. No markdown.\n"
            "CRITICAL REQUIREMENT: Every issue MUST include:\n"
            "- file_path (best match from provided file names)\n"
            "- line_start and line_end (estimate if needed, but do not omit)\n"
            "- remediation (specific fix steps)\n"
            "If you are unsure, set file_path to the closest file and line_start=1,line_end=1 and confidence=Low.\n"
        )

        all_issues: List[Issue] = []

        for idx, selected in enumerate(chunks, start=1):
            file_list = sorted(list(selected.keys()))
            user_payload = {
                "language_hint": language,
                "chunk": {"index": idx, "count": len(chunks)},
                "file_names_in_chunk": file_list,
                "instructions": [
                    "Find issues across Security, Reliability, Maintainability, Performance, and Style.",
                    "Be strict and thorough.",
                    "IMPORTANT: You must pick file_path only from file_names_in_chunk.",
                    "Provide line_start/line_end. If exact lines are unknown, estimate and set confidence Low.",
                ],
                "files": selected,
                "output_schema": {
                    "issues": [
                        {
                            "language": "string",
                            "file_path": "string (must match provided file names)",
                            "line_start": "int",
                            "line_end": "int",
                            "severity": "LOW|MEDIUM|HIGH|CRITICAL",
                            "category": "Security|Reliability|Maintainability|Performance|Style",
                            "title": "string",
                            "detail": "string",
                            "remediation": "string",
                            "confidence": "High|Medium|Low",
                        }
                    ]
                },
            }

            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload)},
                ],
                temperature=0.2,
            )

            txt = resp.choices[0].message.content or ""
            json_text = _extract_first_json_object(txt)
            if not json_text:
                continue

            try:
                payload = json.loads(json_text)
            except Exception:
                continue

            for raw in payload.get("issues", []) or []:
                if not isinstance(raw, dict):
                    continue
                norm = _normalize_issue_dict(raw)
                # Ensure language is set
                if not norm.get("language"):
                    norm["language"] = language

                try:
                    all_issues.append(Issue(**norm))
                except Exception:
                    # As a last resort, skip broken entries
                    continue

        return _dedupe_issues(all_issues)
