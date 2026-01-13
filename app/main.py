from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Optional, List

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


def import_fastapi_app_from_file(app_file: Path, module_name: str):
    """
    Loads a Python file as a uniquely-named module and returns its FastAPI `app`.
    Adds the app's directory to sys.path so local imports work.
    """
    import sys
    import time

    # Ensure local imports inside that project work
    app_dir = str(app_file.parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    # Unique module name so we don't reuse cached modules
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
                <p>I couldn't find the entry file at:</p>
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
) -> FastAPI:
    """
    Try to load an app from the first existing candidate.
    If none found, return a stub app (so suite doesn't crash).
    """
    app_file = _first_existing(candidates)
    if not app_file:
        expected = str(candidates[0])
        return stub_app(display_name, expected)

    return import_fastapi_app_from_file(app_file, module_key)


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
# Load sibling apps safely (won't crash if missing)
# ------------------------------------------------------------
user_story_app = load_module_app(
    "User Story Generator",
    "jira_user_story",
    candidates=[
        REPO_ROOT / "jira-user-story" / "main.py",
        REPO_ROOT / "jira-user-story" / "app.py",
        REPO_ROOT / "jira_user_story" / "main.py",
        REPO_ROOT / "jira_user_story" / "app.py",
        REPO_ROOT / "app" / "jira-user-story" / "main.py",
    ],
)

design_doc_app = load_module_app(
    "Design Doc Generator",
    "jira_design_doc",
    candidates=[
        REPO_ROOT / "jira-design-doc" / "main.py",
        REPO_ROOT / "jira-design-doc" / "app.py",
        REPO_ROOT / "jira_design_doc" / "main.py",
        REPO_ROOT / "jira_design_doc" / "app.py",
        REPO_ROOT / "app" / "jira-design-doc" / "main.py",
    ],
)

code_review_app = load_module_app(
    "Code Review Checklist",
    "code_review",
    candidates=[
        REPO_ROOT / "code-review" / "main.py",
        REPO_ROOT / "code-review" / "app.py",
        REPO_ROOT / "code_review" / "main.py",
        REPO_ROOT / "code_review" / "app.py",
        REPO_ROOT / "app" / "code-review" / "main.py",
    ],
)

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
suite.mount("/code-review", code_review_app)
suite.mount("/ai-code-review", ai_code_review_app)

app = suite
