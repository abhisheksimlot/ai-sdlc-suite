import json
from typing import Dict, List

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


class LLMFallbackReviewer(Reviewer):
    name = "llm-fallback"

    def __init__(self, model: str = "gpt-4.1-mini"):
        self.model = model
        self.client = OpenAI()

    def supports(self, language: str) -> bool:
        return True

    def review(self, files: Dict[str, str], language: str) -> List[Issue]:
        # Keep payload size controlled
        selected: Dict[str, str] = {}
        max_total_chars = 120_000
        max_per_file = 18_000
        used = 0

        for path, content in files.items():
            if used >= max_total_chars:
                break
            if path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".dll", ".exe", ".zip", ".pdf")):
                continue

            chunk = content[:max_per_file]
            selected[path] = chunk
            used += len(chunk)

        system_prompt = (
            "You are a senior software engineer performing a strict enterprise code review. "
            "Return ONLY valid JSON (no markdown). "
            "You MUST include file_path and line numbers. "
            "If line numbers are estimated, set confidence to Low."
        )

        user_payload = {
            "language_hint": language,
            "instructions": [
                "Find issues in security, reliability, maintainability, performance, and style.",
                "For each issue include: file_path, line_start, line_end, severity, category, title, detail, remediation, confidence.",
                "If uncertain about exact lines, estimate and set confidence Low."
            ],
            "files": selected,
            "output_schema": {
                "issues": [
                    {
                        "language": "string",
                        "file_path": "string",
                        "line_start": "int",
                        "line_end": "int",
                        "severity": "LOW|MEDIUM|HIGH|CRITICAL",
                        "category": "Security|Reliability|Maintainability|Performance|Style",
                        "title": "string",
                        "detail": "string",
                        "remediation": "string",
                        "confidence": "High|Medium|Low",
                        "rule_id": "string|null"
                    }
                ]
            }
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
            return []

        try:
            payload = json.loads(json_text)
        except Exception:
            return []

        out: List[Issue] = []
        for it in payload.get("issues", []):
            try:
                it.setdefault("language", language)
                it.setdefault("rule_id", None)
                out.append(Issue(**it))
            except Exception:
                continue

        return out
