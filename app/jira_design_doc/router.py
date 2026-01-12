from fastapi import APIRouter

from app.jira_design_doc.main import app as module_app

router = APIRouter()

# Expose all routes defined in module_app (FastAPI instance)
for r in module_app.router.routes:
    router.routes.append(r)
