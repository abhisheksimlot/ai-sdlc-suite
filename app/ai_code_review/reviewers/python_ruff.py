import json
import subprocess
from typing import Dict, List

from .base import Reviewer, Issue


CATEGORY_MAP = {
    "E": "Style",
    "W": "Style",
    "F": "Reliability",
    "B": "Reliability",
    "S": "Security",
    "UP": "Maintainability",
    "PERF": "Performance",
    "C90": "Maintainability",
}


def _category_from_code(code: str) -> str:
    if not code:
        return "Maintainability"

    for prefix in ("PERF", "UP", "C90"):
        if code.startswith(prefix):
            return CATEGORY_MAP.get(prefix, "Maintainability")

    first = code[0]
    return CATEGORY_MAP.get(first, "Maintainability")


class PythonRuffReviewer(Reviewer):
    name = "python-ruff"

    def supports(self, language: str) -> bool:
        return language == "python"

    def review(self, files: Dict[str, str], language: str) -> List[Issue]:
        issues: List[Issue] = []

        for path, content in files.items():
            if not path.lower().endswith(".py"):
                continue

            cmd = ["ruff", "check", "--output-format=json", "--stdin-filename", path, "-"]
            proc = subprocess.run(
                cmd,
                input=content.encode("utf-8", errors="replace"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            if proc.returncode not in (0, 1):
                continue

            raw = proc.stdout.decode("utf-8", errors="replace").strip()
            if not raw:
                continue

            try:
                data = json.loads(raw)
            except Exception:
                continue

            for item in data:
                code = item.get("code") or ""
                msg = item.get("message") or "Lint issue"
                loc = item.get("location") or {}
                end = item.get("end_location") or loc

                line_start = int(loc.get("row") or 1)
                line_end = int(end.get("row") or line_start)

                category = _category_from_code(code)

                if category == "Security":
                    severity = "HIGH"
                elif category == "Style":
                    severity = "LOW"
                else:
                    severity = "MEDIUM"

                issues.append(
                    Issue(
                        language="python",
                        file_path=path,
                        line_start=line_start,
                        line_end=line_end,
                        severity=severity,
                        category=category,
                        title=f"{code}: {msg}".strip(": "),
                        detail=msg,
                        remediation="Fix per the lint message. Consider enabling autofix where safe.",
                        confidence="High",
                        rule_id=code or None,
                    )
                )

        return issues
