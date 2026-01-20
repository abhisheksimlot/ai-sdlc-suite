from __future__ import annotations

import importlib
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


def _import_fastapi_app_from_package(module_path: str):
    """
    Import a FastAPI app from a Python package module path like:
      app.jira_design_doc.main
    This preserves relative imports inside that module/package.
    """
    import sys

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
    if package_import:
        try:
            return _import_fastapi_app_from_package(package_import)
        except Exception:
            pass

    app_file = _first_existing(candidates)
    if not app_file:
        expected = str(candidates[0])
        return stub_app(display_name, expected)

    try:
        return import_fastapi_app_from_file(app_file, module_key)
    except Exception as e:
        return stub_app(display_name, f"{app_file}\n\nImport error:\n{e}")


# ------------------------------------------------------------
# Special loader: a router-only module (no "app" variable)
# ------------------------------------------------------------
def load_router_only_app(
    display_name: str,
    module_key: str,
    router_file_candidates: List[Path],
    router_attr_name: str = "router",
) -> FastAPI:
    """
    Loads a FastAPI APIRouter from a python file and wraps it in a FastAPI app.
    This is useful when you built a module as "router.py" rather than "main.py".
    """
    router_file = _first_existing(router_file_candidates)
    if not router_file:
        expected = str(router_file_candidates[0])
        return stub_app(display_name, expected)

    try:
        import sys
        import time

        app_dir = str(router_file.parent)
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)

        unique_name = f"{module_key}_router_{int(time.time() * 1000)}"
        spec = importlib.util.spec_from_file_location(unique_name, str(router_file))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load module spec for: {router_file}")

        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore

        if not hasattr(mod, router_attr_name):
            raise AttributeError(f"{router_file} does not define '{router_attr_name}'")

        r = getattr(mod, router_attr_name)

        a = FastAPI(title=display_name)
        a.include_router(r)
        return a

    except Exception as e:
        return stub_app(display_name, f"{router_file}\n\nImport error:\n{e}")


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

# ✅ NEW: Test Case Generation module
# Preferred: package import app.test_case_gen.main (if you create main.py)
# Fallback: router-only file app/test_case_gen/router.py (as provided earlier)
test_case_app = load_module_app(
    "Test Case Generation",
    "test_case_gen",
    candidates=[
        REPO_ROOT / "app" / "test_case_gen" / "main.py",
    ],
    package_import="app.test_case_gen.main",
)

# If main.py isn't present, use router-only fallback
# (only if the previous call returned a "Missing" stub app)
if "Missing" in getattr(test_case_app, "title", ""):
    test_case_app = load_router_only_app(
        "Test Case Generation",
        "test_case_gen",
        router_file_candidates=[
            REPO_ROOT / "app" / "test_case_gen" / "router.py",
        ],
        router_attr_name="router",
    )



# ------------------------------------------------------------
# Mount sub-apps (UI apps)
# ------------------------------------------------------------
suite.mount("/user-story", user_story_app)
suite.mount("/design-doc", design_doc_app)
suite.mount("/ai-code-review", ai_code_review_app)
suite.mount("/test-cases", test_case_app)
from app.pp_copilot_prompt.app import pp_copilot_app
from app.pp_copilot_prompt.router import router as pp_copilot_router


# ------------------------------------------------------------
# Include API routers (services, NOT apps)
# ------------------------------------------------------------

suite.include_router(pp_copilot_router)
suite.mount("/pp-copilot-ui", pp_copilot_app)

# ------------------------------------------------------------
# Final ASGI app
# ------------------------------------------------------------
app = suite

# ✅ NEW mount
suite.mount("/test-cases", test_case_app)

from app.pp_copilot_prompt.router import router as pp_copilot_router
app.include_router(pp_copilot_router)


app = suite
