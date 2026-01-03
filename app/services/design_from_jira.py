from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
import importlib.util


def _load_module_from_path(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    return module


def _jira_items_to_text(jira_items: List[Dict[str, Any]]) -> str:
    """
    Your jira-design-doc expects one big jira_text string.
    We'll convert selected items to a readable text blob.
    """
    blocks = []
    for i, it in enumerate(jira_items, start=1):
        blocks.append(
            "\n".join(
                [
                    f"Item {i}",
                    f"Type: {it.get('type', 'Story')}",
                    f"Summary: {it.get('summary', '')}",
                    f"Priority: {it.get('priority', '')}",
                    "Description:",
                    str(it.get('description', '')).strip(),
                    "Acceptance Criteria:",
                    "\n".join(f"- {x}" for x in (it.get('acceptance_criteria') or [])),
                    "-" * 40,
                ]
            )
        )
    return "\n\n".join(blocks).strip()


def generate_design_docx(project_name: str, jira_items: List[Dict[str, Any]]) -> bytes:
    """
    Calls jira-design-doc/design_doc_logic.generate_design_doc_bytes(...)
    and returns DOCX bytes.
    """
    # ai-sdlc-suite/app/services/design_from_jira.py
    # parents[3] => ai-sdlc-suite (root)
    suite_root = Path(__file__).resolve().parents[2]  # .../ai-sdlc-suite/app
    suite_root = suite_root.parent  # .../ai-sdlc-suite
    projects_root = suite_root.parent  # .../projects

    design_logic_path = projects_root / "jira-design-doc" / "design_doc_logic.py"
    if not design_logic_path.exists():
        raise FileNotFoundError(f"Could not find {design_logic_path}")

    mod = _load_module_from_path("jira_design_doc_logic", design_logic_path)

    if not hasattr(mod, "generate_design_doc_bytes"):
        raise AttributeError(
            "Expected function generate_design_doc_bytes in jira-design-doc/design_doc_logic.py"
        )

    jira_text = _jira_items_to_text(jira_items)

    doc_bytes = mod.generate_design_doc_bytes(
        jira_text=jira_text,
        project_name=project_name or "PROJECT",
        version="1.0",
        prepared_by="Automation Factory",
    )

    if not isinstance(doc_bytes, (bytes, bytearray)):
        raise TypeError("generate_design_doc_bytes did not return bytes")

    return bytes(doc_bytes)
