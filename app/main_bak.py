from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Optional, List, Tuple

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------
SUITE_APP_DIR = Path(__file__).resolve().parent          # .../ai-sdlc-suite/app
REPO_ROOT = SUITE_APP_DIR.parent                         # .../ai-sdlc-suite


def _first_existing(candidates: List[Path]) -> Optional[Path]:
    for p in candidates:
        if p.exists() and p.is_file():
            return p
    return None


def _import_fastapi_app_from_package(module_path: str):
    """
    Import a FastAPI app from a Python package module path like:
      app.jira_design_doc.main
    This preserves relative imports inside that module/package.
    """
    import sys

    # Ensure repo root is on sys.path so 'app.<module>' imports work
    repo_root_str = str(REPO_ROOT)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)

    mod = importlib.import_module(module_path)

    if not hasattr(mod, "app"):
        raise AttributeError(f"{module_path} does not define a FastAPI variable named 'app'")

    return getattr(mod, "app")


def import_fastapi_app_from_file(app_file: Path, module_name: str):
    """
    Loads a Python file as a uniquely-named module and returns its FastAPI `app`.
    NOTE: This does NOT support relative imports like 'from .x import y'
    unless the module is loaded as a package. Use package import when possible.
    """
    import sys
    import time

    app_dir = str(app_file.parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    unique_name = f"{module_name}_{int(time.time() * 1000)}"

    spec = importlib.util.spec_from_file_location(unique_name, str(app_file))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for: {app_file}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore

    if not hasattr(mod, "app"):
        raise AttributeError(f"{app_file} does not define a FastAPI variable named 'app'")

    return mod.app


def stub_app(name: str, expected: str) -> FastAPI:
    """
    Fallback app so the suite starts even if a module is missing.
    """
    a = FastAPI(title=f"{name} (Missing)")

    @a.get("/", response_class=HTMLResponse)
    def _missing():
        return HTMLResponse(
            f"""
            <html>
              <head><title>{name} missing</title></head>
              <body style="font-family: Arial; padding: 24px;">
                <h2>{name} module is missing</h2>
                <p>I couldn't load the entry module at:</p>
                <pre>{expected}</pre>
                <p>
                  Fix by placing <b>main.py</b> in that folder, or update the path candidates in <b>app/main.py</b>.
                </p>
              </body>
            </html>
            """
        )

    return a


def load_module_app(
    display_name: str,
    module_key: str,
    candidates: List[Path],
    package_import: Optional[str] = None,
) -> FastAPI:
    """
    Try to load an app from:
      1) package import (if provided) - supports relative imports
      2) first existing file candidate
    If none found or import fails, return stub app.
    """
    # 1) Prefer package import if provided
    if package_import:
        try:
            return _import_fastapi_app_from_package(package_import)
        except Exception:
            # fall back to file candidates
            pass

    # 2) File fallback
    app_file = _first_existing(candidates)
    if not app_file:
        expected = str(candidates[0])
        return stub_app(display_name, expected)

    try:
        return import_fastapi_app_from_file(app_file, module_key)
    except Exception as e:
        # If file exists but fails import, show error detail
        return stub_app(display_name, f"{app_file}\n\nImport error:\n{e}")


# ------------------------------------------------------------
# Suite app
# ------------------------------------------------------------
suite = FastAPI(title="AI SDLC Suite")
templates = Jinja2Templates(directory=str(SUITE_APP_DIR / "templates"))


# ✅ Render-safe health endpoints (GET + HEAD)
@suite.get("/healthz")
def healthz_get():
    return {"status": "ok"}

@suite.head("/healthz")
def healthz_head():
    return Response(status_code=200)

# ✅ Render sometimes calls HEAD /
@suite.head("/")
def head_root():
    return Response(status_code=200)


@suite.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ------------------------------------------------------------
# Load sibling apps safely
# ------------------------------------------------------------

# ✅ FIXED: load as package so relative imports work (NO logic changes in module)
user_story_app = load_module_app(
    "User Story Generator",
    "jira_user_story",
    candidates=[
        REPO_ROOT / "jira-user-story" / "main.py",
        REPO_ROOT / "jira-user-story" / "app.py",
        REPO_ROOT / "jira_user_story" / "main.py",
        REPO_ROOT / "jira_user_story" / "app.py",
        REPO_ROOT / "app" / "jira-user-story" / "main.py",
        REPO_ROOT / "app" / "jira-user-story" / "app.py",
        REPO_ROOT / "app" / "jira_user_story" / "main.py",
        REPO_ROOT / "app" / "jira_user_story" / "app.py",
    ],
    package_import="app.jira_user_story.main",
)

# ✅ FIXED: load as package so relative imports work (NO logic changes in module)
design_doc_app = load_module_app(
    "Design Doc Generator",
    "jira_design_doc",
    candidates=[
        REPO_ROOT / "jira-design-doc" / "main.py",
        REPO_ROOT / "jira-design-doc" / "app.py",
        REPO_ROOT / "jira_design_doc" / "main.py",
        REPO_ROOT / "jira_design_doc" / "app.py",
        REPO_ROOT / "app" / "jira-design-doc" / "main.py",
        REPO_ROOT / "app" / "jira-design-doc" / "app.py",
        REPO_ROOT / "app" / "jira_design_doc" / "main.py",
        REPO_ROOT / "app" / "jira_design_doc" / "app.py",
    ],
    package_import="app.jira_design_doc.main",
)

# ✅ DO NOT CHANGE: option 3 (kept same approach)
#code_review_app = load_module_app(
#    "Code Review Checklist",
#    "code_review",
#    candidates=[
#        REPO_ROOT / "code-review" / "main.py",
#        REPO_ROOT / "code-review" / "app.py",
#        REPO_ROOT / "code_review" / "main.py",
#        REPO_ROOT / "code_review" / "app.py",
#        REPO_ROOT / "app" / "code-review" / "main.py",
#    ],
#)

# ✅ DO NOT CHANGE: option 4 (kept same approach)
ai_code_review_app = load_module_app(
    "AI Code Review",
    "ai_code_review",
    candidates=[
        REPO_ROOT / "app" / "ai_code_review" / "main.py",
        REPO_ROOT / "ai-code-review" / "main.py",
        REPO_ROOT / "ai_code_review" / "main.py",
    ],
)


# ------------------------------------------------------------
# Mount apps
# ------------------------------------------------------------
suite.mount("/user-story", user_story_app)
suite.mount("/design-doc", design_doc_app)
#suite.mount("/code-review", code_review_app)
suite.mount("/ai-code-review", ai_code_review_app)

app = suite
