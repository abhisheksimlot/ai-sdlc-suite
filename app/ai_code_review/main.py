from fastapi import FastAPI
from app.ai_code_review.router import router

# Wrapper app so your suite loader can import a FastAPI variable named `app`.
app = FastAPI(title="AI Code Review")
app.include_router(router)
