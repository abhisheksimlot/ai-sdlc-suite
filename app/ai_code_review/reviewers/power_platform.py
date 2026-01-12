import re
from typing import Dict, List

from .base import Reviewer, Issue


def _find_line(text: str, needle: str) -> int:
    """
    Best-effort: find approximate line number of needle.
    """
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return 1
    return text.count("\n", 0, idx) + 1


def _looks_like_hardcoded_url(value: str) -> bool:
    return bool(re.search(r"https?://", value or "", re.IGNORECASE))


def _has_secret_like(value: str) -> bool:
    # heuristic for secrets
    if not value:
        return False
    v = value.lower()
    return any(k in v for k in ["apikey", "api_key", "secret", "password", "token", "clientsecret", "client_secret"])


class PowerPlatformReviewer(Reviewer):
    name = "powerplatform-reviewer"

    def supports(self, language: str) -> bool:
        return language == "powerplatform"

    def review(self, files: Dict[str, str], language: str) -> List[Issue]:
        issues: List[Issue] = []

        # Review solution.xml / customizations.xml presence
        sol_xml = None
        sol_path = None
        for p, c in files.items():
            if p.lower().endswith("solution.xml"):
                sol_xml = c
                sol_path = p
                break

        if sol_xml and sol_path:
            # Basic checks: managed/unmanaged markers, publisher info etc. (heuristics)
            if "<Publisher>" not in sol_xml and "<publisher>" not in sol_xml:
                issues.append(Issue(
                    language="powerplatform",
                    file_path=sol_path,
                    line_start=_find_line(sol_xml, "<Solution"),
                    line_end=_find_line(sol_xml, "<Solution"),
                    severity="MEDIUM",
                    category="Maintainability",
                    title="Solution metadata incomplete (Publisher not found)",
                    detail="solution.xml does not appear to contain Publisher metadata. This can affect ALM traceability and governance.",
                    remediation="Ensure Solution has correct Publisher, unique prefix, versioning strategy, and managed/unmanaged governance.",
                    confidence="Medium",
                    rule_id="PP-SOLUTION-METADATA",
                ))

        # ✅ IMPORTANT:
        # Canvas apps (.msapp) are reviewed by CanvasMsappReviewer (Option A in-memory parser).
        # We do NOT add a duplicate “.msapp not inspected” issue here anymore.

        # Review workflow JSON (Power Automate flows in solution often appear under Workflows/*.json)
        workflow_json_paths = [
            p for p in files.keys()
            if p.lower().endswith(".json") and ("/workflows/" in p.lower() or "\\workflows\\" in p.lower())
        ]

        for p in workflow_json_paths:
            content = files[p]

            # 1) Hardcoded URLs
            if _looks_like_hardcoded_url(content):
                issues.append(Issue(
                    language="powerplatform",
                    file_path=p,
                    line_start=_find_line(content, "http"),
                    line_end=_find_line(content, "http"),
                    severity="MEDIUM",
                    category="Maintainability",
                    title="Hardcoded URL found in flow definition",
                    detail="Flow JSON appears to contain an absolute URL. This may break across environments and violates ALM best practice.",
                    remediation="Use environment variables or configuration values. Avoid hardcoding environment-specific URLs in actions/triggers.",
                    confidence="Medium",
                    rule_id="PP-FLOW-HARDCODED-URL",
                ))

            # 2) Potential secrets in JSON
            if _has_secret_like(content):
                issues.append(Issue(
                    language="powerplatform",
                    file_path=p,
                    line_start=_find_line(content, "secret"),
                    line_end=_find_line(content, "secret"),
                    severity="HIGH",
                    category="Security",
                    title="Potential secret-like key/value in flow JSON",
                    detail="Flow definition contains keys/fields that resemble secrets (token/password/client secret). Secrets should not be embedded.",
                    remediation="Move secrets to Azure Key Vault or secure inputs. Use connection references and environment variables for configuration.",
                    confidence="Medium",
                    rule_id="PP-FLOW-SECRET",
                ))

            # 3) Retry policy absent (very rough)
            if "retryPolicy" not in content and "retry" not in content.lower():
                issues.append(Issue(
                    language="powerplatform",
                    file_path=p,
                    line_start=1,
                    line_end=1,
                    severity="LOW",
                    category="Reliability",
                    title="No explicit retry policy detected",
                    detail="Flow actions may not be configured with retry policy. In enterprise scenarios, transient failures are common.",
                    remediation="Set appropriate retry policy where supported and implement robust error handling with run-after branches.",
                    confidence="Low",
                    rule_id="PP-FLOW-RETRY",
                ))

            # 4) Run-after / error handling hints
            if "runAfter" not in content:
                issues.append(Issue(
                    language="powerplatform",
                    file_path=p,
                    line_start=1,
                    line_end=1,
                    severity="LOW",
                    category="Reliability",
                    title="Limited error-handling structure detected (runAfter missing)",
                    detail="Flow definition does not include 'runAfter' patterns. This may indicate limited error handling (no try/catch scopes).",
                    remediation="Use Scope actions for Try/Catch/Finally, configure runAfter for failure paths, and log errors to a central store.",
                    confidence="Low",
                    rule_id="PP-FLOW-RUNAFTER",
                ))

        # Review Environment Variable XML
        env_defs = [
            p for p in files.keys()
            if "/environmentvariabledefinitions/" in p.lower() and p.lower().endswith(".xml")
        ]
        env_vals = [
            p for p in files.keys()
            if "/environmentvariablevalues/" in p.lower() and p.lower().endswith(".xml")
        ]

        if env_defs and not env_vals:
            p = env_defs[0]
            content = files[p]
            issues.append(Issue(
                language="powerplatform",
                file_path=p,
                line_start=1,
                line_end=1,
                severity="MEDIUM",
                category="Maintainability",
                title="Environment variable definitions present but values missing",
                detail="Solution includes Environment Variable Definitions but no corresponding values package. Deployment may fail or require manual setup.",
                remediation="Provide sensible default values (where appropriate) and document environment-specific overrides. Validate during CI/CD import.",
                confidence="Medium",
                rule_id="PP-ENV-VARS",
            ))

        # Connection references review
        conn_refs = [p for p in files.keys() if "/connectionreferences/" in p.lower() and p.lower().endswith(".xml")]
        if not conn_refs:
            issues.append(Issue(
                language="powerplatform",
                file_path=sol_path or "solution.xml",
                line_start=1,
                line_end=1,
                severity="LOW",
                category="Maintainability",
                title="Connection References not detected",
                detail="Connection References help make solutions environment-agnostic. Not finding them may indicate hard bindings to connections.",
                remediation="Use Connection References for flows and canvas apps to support proper ALM across Dev/Test/Prod.",
                confidence="Low",
                rule_id="PP-CONN-REFS",
            ))

        return issues
