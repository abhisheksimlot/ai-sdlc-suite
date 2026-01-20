from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PromptOptions:
    solution_name: str = "MSPP Auto-Generated Solution"
    publisher_prefix: str = "org"
    max_chars: int = 12000  # safe for textbox
    max_bullets: int = 18   # keep concise
    max_roles: int = 8
    max_capabilities: int = 16
    max_constraints: int = 12
    max_nfrs: int = 12


# --------------------------
# Helpers
# --------------------------
def _clean(s: str) -> str:
    s = (s or "").replace("\x00", " ").strip()
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for it in items:
        key = it.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it.strip())
    return out


def _extract_bullets(text: str) -> List[str]:
    """
    Extract bullet-like lines and requirement-y statements.
    """
    lines = [ln.strip() for ln in _clean(text).splitlines() if ln.strip()]
    bullets: List[str] = []

    for ln in lines:
        # obvious bullets
        if re.match(r"^(\-|\*|•|\d+\)|\d+\.)\s+", ln):
            bullets.append(re.sub(r"^(\-|\*|•|\d+\)|\d+\.)\s+", "", ln).strip())
            continue

        # AC style
        low = ln.lower()
        if "given" in low and "when" in low and "then" in low:
            bullets.append(ln)
            continue

        # "As a ... I want ... so that ..."
        if re.match(r"^as a\s+.+\s+i want\s+.+", low):
            bullets.append(ln)
            continue

        # short requirement sentences (heuristic)
        if any(k in low for k in ["must", "shall", "should", "required", "need to", "needs to"]):
            bullets.append(ln)
            continue

    return _dedupe_keep_order(bullets)


def _pick_sections(design: str, jira: str):
    """
    Heuristic extraction of:
    - context summary
    - personas
    - capabilities
    - constraints/integrations
    - NFRs
    """
    all_text = _clean(design + "\n\n" + jira)
    bullets = _extract_bullets(all_text)

    # Personas / roles (heuristics)
    personas = []
    for b in bullets:
        m = re.search(r"\b(as a|role:)\s+([A-Za-z0-9 \-/&_]+)", b, re.I)
        if m:
            role = m.group(2).strip()
            role = re.sub(r"[.,;:]+$", "", role)
            if 2 <= len(role) <= 60:
                personas.append(role)

    # Also extract from “Audience / Users / Roles”
    for ln in all_text.splitlines():
        low = ln.lower().strip()
        if any(h in low for h in ["audience", "user roles", "roles", "personas"]):
            # next lines often contain roles; keep lightweight by adding the heading line
            personas.append(re.sub(r"\s+", " ", ln.strip()))

    personas = _dedupe_keep_order(personas)

    # Capabilities (prefer functional requirements + AC + user stories)
    capabilities = []
    for b in bullets:
        low = b.lower()
        if any(k in low for k in ["create", "update", "delete", "view", "submit", "approve", "reject",
                                  "upload", "download", "notify", "dashboard", "report", "audit",
                                  "track", "search", "assign", "escalat", "remind", "integrat"]):
            capabilities.append(b)

    capabilities = _dedupe_keep_order(capabilities)

    # Constraints / integrations / platforms
    constraints = []
    for b in bullets:
        low = b.lower()
        if any(k in low for k in ["integrat", "api", "connector", "sso", "entra", "azure ad",
                                  "sharepoint", "email", "teams", "retention", "compliance",
                                  "dataverse", "dynamics", "erp", "crm"]):
            constraints.append(b)
    constraints = _dedupe_keep_order(constraints)

    # NFRs
    nfrs = []
    for b in bullets:
        low = b.lower()
        if any(k in low for k in ["performance", "scal", "availability", "uptime",
                                  "security", "encryption", "audit", "logging",
                                  "privacy", "gdpr", "retention", "backup", "monitor"]):
            nfrs.append(b)
    nfrs = _dedupe_keep_order(nfrs)

    # Context summary: take first few meaningful sentences from design overview-ish content
    # Keep it short and not a raw paste.
    summary_lines = []
    for ln in _clean(design).splitlines():
        if len(ln.strip()) < 4:
            continue
        # Prefer overview / scope / summary style lines
        if any(k in ln.lower() for k in ["overview", "scope", "summary", "objective", "purpose"]):
            summary_lines.append(ln.strip())
        if len(summary_lines) >= 6:
            break
    if not summary_lines:
        # fallback: first 3 non-empty lines
        for ln in _clean(design).splitlines()[:6]:
            if ln.strip():
                summary_lines.append(ln.strip())
            if len(summary_lines) >= 3:
                break

    context_summary = _dedupe_keep_order(summary_lines)

    return context_summary, personas, capabilities, constraints, nfrs


