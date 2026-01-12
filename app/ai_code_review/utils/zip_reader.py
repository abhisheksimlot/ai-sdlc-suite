import io
import zipfile
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class ZipFileEntry:
    path: str
    content: bytes


def read_zip_in_memory(zip_bytes: bytes, max_file_bytes: int = 8_000_000) -> List[ZipFileEntry]:
    """
    Reads a ZIP fully in-memory. Does NOT extract to disk.
    Keeps binary entries too (needed for .msapp).
    """
    entries: List[ZipFileEntry] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if info.file_size > max_file_bytes:
                continue
            with z.open(info) as f:
                entries.append(ZipFileEntry(path=info.filename, content=f.read()))
    return entries


def as_text_files(entries: List[ZipFileEntry]) -> Dict[str, str]:
    """
    Best-effort decode to UTF-8 text. Non-text files decode with replacement.
    """
    out: Dict[str, str] = {}
    for e in entries:
        try:
            out[e.path] = e.content.decode("utf-8", errors="replace")
        except Exception:
            continue
    return out


def extract_binary(entries: List[ZipFileEntry], suffix_lower: str) -> Dict[str, bytes]:
    """
    Returns dict of filename->bytes for entries matching suffix (e.g. '.msapp').
    """
    out: Dict[str, bytes] = {}
    for e in entries:
        if e.path.lower().endswith(suffix_lower):
            out[e.path] = e.content
    return out
