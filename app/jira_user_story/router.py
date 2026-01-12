from fastapi import APIRouter

from app.jira_user_story.main import app as module_app

router = APIRouter()

for r in module_app.router.routes:
    router.routes.append(r)
