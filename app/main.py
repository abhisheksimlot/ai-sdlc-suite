from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.ai_code_review.router import router as ai_code_review_router
from app.jira_user_story.router import router as jira_user_story_router
from app.jira_design_doc.router import router as jira_design_doc_router

# --------- Suite app ----------
app = FastAPI(title="AI SDLC Suite")

# Templates for home page
SUITE_APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(SUITE_APP_DIR / "templates"))

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# Optional: debug route list
@app.get("/__routes")
def show_routes():
    out = []
    for r in app.router.routes:
        out.append({
            "type": r.__class__.__name__,
            "path": getattr(r, "path", None),
            "name": getattr(r, "name", None),
        })
    return out

# --------- Include module routers ----------
app.include_router(ai_code_review_router, prefix="/ai-code-review", tags=["AI Code Review"])
app.include_router(jira_user_story_router, prefix="/jira-user-story", tags=["Jira User Story"])
app.include_router(jira_design_doc_router, prefix="/jira-design-doc", tags=["Jira Design Doc"])
