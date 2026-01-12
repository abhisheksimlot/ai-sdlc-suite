from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

from app.ai_code_review.reviewers.base import Reviewer, Issue


def _find_line(text: str, needle: str) -> int:
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return 1
    return text.count("\n", 0, idx) + 1


def _contains_url(text: str) -> bool:
    return bool(re.search(r"https?://", text or "", re.IGNORECASE))


def _safe_parse_xml(xml_text: str) -> Optional[ET.Element]:
    try:
        return ET.fromstring(xml_text)
    except Exception:
        return None


class ModelDrivenAppReviewer(Reviewer):
    name = "model-driven-app-reviewer"

    def supports(self, language: str) -> bool:
        return language == "powerplatform"

    def review(self, files: Dict[str, str], language: str) -> List[Issue]:
        """
        Review Model-Driven App artifacts in a Power Platform solution export.
        Works in-memory, no extraction.
        """
        issues: List[Issue] = []

        # Common places where model-driven apps appear
        mda_paths = [
            p for p in files.keys()
            if p.lower().endswith(".xml")
            and (
                "/modeldrivenapps/" in p.lower()
                or "\\modeldrivenapps\\" in p.lower()
                or "appmodules" in p.lower()
                or "appmodule" in p.lower()
            )
        ]

        # If we cannot find dedicated files, fall back to customizations.xml check
        customizations_path = next((p for p in files.keys() if p.lower().endswith("customizations.xml")), None)
        if not mda_paths and customizations_path:
            txt = files[customizations_path]
            if "appmodule" in txt.lower():
                mda_paths = [customizations_path]

        if not mda_paths:
            # Not always present; only warn lightly if solution is powerplatform
            issues.append(Issue(
                language="powerplatform",
                file_path="(solution)",
                line_start=1,
                line_end=1,
                severity="LOW",
                category="Maintainability",
                title="No Model-Driven App artifacts detected",
                detail="Solution does not appear to contain Model-Driven App (AppModule) XML files. If expected, verify the app is included in the export.",
                remediation="Ensure the Model-Driven App is added to the solution and exported. Verify AppModule components are present.",
                confidence="Low",
                rule_id="MDA-NOT-FOUND",
            ))
            return issues

        # Review each found file
        for path in mda_paths:
            xml_text = files.get(path, "")
            root = _safe_parse_xml(xml_text)

            if root is None:
                issues.append(Issue(
                    language="powerplatform",
                    file_path=path,
                    line_start=1,
                    line_end=1,
                    severity="MEDIUM",
                    category="Reliability",
                    title="Model-Driven App XML could not be parsed",
                    detail="The XML file could not be parsed. The app definition might be corrupted or in an unexpected format.",
                    remediation="Re-export the solution, validate the file contents, and ensure it is well-formed XML.",
                    confidence="High",
                    rule_id="MDA-XML-PARSE",
                ))
                continue

            # Heuristic: check for minimal metadata
            # Different exports vary; we try multiple tag names.
            text_lower = xml_text.lower()

            # Name / label check
            has_name = any(k in text_lower for k in ["<name>", "displayname", "localizedname", "appmodule"])
            if not has_name:
                issues.append(Issue(
                    language="powerplatform",
                    file_path=path,
                    line_start=_find_line(xml_text, "<appmodule"),
                    line_end=_find_line(xml_text, "<appmodule"),
                    severity="LOW",
                    category="Maintainability",
                    title="Model-Driven App metadata appears minimal (name/display name not obvious)",
                    detail="Could not reliably detect display name/label metadata in the app definition.",
                    remediation="Ensure the app has clear display name, unique name, description, and versioning. Avoid cryptic internal names.",
                    confidence="Low",
                    rule_id="MDA-METADATA",
                ))

            # Sitemap check
            # Many exports include a reference to sitemap or site map XML.
            has_sitemap = ("sitemap" in text_lower) or ("site map" in text_lower) or ("sitemapproperties" in text_lower)
            if not has_sitemap:
                issues.append(Issue(
                    language="powerplatform",
                    file_path=path,
                    line_start=1,
                    line_end=1,
                    severity="MEDIUM",
                    category="Maintainability",
                    title="No Sitemap reference detected for Model-Driven App",
                    detail="A sitemap defines navigation for model-driven apps. Not detecting a sitemap reference may indicate default/empty navigation.",
                    remediation="Add/verify a Sitemap (areas, groups, subareas) appropriate for user journeys and roles.",
                    confidence="Medium",
                    rule_id="MDA-SITEMAP",
                ))

            # Hardcoded URLs (environment specific)
            if _contains_url(xml_text):
                issues.append(Issue(
                    language="powerplatform",
                    file_path=path,
                    line_start=_find_line(xml_text, "http"),
                    line_end=_find_line(xml_text, "http"),
                    severity="MEDIUM",
                    category="Maintainability",
                    title="Hardcoded URL detected in Model-Driven App XML",
                    detail="Found an absolute URL in the app definition. This may break across environments.",
                    remediation="Use environment variables or configuration records. Avoid embedding environment URLs in app metadata.",
                    confidence="Medium",
                    rule_id="MDA-HARDCODED-URL",
                ))

            # Component bloat (very rough): if huge file, flag maintainability/perf risk
            if len(xml_text) > 500_000:
                issues.append(Issue(
                    language="powerplatform",
                    file_path=path,
                    line_start=1,
                    line_end=1,
                    severity="LOW",
                    category="Performance",
                    title="Large Model-Driven App definition detected",
                    detail="App definition XML is very large; this can indicate many components (forms/views/dashboards) and may impact load/maintainability.",
                    remediation="Review included components. Keep app scope focused and use multiple apps if necessary.",
                    confidence="Low",
                    rule_id="MDA-LARGE",
                ))

        return issues