def _fmt_list(title: str, items: List[str], limit: int) -> str:
    items = [it.strip() for it in items if it.strip()]
    items = _dedupe_keep_order(items)[:limit]
    if not items:
        return f"{title}\n- (Not explicitly stated. Derive from the user stories and design doc.)"
    return title + "\n" + "\n".join([f"- {it}" for it in items])


def build_copilot_make_a_plan_prompt(
    design_doc_text: str,
    jira_stories_text: str,
    options: Optional[PromptOptions] = None,
) -> str:
    """
    Domain-agnostic "classic" Make-a-Plan prompt generator.
    It DOES NOT dump the full document; it extracts high-signal bullets and structures them.
    """
    opts = options or PromptOptions()
    design = _clean(design_doc_text)
    jira = _clean(jira_stories_text)

    context_summary, personas, capabilities, constraints, nfrs = _pick_sections(design, jira)

    prompt = f"""
ROLE
You are Microsoft Power Platform Copilot in “Make a plan” mode.
Act as an enterprise Power Platform Solution Architect + Lead Developer.

GOAL
Create a complete Power Platform solution based on the requirements below.

SOLUTION STANDARDS
- Solution Name: {opts.solution_name}
- Publisher Prefix: {opts.publisher_prefix}
- Dataverse-first unless explicitly stated otherwise
- ALM ready (Dev/Test/Prod): Environment Variables + Connection References
- Security: least privilege, role-based access, row-level security where needed
- Quality: error handling, logging, auditability, performance-friendly schema

DOMAIN CONTEXT (AUTO-SUMMARIZED)
{_fmt_list("", context_summary, opts.max_bullets).replace("\\n- ", "\\n- ").strip()}

{_fmt_list("PERSONAS / ROLES (AUTO-EXTRACTED)", personas, opts.max_roles)}

{_fmt_list("KEY CAPABILITIES (AUTO-EXTRACTED)", capabilities, opts.max_capabilities)}

{_fmt_list("CONSTRAINTS / INTEGRATIONS (AUTO-EXTRACTED)", constraints, opts.max_constraints)}

{_fmt_list("NON-FUNCTIONAL REQUIREMENTS (AUTO-EXTRACTED)", nfrs, opts.max_nfrs)}

WHAT TO BUILD (OUTPUT REQUIRED)
1) Output a “MAKE A PLAN” broken into phases with numbered tasks.
2) Then produce the detailed build blueprint:

PHASE 1: Dataverse Data Model
- Define tables + columns (type, required, default), relationships, choice fields, keys
- Define business rules/validation
- Define audit/history approach (Dataverse auditing + custom history tables if needed)

PHASE 2: Security Model
- Define security roles mapped to personas
- Define table permissions per role (CRUD)
- Define row-level access strategy (ownership/teams/hierarchies)

PHASE 3: Apps
- Recommend Model-driven vs Canvas based on requirements
- Provide sitemap/navigation
- Provide forms (tabs/sections), views (filters), dashboards (KPIs)
- If Canvas is used: screens, navigation, components, key Power Fx examples

PHASE 4: Automations (Cloud Flows)
- Identify all required automations from the user stories
- For each flow: trigger, steps, conditions, approvals, error handling, retries
- Use environment variables + connection references
- Add logging to a Dataverse log table

PHASE 5: Governance & ALM
- Solution structure, naming conventions, list of environment variables
- Import/export strategy, managed-solution readiness
- Deployment notes, risks, and controls

IMPORTANT RULES
- Do NOT paste back the Design Doc or raw stories.
- Convert requirements into concrete Power Platform artefacts and steps.
- Be explicit: names, schema, triggers, filters, formulas, variables.
- Ask at most 3 clarifying questions ONLY if absolutely required.

NOW START:
Output the “MAKE A PLAN” first, then the detailed build blueprint.
""".strip()

    # final safe cap
    if len(prompt) > opts.max_chars:
        prompt = prompt[:opts.max_chars].rsplit("\n", 1)[0].strip()

    return prompt
