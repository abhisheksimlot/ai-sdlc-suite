from typing import Dict


DEFAULT_IGNORE_PARTS = (
    "/node_modules/",
    "/.git/",
    "/.svn/",
    "/.hg/",
    "/bin/",
    "/obj/",
    "/dist/",
    "/build/",
    "/target/",
    "/out/",
    "/.next/",
    "/.venv/",
    "/venv/",
)


def filter_files_for_review(files: Dict[str, str], max_chars_per_file: int = 200_000) -> Dict[str, str]:
    """
    Remove common junk folders and cap file size (still in-memory).
    """
    kept: Dict[str, str] = {}
    for path, content in files.items():
        p = path.replace("\\", "/").lower()
        if any(part in p for part in DEFAULT_IGNORE_PARTS):
            continue
        kept[path] = content[:max_chars_per_file] if len(content) > max_chars_per_file else content
    return kept
