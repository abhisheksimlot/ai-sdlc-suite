from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

pp_copilot_app = FastAPI()

# ✅ Use shared templates directory so base.html is found
templates = Jinja2Templates(directory="app/templates")

@pp_copilot_app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("pp_copilot_prompt.html", {"request": request})
