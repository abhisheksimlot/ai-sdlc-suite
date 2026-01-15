# ai-sdlc-suite/app/ai_code_review/utils/zip_reader.py
from __future__ import annotations

import io
import os
import zipfile
from typing import Dict, Iterable, Optional, Set, Tuple


def read_zip_in_memory(zip_bytes: bytes) -> Dict[str, bytes]:
    """
    Read a ZIP (bytes) and return a dict: { path: raw_bytes }.
    """
    if not zip_bytes:
        return {}

    out: Dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = (info.filename or "").replace("\\", "/").lstrip("/")
            if not name:
                continue
            try:
                out[name] = z.read(info.filename)
            except Exception:
                # ignore unreadable entries
                continue
    return out


def normalize_zip_entries(entries: Dict[str, bytes]) -> Dict[str, bytes]:
    """
    GitHub (and many tools) wrap repo contents in a top-level folder:
      repo-main/app/main.py -> app/main.py
    This strips that top folder IF all files share it.
    """
    if not entries:
        return entries

    keys = [k for k in entries.keys() if isinstance(k, str) and k]
    if not keys:
        return entries

    # Determine common top folder
    top = None
    for k in keys:
        k2 = k.replace("\\", "/")
        if "/" not in k2:
            top = None
            break
        first = k2.split("/")[0]
        if not first:
            top = None
            break
        if top is None:
            top = first
        elif top != first:
            top = None
            break

    if not top:
        return entries

    # Confirm all keys start with top + "/"
    prefix = top + "/"
    if not all(k.replace("\\", "/").startswith(prefix) for k in keys):
        return entries

    new_map: Dict[str, bytes] = {}
    for k, v in entries.items():
        kk = k.replace("\\", "/")
        if kk.startswith(prefix):
            kk = kk[len(prefix):]
        new_map[kk] = v
    return new_map


def as_text_files(entries: Dict[str, bytes], max_bytes: int = 500_000) -> Dict[str, str]:
    """
    Convert ZIP entries to text files dict[path -> decoded string].
    Skips very large files and binary-like extensions.
    """
    if not entries:
        return {}

    binary_exts = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico",
        ".exe", ".dll", ".so", ".dylib",
        ".zip", ".7z", ".rar", ".tar", ".gz",
        ".pdf", ".docx", ".pptx", ".xlsx",
        ".pyc", ".class",
    }

    out: Dict[str, str] = {}
    for path, data in entries.items():
        p = (path or "").replace("\\", "/").lstrip("/")
        if not p or p.endswith("/"):
            continue

        ext = os.path.splitext(p.lower())[1]
        if ext in binary_exts:
            continue

        if not isinstance(data, (bytes, bytearray)):
            continue

        if len(data) > max_bytes:
            continue

        try:
            out[p] = data.decode("utf-8", errors="ignore")
        except Exception:
            continue

    return out


def extract_binary(entries: Dict[str, bytes], extensions: Optional[Set[str]] = None) -> Dict[str, bytes]:
    """
    Extract binary files by extension (e.g., {'.msapp'}).
    Returns dict[path -> bytes]
    """
    if not entries:
        return {}

    exts = {e.lower() for e in (extensions or set())}
    out: Dict[str, bytes] = {}

    for path, data in entries.items():
        p = (path or "").replace("\\", "/").lstrip("/")
        if not p or p.endswith("/"):
            continue
        ext = os.path.splitext(p.lower())[1]
        if exts and ext not in exts:
            continue
        if isinstance(data, (bytes, bytearray)):
            out[p] = bytes(data)

    return out
