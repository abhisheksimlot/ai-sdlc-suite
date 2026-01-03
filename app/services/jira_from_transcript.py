from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
import importlib.util
import sys


def _load_module_from_path(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore
    return module


def _map_requirements_to_items(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert jira-user-story output:
      { project_key, requirements:[{issue_type, summary, description, ...}] }
    into unified app output:
      { items:[{type, summary, description, acceptance_criteria, priority}] }
    """
    reqs: List[Dict[str, Any]] = data.get("requirements", []) or []

    items: List[Dict[str, Any]] = []
    for r in reqs:
        items.append(
            {
                "type": r.get("issue_type", "Story"),
                "summary": r.get("summary", ""),
                "description": r.get("description", ""),
                "acceptance_criteria": r.get("acceptance_criteria", []) or [],
                "priority": r.get("priority", "Medium"),
                # keep extras if you want later
                "id": r.get("id"),
                "story_points": r.get("story_points"),
                "dependencies": r.get("dependencies", []),
            }
        )

    return {
        "project_key": data.get("project_key", "PROJECT"),
        "items": items,
        "raw": data,  # optional: keeps original response for debugging
    }


def generate_jira_from_transcript(transcript_text: str) -> Dict[str, Any]:
    """
    Calls jira-user-story/main.py -> generate_requirements_from_text(raw_text)
    then maps to {items:[...]} for the unified web app.
    """
    # ai-sdlc-suite/app/services/jira_from_transcript.py
    suite_root = Path(__file__).resolve().parents[2]  # .../ai-sdlc-suite/app
    suite_root = suite_root.parent                    # .../ai-sdlc-suite
    projects_root = suite_root.parent                 # .../projects

    user_story_main = projects_root / "jira-user-story" / "main.py"
    if not user_story_main.exists():
        raise FileNotFoundError(f"Could not find {user_story_main}")

    # Important: allow imports inside jira-user-story (if it has any local modules later)
    sys.path.insert(0, str(user_story_main.parent))

    mod = _load_module_from_path("jira_user_story_main", user_story_main)

    if not hasattr(mod, "generate_requirements_from_text"):
        raise AttributeError(
            "Expected function 'generate_requirements_from_text' in jira-user-story/main.py"
        )

    data = mod.generate_requirements_from_text(transcript_text)
    if not isinstance(data, dict):
        raise TypeError("jira-user-story returned non-dict result")

    return _map_requirements_to_items(data)
