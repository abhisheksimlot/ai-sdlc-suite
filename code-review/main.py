import os
import zipfile
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from review_logic import (
    generate_code_review_report,
    StandardsDocInvalidError,
)  # NOTE: no relative import

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="AI Code Review")


@app.get("/", response_class=HTMLResponse)
def upload_form(request: Request):
    return templates.TemplateResponse("review_upload.html", {"request": request})


@app.post("/review", response_class=HTMLResponse)
async def run_review(
    request: Request,
    standards_docx: UploadFile = File(...),
    project_zip: UploadFile = File(...),
    project_name: Optional[str] = Form(None),
    prepared_by: str = Form(""),
):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        standards_path = tmp / "standards.docx"
        zip_path = tmp / "project.zip"
        extract_dir = tmp / "repo"

        # --- Save standards ---
        standards_bytes = await standards_docx.read()
        if not standards_bytes or len(standards_bytes) < 1000:
            return templates.TemplateResponse(
                "review_result.html",
                {"request": request, "error": "Standards file looks empty/invalid. Upload a valid .docx.", "report": None},
            )
        standards_path.write_bytes(standards_bytes)

        # Validate docx is a zip container
        if not zipfile.is_zipfile(standards_path):
            return templates.TemplateResponse(
                "review_result.html",
                {"request": request, "error": "Uploaded standards file is not a valid .docx.", "report": None},
            )

        # --- Save zip ---
        zip_bytes = await project_zip.read()
        if not zip_bytes or len(zip_bytes) < 1000:
            return templates.TemplateResponse(
                "review_result.html",
                {"request": request, "error": "Project ZIP looks empty/invalid. Upload a valid .zip.", "report": None},
            )
        zip_path.write_bytes(zip_bytes)

        # --- Extract zip ---
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(extract_dir)
        except zipfile.BadZipFile:
            return templates.TemplateResponse(
                "review_result.html",
                {"request": request, "error": "Uploaded project file is not a valid ZIP.", "report": None},
            )

        repo_root = _detect_repo_root(extract_dir)

        # --- Default project name from ZIP filename ---
        if not project_name or not project_name.strip():
            filename = project_zip.filename or "Python Project"
            project_name = os.path.splitext(filename)[0]

        # Fixed model (NOT shown in UI)
        model = "gpt-4.1-mini"
        #model = "gpt-4.1-nano"


        try:
            report = generate_code_review_report(
                standards_docx_path=standards_path,
                repo_root=repo_root,
                project_name=project_name.strip(),
                prepared_by=prepared_by.strip() if "prepared_by" in locals() else "",
            )
            return templates.TemplateResponse(
                "review_result.html",
                {"request": request, "error": None, "report": report},
            )

        except StandardsDocInvalidError:
            return templates.TemplateResponse(
                "review_result.html",
                {
                    "request": request,
                    "error": "The attached document doesnt look like a best practice or coding standard document",
                    "report": None
                },
            )

        except Exception as e:
            return templates.TemplateResponse(
                "review_result.html",
                {"request": request, "error": str(e), "report": None},
            )


def _detect_repo_root(extract_dir: Path) -> Path:
    entries = [p for p in extract_dir.iterdir() if p.name not in {".DS_Store"}]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extract_dir
