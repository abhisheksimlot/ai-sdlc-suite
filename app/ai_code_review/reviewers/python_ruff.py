# ai-sdlc-suite/app/ai_code_review/reviewers/python_ruff.py
from __future__ import annotations

import json
import os
import subprocess
from typing import Dict, List, Optional

from app.ai_code_review.reviewers.base import Reviewer, Issue


# --- Simple remediation hints for common Ruff families ---
RULE_HINTS = {
    "F401": "Remove unused import(s) or use them. Run: `ruff check --fix` if safe.",
    "F811": "Avoid redefinition. Rename the variable/function or remove the duplicate definition.",
    "E501": "Line too long. Wrap the line or refactor into smaller expressions.",
    "B006": "Avoid mutable default arguments. Use `None` and initialize inside the function.",
    "S105": "Possible hard-coded password/secret. Move to env vars/Key Vault and rotate the secret.",
    "S106": "Possible hard-coded password/secret. Move to env vars/Key Vault and rotate the secret.",
    "S107": "Possible hard-coded password/secret. Move to env vars/Key Vault and rotate the secret.",
}


def _category_from_code(code: str) -> str:
    c = (code or "").upper()
    # Security (bandit-like)
    if c.startswith("S"):
        return "Security"
    # Style
    if c.startswith(("E", "W")):
        return "Style"
    # Reliability / bugs
    if c.startswith(("F", "B")):
        return "Reliability"
    # Maintainability / complexity
    if c.startswith(("C90", "PL", "SIM")):
        return "Maintainability"
    return "Maintainability"


def _severity_from_code(code: str) -> str:
    c = (code or "").upper()
    if c.startswith("S"):
        return "HIGH"
    if c.startswith(("B", "F")):
        return "MEDIUM"
    if c.startswith(("E", "W")):
        return "LOW"
    return "MEDIUM"


class PythonRuffReviewer(Reviewer):
    name = "python-ruff"

    def supports(self, language: str) -> bool:
        return (language or "").lower() == "python"

    def review(self, files: Dict[str, str], language: str) -> List[Issue]:
        """
        Runs Ruff against the current working directory (repo) OR against extracted files
        if your pipeline writes them out. If Ruff can't run, returns a single Issue
        explaining what to do.
        """
        # Ruff needs a filesystem context. Most projects run the suite from repo root.
        # If you're running from elsewhere, set RUFF_WORKDIR env var to project root.
        workdir = os.getenv("RUFF_WORKDIR", os.getcwd())

        try:
            # JSON output gives us file + row + col reliably
            cmd = ["python", "-m", "ruff", "check", ".", "--output-format", "json"]
            proc = subprocess.run(
                cmd,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception as e:
            return [
                Issue(
                    language="python",
                    file_path="",
                    line_start=1,
                    line_end=1,
                    severity="MEDIUM",
                    category="Reliability",
                    title="Ruff could not be executed",
                    detail=f"Failed to run Ruff. Error: {e}",
                    remediation="Install Ruff: `python -m pip install ruff` and ensure the app runs from the project root.",
                    confidence="High",
                    rule_id="RUFF-EXEC",
                )
            ]

        # Ruff returns non-zero when issues found. That's OK.
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()

        if not stdout:
            # If ruff crashed, show why
            if proc.returncode not in (0, 1):  # 1 often means lint found
                return [
                    Issue(
                        language="python",
                        file_path="",
                        line_start=1,
                        line_end=1,
                        severity="MEDIUM",
                        category="Reliability",
                        title="Ruff execution failed",
                        detail=f"Ruff returned code {proc.returncode}. stderr: {stderr}",
                        remediation="Ensure Ruff is installed and runnable. Try: `python -m ruff check . --output-format json` from your repo root.",
                        confidence="High",
                        rule_id="RUFF-RUN",
                    )
                ]
            return []

        try:
            findings = json.loads(stdout)
        except Exception:
            return [
                Issue(
                    language="python",
                    file_path="",
                    line_start=1,
                    line_end=1,
                    severity="MEDIUM",
                    category="Reliability",
                    title="Ruff JSON output could not be parsed",
                    detail=f"Ruff output was not valid JSON. stderr: {stderr}",
                    remediation="Run `python -m ruff check . --output-format json` manually to verify JSON output.",
                    confidence="High",
                    rule_id="RUFF-JSON",
                )
            ]

        issues: List[Issue] = []
        for f in findings or []:
            code = (f.get("code") or "").strip()
            msg = (f.get("message") or "").strip()
            path = (f.get("filename") or "").replace("\\", "/")
            loc = f.get("location") or {}
            end_loc = f.get("end_location") or loc

            row = int(loc.get("row") or 1)
            end_row = int(end_loc.get("row") or row)

            title = f"{code}: {msg}" if code else (msg or "Ruff finding")
            remediation = RULE_HINTS.get(code, "Address this Ruff rule. Consider running: `ruff check --fix` if appropriate.")

            issues.append(
                Issue(
                    language="python",
                    file_path=path,
                    line_start=row,
                    line_end=end_row,
                    severity=_severity_from_code(code),
                    category=_category_from_code(code),
                    title=title,
                    detail=msg or title,
                    remediation=remediation,
                    confidence="High",
                    rule_id=code or "RUFF",
                )
            )

        return issues
