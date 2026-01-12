from typing import Any, Dict, List, TypedDict, Optional

class Snippet(TypedDict):
    path: str
    snippet_type: str  # "head" | "function" | "class" | "config" | "hit"
    content: str

class Finding(TypedDict):
    path: str
    rule: str
    line: int
    evidence: str

class CodePack(TypedDict):
    language: str                    # "python" | "dotnet" | "java" | "mixed"
    file_index: List[Dict[str, Any]] # includes relevant files for that stack
    snippets: List[Snippet]
    quick_findings: List[Finding]
    repo_signals: Dict[str, Any]     # build files, frameworks, etc.
    stats: Dict[str, Any]
