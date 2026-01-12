import re
from typing import List

from app.ai_code_review.reviewers.base import Reviewer, Issue
from app.ai_code_review.utils.msapp_reader import read_msapp_in_memory, extract_canvas_formula_hits


# Heuristic patterns
URL_RE = re.compile(r"https?://", re.IGNORECASE)
SECRET_RE = re.compile(r"(api[_-]?key|client[_-]?secret|password|token)\s*[:=]", re.IGNORECASE)

DELEGATION_SMELLS = [
    "EndsWith(",
    "StartsWith(",
    " in ",
    "CountRows(",
    "ForAll(",
]

PERF_SMELLS = [
    ("LookUp(", "Repeated LookUp can be slow; cache results or use collections where appropriate."),
    ("ForAll(", "ForAll over large data can be slow; consider delegation/collections and minimize repeated evaluation."),
    ("Concurrent(", "Use carefully; check connector throttling, side effects, and data consistency."),
]

PATCH_SMELL = "Patch("
IFERROR = "IfError("


class CanvasMsappReviewer(Reviewer):
    """
    In-memory Canvas App (.msapp) reviewer.
    Reads the .msapp container (often ZIP-like), extracts JSON/text artifacts,
    finds likely Power Fx formulas/properties, and runs heuristic rules.
    """

    name = "canvas-msapp-reviewer"

    def supports(self, language: str) -> bool:
        return language == "powerplatform"

    def review_msapp(self, msapp_name: str, msapp_bytes: bytes) -> List[Issue]:
        issues: List[Issue] = []

        artifacts = read_msapp_in_memory(msapp_bytes)

        # If not parsable, return ONE clear warning only
        if not artifacts:
            return [Issue(
                language="powerplatform",
                file_path=msapp_name,
                line_start=1,
                line_end=1,
                severity="MEDIUM",
                category="Maintainability",
                title="Canvas app could not be parsed in memory",
                detail=(
                    "This .msapp could not be read as a ZIP-like package in memory. "
                    "The app may be in a legacy/encrypted format or the file is corrupted. "
                    "Deep formula/control analysis was skipped."
                ),
                remediation=(
                    "Re-export the Canvas app from Power Apps Studio. "
                    "If available, use an export format that supports unpacked sources, "
                    "or provide unpacked app sources for deeper analysis."
                ),
                confidence="High",
                rule_id="MSAPP-PARSE",
            )]

        # Extract “friendly” formula/property hits (best-effort)
        hits = extract_canvas_formula_hits(artifacts)

        if not hits:
            return [Issue(
                language="powerplatform",
                file_path=msapp_name,
                line_start=1,
                line_end=1,
                severity="LOW",
                category="Maintainability",
                title="Canvas app parsed, but no formulas detected by heuristics",
                detail=(
                    "The .msapp was parsed successfully, but formula extraction did not find recognizable "
                    "Power Fx patterns. Review may be incomplete."
                ),
                remediation="Enable enhanced extraction rules or provide unpacked sources for a richer review.",
                confidence="Medium",
                rule_id="MSAPP-NO-FX",
            )]

        for h in hits:
            # Friendly location already includes Screen/Control/Property when possible
            file_path = f"{msapp_name} :: {h.location}"
            line_start = int(h.line or 1)
            fx = (h.snippet or "").strip()

            # Hardcoded URL
            if URL_RE.search(fx):
                issues.append(Issue(
                    language="powerplatform",
                    file_path=file_path,
                    line_start=line_start,
                    line_end=line_start,
                    severity="MEDIUM",
                    category="Maintainability",
                    title="Hardcoded URL detected in Canvas formula/property",
                    detail="Found an absolute URL inside a Canvas formula/property; this often breaks across environments.",
                    remediation="Use environment variables or configuration values instead of hardcoded URLs.",
                    confidence="Medium",
                    rule_id="MSAPP-HARDCODED-URL",
                ))

            # Secret-like strings
            if SECRET_RE.search(fx):
                issues.append(Issue(
                    language="powerplatform",
                    file_path=file_path,
                    line_start=line_start,
                    line_end=line_start,
                    severity="HIGH",
                    category="Security",
                    title="Potential secret-like text detected in Canvas content",
                    detail="Found patterns resembling API keys/secrets/tokens. Secrets should not be embedded in Canvas apps.",
                    remediation="Move secrets to a secure backend (Key Vault via custom connector/function). Use connection references & env vars.",
                    confidence="Low",
                    rule_id="MSAPP-SECRET",
                ))

            # Patch without IfError
            if PATCH_SMELL in fx and IFERROR not in fx:
                issues.append(Issue(
                    language="powerplatform",
                    file_path=file_path,
                    line_start=line_start,
                    line_end=line_start,
                    severity="MEDIUM",
                    category="Reliability",
                    title="Patch() used without IfError() handling",
                    detail="Patch appears without IfError protection; failures may not be handled and users may not get feedback.",
                    remediation="Wrap Patch with IfError(..., Notify(...)) and handle failure paths properly.",
                    confidence="Medium",
                    rule_id="MSAPP-PATCH-IFERROR",
                ))

            # Delegation/performance smells (heuristic)
            for smell in DELEGATION_SMELLS:
                if smell in fx:
                    issues.append(Issue(
                        language="powerplatform",
                        file_path=file_path,
                        line_start=line_start,
                        line_end=line_start,
                        severity="MEDIUM",
                        category="Performance",
                        title="Potential delegation/performance smell in Canvas formula",
                        detail=f"Formula contains '{smell}' which can be non-delegable or slow depending on datasource size.",
                        remediation="Check delegation warnings in Studio. Prefer delegable queries; pre-filter server-side; cache with collections where safe.",
                        confidence="Low",
                        rule_id="MSAPP-DELEGATION",
                    ))
                    break

            # Other performance smells
            for token, suggestion in PERF_SMELLS:
                if token in fx:
                    issues.append(Issue(
                        language="powerplatform",
                        file_path=file_path,
                        line_start=line_start,
                        line_end=line_start,
                        severity="LOW",
                        category="Performance",
                        title=f"Performance smell: {token.rstrip('(')} usage",
                        detail="Pattern can be expensive depending on data size and frequency of evaluation.",
                        remediation=suggestion,
                        confidence="Low",
                        rule_id="MSAPP-PERF",
                    ))
                    break

        # Deduplicate identical issues (common when formulas repeat)
        dedup = []
        seen = set()
        for it in issues:
            key = (it.rule_id, it.file_path, it.line_start, it.title)
            if key not in seen:
                seen.add(key)
                dedup.append(it)

        return dedup
