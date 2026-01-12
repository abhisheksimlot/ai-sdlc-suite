from __future__ import annotations

from pathlib import Path
import importlib.util

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


# Root of repo (ai-sdlc-suite)
REPO_ROOT = Path(__file__).resolve().parent.parent


def import_fastapi_app_from_file(app_file: Path, module_name: str):
    """
    Loads a Python file as a uniquely-named module and returns its FastAPI `app`.
    Adds the app's directory to sys.path so local imports work.
    """
    import sys
    import time

    if not app_file.exists():
        raise FileNotFoundError(
            f"Could not find: {app_file}\n\n"
            f"Fix: confirm the file exists and the path is correct.\n"
            f"If this is a router-only module, create a tiny wrapper main.py that defines `app`."
        )

    # Ensure local imports inside that project work
    app_dir = str(app_file.parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    # Make module name unique so we NEVER reuse cached modules
    unique_name = f"{module_name}_{int(time.time() * 1000)}"

    spec = importlib.util.spec_from_file_location(unique_name, str(app_file))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for: {app_file}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore

    if not hasattr(mod, "app"):
        raise AttributeError(f"{app_file} does not define a FastAPI variable named 'app'")

    return mod.app


# --------- Locate sibling projects ----------
SUITE_APP_DIR = Path(__file__).resolve().parent

USER_STORY_MAIN = REPO_ROOT / "jira-user-story" / "main.py"
DESIGN_DOC_MAIN = REPO_ROOT / "jira-design-doc" / "main.py"
CODE_REVIEW_MAIN = REPO_ROOT / "code-review" / "main.py"

# ✅ AI Code Review wrapper file (must exist)
AI_CODE_REVIEW_MAIN = REPO_ROOT / "app" / "ai_code_review" / "main.py"


# --------- Import apps ----------
user_story_app = import_fastapi_app_from_file(USER_STORY_MAIN, "jira_user_story_main_mod")
design_doc_app = import_fastapi_app_from_file(DESIGN_DOC_MAIN, "jira_design_doc_main_mod")
code_review_app = import_fastapi_app_from_file(CODE_REVIEW_MAIN, "code_review_main_mod")
ai_code_review_app = import_fastapi_app_from_file(AI_CODE_REVIEW_MAIN, "ai_code_review_main_mod")


# --------- Suite app ----------
suite = FastAPI(title="AI SDLC Suite")


@suite.get("/__routes")
def show_routes():
    out = []
    for r in suite.router.routes:
        out.append({
            "type": r.__class__.__name__,
            "path": getattr(r, "path", None),
            "name": getattr(r, "name", None),
        })
    return out


templates = Jinja2Templates(directory=str(SUITE_APP_DIR / "templates"))


@suite.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --------- Mount child apps ----------
suite.mount("/user-story", user_story_app)
suite.mount("/design-doc", design_doc_app)
suite.mount("/code-review", code_review_app)
suite.mount("/ai-code-review", ai_code_review_app)


# Export app for uvicorn
app = suite
