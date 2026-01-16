from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from app.test_case_gen.generator import extract_text, generate_sit_test_cases
from app.test_case_gen.export_pdf import write_testcases_pdf
from app.test_case_gen.export_xlsx import write_testcases_xlsx
from app.test_case_gen.store import JobStore

router = APIRouter(prefix="", tags=["test-cases"])

# ------------------------------------------------------------
# Templates: module templates + global templates (base.html)
# ------------------------------------------------------------
MODULE_DIR = Path(__file__).resolve().parent                 # .../app/test_case_gen
APP_DIR = MODULE_DIR.parent                                  # .../app
MODULE_TEMPLATES = MODULE_DIR / "templates"                  # .../app/test_case_gen/templates
GLOBAL_TEMPLATES = APP_DIR / "templates"                     # .../app/templates

templates = Jinja2Templates(directory=str(MODULE_TEMPLATES))
templates.env.loader = ChoiceLoader([
    FileSystemLoader(str(MODULE_TEMPLATES)),
    FileSystemLoader(str(GLOBAL_TEMPLATES)),
])

store = JobStore()


def _bad_request(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)


@router.get("/", response_class=HTMLResponse)
def upload_form(request: Request):
    store.cleanup_old()
    return templates.TemplateResponse("test_case_upload.html", {"request": request})


@router.post("/", response_class=HTMLResponse)
async def generate(
    request: Request,
    jira_file: Optional[UploadFile] = File(default=None),
    design_file: Optional[UploadFile] = File(default=None),
    extra_info: str = Form(default=""),
):
    try:
        jira_text = ""
        design_text = ""

        if jira_file and jira_file.filename:
            jira_text = extract_text(
                jira_file.filename,
                jira_file.content_type or "",
                await jira_file.read(),
            )

        if design_file and design_file.filename:
            design_text = extract_text(
                design_file.filename,
                design_file.content_type or "",
                await design_file.read(),
            )

        if not jira_text and not design_text and not extra_info.strip():
            raise _bad_request("Please upload at least one document or provide text in 'Other information'.")

        payload = generate_sit_test_cases(
            jira_text=jira_text.strip(),
            design_text=design_text.strip(),
            extra_text=extra_info.strip(),
        )

        job_id = store.new_job_id()
        store.save_json(job_id, payload)

        return templates.TemplateResponse(
            "test_case_result.html",
            {
                "request": request,
                "job_id": job_id,
                "summary": payload.get("summary", {}),
                "test_cases": payload.get("test_cases", []),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise _bad_request(str(e))


@router.get("/{job_id}/pdf")
def download_pdf(job_id: str):
    payload = store.load_json(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Test case job not found")

    path = store.paths(job_id).pdf_path
    if not os.path.exists(path):
        write_testcases_pdf(payload, path)

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"SIT_Test_Cases_{job_id}.pdf",
    )


@router.get("/{job_id}/xlsx")
def download_xlsx(job_id: str):
    payload = store.load_json(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Test case job not found")

    path = store.paths(job_id).xlsx_path
    if not os.path.exists(path):
        write_testcases_xlsx(payload, path)

    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"SIT_Test_Cases_{job_id}.xlsx",
    )
