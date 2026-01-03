from __future__ import annotations

from pathlib import Path
import importlib.util

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def import_fastapi_app_from_file(app_file: Path, module_name: str):
    """
    Loads a Python file as a uniquely-named module and returns its FastAPI `app`.
    Adds the app's directory to sys.path so local imports work (e.g. design_doc_logic).
    """
    import sys
    if not app_file.exists():
        raise FileNotFoundError(f"Could not find: {app_file}")

    # ✅ Ensure local imports inside that project work
    app_dir = str(app_file.parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    spec = importlib.util.spec_from_file_location(module_name, str(app_file))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module spec for: {app_file}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore

    if not hasattr(mod, "app"):
        raise AttributeError(f"{app_file} does not define a FastAPI variable named 'app'")

    return mod.app



# --------- Locate sibling projects ----------
# This file is: ...\ai-sdlc-suite\app\main.py
SUITE_APP_DIR = Path(__file__).resolve().parent        # ...\ai-sdlc-suite\app
SUITE_ROOT = SUITE_APP_DIR.parent                      # ...\ai-sdlc-suite
PROJECTS_ROOT = SUITE_ROOT.parent                      # ...\projects

USER_STORY_MAIN = PROJECTS_ROOT / "jira-user-story" / "main.py"
DESIGN_DOC_MAIN = PROJECTS_ROOT / "jira-design-doc" / "main.py"

# --------- Import both apps safely ----------
user_story_app = import_fastapi_app_from_file(USER_STORY_MAIN, "jira_user_story_main_mod")
design_doc_app = import_fastapi_app_from_file(DESIGN_DOC_MAIN, "jira_design_doc_main_mod")

# --------- Suite app ----------
suite = FastAPI(title="AI SDLC Suite")


@suite.get("/", response_class=HTMLResponse)
def home():
    return """
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width,initial-scale=1"/>
      <title>AI SDLC Suite</title>
      <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen">
      <div class="max-w-5xl mx-auto px-6 py-10">
        <div class="rounded-3xl border border-slate-800 bg-slate-900/50 p-10 shadow-lg">
          <h1 class="text-4xl font-bold tracking-tight">AI SDLC Suite</h1>
          <p class="mt-3 text-slate-300">
            Choose a tool to open .
          </p>

          <div class="mt-8 grid md:grid-cols-2 gap-5">
            <a href="/user-story/"
               class="rounded-2xl border border-slate-800 bg-slate-950/40 p-6 hover:bg-slate-950/70 transition">
              <div class="text-xl font-semibold">User Story Generator</div>
              <div class="mt-2 text-slate-300 text-sm">
                Conversation / transcript → Jira stories + Word output
              </div>
              <div class="mt-5 inline-flex rounded-xl bg-indigo-600 px-4 py-2 font-semibold">
                Open
              </div>
            </a>

            <a href="/design-doc/"
               class="rounded-2xl border border-slate-800 bg-slate-950/40 p-6 hover:bg-slate-950/70 transition">
              <div class="text-xl font-semibold">Design Document Generator</div>
              <div class="mt-2 text-slate-300 text-sm">
                Jira stories → Solution Design Document (DOCX)
              </div>
              <div class="mt-5 inline-flex rounded-xl bg-emerald-600 px-4 py-2 font-semibold">
                Open
              </div>
            </a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


# Mount both apps
suite.mount("/user-story", user_story_app)
suite.mount("/design-doc", design_doc_app)

# Uvicorn entrypoint
app = suite
