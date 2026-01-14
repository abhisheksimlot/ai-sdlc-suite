# ai-sdlc-suite/app/ai_code_review/utils/content_filter.py
from __future__ import annotations

import os
from typing import Dict


# Folders we never want to scan (noise, binaries, dependencies, build outputs)
EXCLUDED_DIRS = {
    ".git", ".github", ".idea", ".vscode",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env",
    "node_modules", "dist", "build", ".next", "coverage",
    ".terraform", ".gradle", ".mvn",
}

# Extensions we never want to read as text
EXCLUDED_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico",
    ".pdf", ".docx", ".pptx", ".xlsx",
    ".exe", ".dll", ".so", ".dylib",
    ".zip", ".7z", ".rar", ".tar", ".gz",
    ".pyc", ".pyo", ".class",
    ".lock",
}

# Allowed "text-like" file types that often matter in reviews (incl. Power Platform artifacts)
INCLUDED_TEXT_EXTS = {
    # code
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".rb", ".php", ".cpp", ".c", ".h",
    ".sql", ".ps1", ".sh", ".bat",
    # web / templates
    ".html", ".htm", ".css",
    # config / docs
    ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".xml", ".md", ".txt",
    # power platform solution files
    ".msapp",  # note: binary in many cases; your pipeline extracts msapp bytes separately too
}

MAX_FILE_CHARS = 80_000  # safety: avoid huge files blowing prompt size / RAM


def _norm_path(p: str) -> str:
    # ZIP paths are usually forward slashes, OS paths may not be.
    return (p or "").replace("\\", "/").lstrip("./")


def _is_in_excluded_dir(path_norm: str) -> bool:
    parts = [x for x in path_norm.split("/") if x]
    return any(part in EXCLUDED_DIRS for part in parts)


def filter_files_for_review(files: Dict[str, str]) -> Dict[str, str]:
    """
    Takes dict[path -> decoded text], returns a filtered dict[path -> text]
    removing junk folders/binaries and keeping relevant code/config/docs.

    IMPORTANT: Do NOT restrict to 'app/' only.
    That was the main reason repo scans became shallow/fast.
    """
    filtered: Dict[str, str] = {}

    for raw_path, content in (files or {}).items():
        p = _norm_path(raw_path)

        if not p or p.endswith("/"):
            continue

        # Skip excluded folders anywhere in the path
        if _is_in_excluded_dir(p):
            continue

        # Extension checks
        _, ext = os.path.splitext(p.lower())
        if ext in EXCLUDED_EXTS:
            continue

        # If it has an extension and isn't in our included set, ignore it
        # (helps avoid random vendor blobs, unknown formats, etc.)
        if ext and ext not in INCLUDED_TEXT_EXTS:
            continue

        # Some files have no extension but are still useful (e.g., Dockerfile, Makefile)
        basename = os.path.basename(p).lower()
        if not ext and basename not in {"dockerfile", "makefile", "requirements", "requirements.txt"}:
            # keep extensionless only if it looks like a known important file
            continue

        text = content or ""
        text = text.strip()
        if not text:
            continue

        # Safety cap per file
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + "\n\n[TRUNCATED: file too large]"

        filtered[p] = text

    return filtered
