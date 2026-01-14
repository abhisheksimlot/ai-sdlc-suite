from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates


# Always resolve templates relative to this file
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render(
    request: Request,
    template_name: str,
    context: Optional[Dict[str, Any]] = None,
    status_code: int = 200,
) -> Response:
    """
    Render a Jinja2 template with FastAPI request injected.
    """
    ctx: Dict[str, Any] = {"request": request}
    if context:
        ctx.update(context)

    return templates.TemplateResponse(
        name=template_name,
        context=ctx,
        status_code=status_code,
    )


def html(content: str, status_code: int = 200) -> HTMLResponse:
    """
    Return raw HTML without templates.
    """
    return HTMLResponse(content=content, status_code=status_code)
