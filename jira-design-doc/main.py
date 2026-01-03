import html
import io
import io as _io

from fastapi import FastAPI, Form, UploadFile, File, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from docx import Document

from design_doc_logic import generate_design_doc_bytes

app = FastAPI()
@app.get("/favicon.ico")
async def favicon():
    # Return an empty 204 (No Content) response so the browser
    # stops logging 404 errors for /favicon.ico.
    return Response(status_code=204)



# ---------- HELPER: RENDER FORM WITH OPTIONAL ERROR ---------- #
def render_form_page(
    jira_text: str = "",
    project_name: str = "",
    version: str = "1.0",
    prepared_by: str = "",
    input_mode: str = "text",
    error_message: str | None = None,
) -> HTMLResponse:
    error_html = ""
    if error_message:
        error_html = f"""
        <div class="alert-error">
            <span>⚠️ {html.escape(error_message)}</span>
        </div>
        """

    text_checked = "checked" if input_mode == "text" else ""
    file_checked = "checked" if input_mode == "file" else ""

    text_display = "flex" if input_mode == "text" else "none"
    file_display = "flex" if input_mode == "file" else "none"

    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Jira Stories → Design Document</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>
            :root {{
                --primary: #1565C0;
                --primary-dark: #0D47A1;
                --primary-light: #BBDEFB;
                --bg-light: #ffffff;
                --card-shadow: rgba(21, 101, 192, 0.25);
                --border: #e5e7eb;
                --text-main: #1a1a1a;
                --text-muted: #6b6b6b;
                --error-bg: #ffebee;
                --error-border: #ef9a9a;
                --error-text: #c62828;
            }}
            body {{
                margin: 0;
                font-family: 'Segoe UI', Arial, sans-serif;
                background: linear-gradient(120deg, #ffffff, #e3f2fd, #ffffff);
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 30px;
                min-height: 100vh;
            }}
            .app-shell {{
                width: 100%;
                max-width: 900px;
            }}
            .card {{
                background: #fff;
                border-radius: 18px;
                padding: 30px;
                box-shadow: 0 15px 35px var(--card-shadow);
                border-left: 6px solid var(--primary);
                display: flex;
                flex-direction: column;
                gap: 18px;
            }}
            h1 {{
                font-size: 1.8rem;
                margin-bottom: 4px;
                color: var(--primary-dark);
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .title-sub {{
                font-size: 0.9rem;
                color: var(--text-muted);
                margin-top: 4px;
            }}
            form {{
                display: flex;
                flex-direction: column;
                gap: 16px;
            }}
            .field-group {{
                display: flex;
                flex-direction: column;
                gap: 6px;
            }}
            .field-label-row {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 8px;
            }}
            label {{
                font-weight: 600;
                font-size: 0.9rem;
                color: var(--text-main);
            }}
            .hint {{
                font-size: 0.8rem;
                color: var(--text-muted);
            }}
            .radio-row {{
                display: flex;
                gap: 10px;
                margin-top: 6px;
                flex-wrap: wrap;
            }}
            .radio-option {{
                background: #fff;
                border: 1px solid var(--primary);
                border-radius: 25px;
                padding: 6px 14px;
                cursor: pointer;
                font-size: 0.9rem;
                color: var(--primary-dark);
                display: flex;
                align-items: center;
                gap: 6px;
                transition: 0.2s;
            }}
            .radio-option:hover {{
                background: var(--primary-light);
            }}
            input[type="radio"] {{
                accent-color: var(--primary);
            }}
            textarea, input[type="text"] {{
                width: 100%;
                padding: 10px;
                border-radius: 10px;
                border: 1px solid var(--border);
                background: #fff;
                font-size: 0.92rem;
                transition: 0.2s;
            }}
            textarea:focus, input[type="text"]:focus {{
                border-color: var(--primary);
                box-shadow: 0 0 0 3px rgba(21, 101, 192, 0.18);
                outline: none;
            }}
            textarea {{
                min-height: 220px;
                resize: vertical;
                font-family: Consolas, Menlo, Monaco, monospace;
            }}
            input[type="file"] {{
                font-size: 0.9rem;
                margin-top: 6px;
            }}
            .text-section, .file-section {{
                border: 1px dashed var(--primary-light);
                border-radius: 10px;
                background: #f5f9ff;
                padding: 12px;
                flex-direction: column;
                gap: 6px;
            }}
            .text-section {{
                display: {text_display};
                flex-direction: column;
                gap: 6px;
                border: 2px solid var(--primary);
                border-radius: 10px;
            }}
            .file-section {{
                display: {file_display};
            }}
            .alert-error {{
                background: var(--error-bg);
                border: 1px solid var(--error-border);
                padding: 10px 12px;
                border-radius: 8px;
                color: var(--error-text);
                font-size: 0.9rem;
                display: flex;
                align-items: center;
                gap: 8px;
            }}
            .btn-primary {{
                background: var(--primary);
                color: white;
                border: none;
                padding: 12px 20px;
                border-radius: 30px;
                font-size: 1rem;
                font-weight: bold;
                cursor: pointer;
                transition: 0.25s;
                box-shadow: 0 6px 14px rgba(21, 101, 192, 0.4);
                display: inline-flex;
                align-items: center;
                gap: 8px;
            }}
            .btn-primary:hover {{
                background: var(--primary-dark);
                transform: translateY(-2px);
            }}
            .btn-primary:active {{
                transform: scale(0.98);
            }}
            .footer-hint {{
                font-size: 0.8rem;
                color: var(--text-muted);
            }}
            @media (max-width: 640px) {{
                .card {{
                    padding: 20px;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="app-shell">
            <div class="card">
                <div>
                    <h1>Design Document Generator</h1>
                    <p class="title-sub">
                        Paste Jira stories or upload a file and get a structured Solution Design Document.
                    </p>
                </div>

                {error_html}

                <form method="post" action="generate" enctype="multipart/form-data">
                    <div class="field-group">
                        <div class="field-label-row">
                            <label>How would you like to provide Jira stories?</label>
                        </div>
                        <div class="radio-row">
                            <label class="radio-option">
                                <input type="radio" name="input_mode" value="text" {text_checked} onclick="toggleInput('text')">
                                <span>Text area</span>
                            </label>
                            <label class="radio-option">
                                <input type="radio" name="input_mode" value="file" {file_checked} onclick="toggleInput('file')">
                                <span>Attachment (.txt / .docx)</span>
                            </label>
                        </div>
                    </div>

                    <div class="field-group text-section" id="text-section">
                        <div class="field-label-row">
                            <label for="jira_text">Jira stories (plain text)</label>
                            <span class="hint">Paste exported Jira stories or copied text.</span>
                        </div>
                        <textarea id="jira_text" name="jira_text">{html.escape(jira_text)}</textarea>
                    </div>

                    <div class="field-group file-section" id="file-section">
                        <div class="field-label-row">
                            <label for="upload_file">Upload file</label>
                            <span class="hint">Supported: .txt or .docx</span>
                        </div>
                        <input type="file" id="upload_file" name="upload_file" accept=".txt,.docx" />
                        <span class="hint">Use this for Jira exports or existing requirement docs.</span>
                    </div>

                    <div class="field-group">
                        <div class="field-label-row">
                            <label for="project_name">Project Name</label>
                            <span class="hint">e.g. Claims Automation Portal</span>
                        </div>
                        <input type="text" id="project_name" name="project_name"
                               placeholder="Project Name"
                               value="{html.escape(project_name)}" />
                    </div>

                    <div class="field-group">
                        <div class="field-label-row">
                            <label for="version">Version</label>
                            <span class="hint">Default is 1.0</span>
                        </div>
                        <input type="text" id="version" name="version"
                               value="{html.escape(version)}" />
                    </div>

                    <div class="field-group">
                        <div class="field-label-row">
                            <label for="prepared_by">Prepared By</label>
                            <span class="hint">Your name or team name</span>
                        </div>
                        <input type="text" id="prepared_by" name="prepared_by"
                               placeholder="Abhishek Simlot"
                               value="{html.escape(prepared_by)}" />
                    </div>

                    <div class="field-group">
                        <div class="field-label-row">
                            <span class="footer-hint">
                                The generated Word file will contain your standard design sections:
                                Overview, Solution Overview, Security, DevOps, NFRs, Risks, etc.
                            </span>
                            <button type="submit" class="btn-primary">
                                <span>⬇️</span>
                                <span>Generate Design Document</span>
                            </button>
                        </div>
                    </div>
                </form>
            </div>
        </div>

        <script>
            function toggleInput(mode) {{
                var textSection = document.getElementById("text-section");
                var fileSection = document.getElementById("file-section");
                if (mode === "text") {{
                    textSection.style.display = "flex";
                    fileSection.style.display = "none";
                }} else {{
                    textSection.style.display = "none";
                    fileSection.style.display = "flex";
                }}
            }}
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# ---------- ROUTES ---------- #

@app.get("/", response_class=HTMLResponse)
async def form_page():
    # initial empty form
    return render_form_page()


@app.post("/generate")
async def generate_design_doc(
    jira_text: str = Form(""),
    project_name: str = Form(""),
    version: str = Form("1.0"),
    prepared_by: str = Form(""),
    input_mode: str = Form("text"),
    upload_file: UploadFile | None = File(None),
):
    try:
        # Decide where Jira stories come from
        if input_mode == "file":
            if upload_file is None or upload_file.filename == "":
                raise ValueError("Please upload a .txt or .docx file when 'Attachment' is selected.")

            filename = upload_file.filename.lower()
            file_bytes = await upload_file.read()

            if filename.endswith(".txt"):
                raw_text = file_bytes.decode("utf-8", errors="ignore")
            elif filename.endswith(".docx"):
                doc = Document(io.BytesIO(file_bytes))
                raw_text = "\n".join(p.text for p in doc.paragraphs)
            else:
                raise ValueError("Only .txt and .docx files are supported.")

        else:
            # Text mode
            raw_text = jira_text.strip()
            if not raw_text:
                raise ValueError("Please enter Jira stories when 'Text area' is selected.")

        if not project_name.strip():
            project_name = "PROJECT"

        if not prepared_by.strip():
            prepared_by = "Automation Factory"

        # 1) Generate design document bytes using the helper
        doc_bytes = generate_design_doc_bytes(
            jira_text=raw_text,
            project_name=project_name,
            version=version or "1.0",
            prepared_by=prepared_by,
        )

        # 2) Return as downloadable Word file
        download_name = f"{project_name.replace(' ', '_')}_design.docx"

        return StreamingResponse(
            _io.BytesIO(doc_bytes),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
        )

    except ValueError as ve:
        # Validation error – show nicely on UI
        return render_form_page(
            jira_text=jira_text,
            project_name=project_name,
            version=version,
            prepared_by=prepared_by,
            input_mode=input_mode,
            error_message=str(ve),
        )
    except Exception as e:
        # Generic error – still show UI with message
        return render_form_page(
            jira_text=jira_text,
            project_name=project_name,
            version=version,
            prepared_by=prepared_by,
            input_mode=input_mode,
            error_message=(
                "Something went wrong while generating the design document. "
                f"Details: {str(e)}"
            ),
        )
