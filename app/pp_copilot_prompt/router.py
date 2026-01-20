from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from .text_extractors import extract_text_from_upload
from .prompt_builder import PromptOptions, build_copilot_make_a_plan_prompt

router = APIRouter(prefix="/pp-copilot", tags=["pp-copilot"])


@router.post("/generate")
async def generate_copilot_prompt(
    design_doc: UploadFile = File(...),
    jira_stories: UploadFile = File(...),
    solution_name: str = Form("MSPP Auto-Generated Solution"),
    publisher_prefix: str = Form("org"),
):
    design_bytes = await design_doc.read()
    jira_bytes = await jira_stories.read()

    design = extract_text_from_upload(design_doc.filename, design_bytes)
    jira = extract_text_from_upload(jira_stories.filename, jira_bytes)

    if not design.text:
        return JSONResponse(
            status_code=400,
            content={"error": f"Could not extract text from Design Doc: {design.filename} ({design.detected_type}). Try .docx or .pdf."},
        )
    if not jira.text:
        return JSONResponse(
            status_code=400,
            content={"error": f"Could not extract text from JIRA file: {jira.filename} ({jira.detected_type}). Try .docx or .pdf."},
        )

    opts = PromptOptions(solution_name=solution_name, publisher_prefix=publisher_prefix)
    prompt = build_copilot_make_a_plan_prompt(design.text, jira.text, opts)

    return {
        "solution_name": solution_name,
        "publisher_prefix": publisher_prefix,
        "design_doc_type": design.detected_type,
        "jira_doc_type": jira.detected_type,
        "prompt": prompt,
    }
