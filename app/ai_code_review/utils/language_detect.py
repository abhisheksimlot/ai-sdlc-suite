from collections import Counter
from typing import Dict, List


EXT_TO_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".cs": "csharp",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c/cpp",
    ".kt": "kotlin",
    ".swift": "swift",
    ".rs": "rust",
    ".json": "json",
    ".xml": "xml",
}

MANIFEST_HINTS = {
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "package.json": "javascript/typescript",
    "pom.xml": "java",
    "build.gradle": "java",
    ".csproj": "csharp",
    "go.mod": "go",

    # ✅ Power Platform solution hints
    "solution.xml": "powerplatform",
    "customizations.xml": "powerplatform",
    "connections.json": "powerplatform",
    "environmentvariabledefinitions": "powerplatform",
    "environmentvariablevalues": "powerplatform",
    "connectionreferences": "powerplatform",
    ".msapp": "powerplatform",
}


def detect_languages(files: Dict[str, str]) -> List[str]:
    counter = Counter()

    for path in files.keys():
        lower = path.lower()

        # Power Platform strong patterns
        if lower.endswith("solution.xml") or lower.endswith("customizations.xml"):
            counter["powerplatform"] += 8
        if "/workflows/" in lower and lower.endswith(".json"):
            counter["powerplatform"] += 4
        if "/canvasapps/" in lower and (lower.endswith(".msapp") or lower.endswith(".json")):
            counter["powerplatform"] += 4
        if "/connectionreferences/" in lower and lower.endswith(".xml"):
            counter["powerplatform"] += 4
        if "/environmentvariabledefinitions/" in lower and lower.endswith(".xml"):
            counter["powerplatform"] += 4
        if "/environmentvariablevalues/" in lower and lower.endswith(".xml"):
            counter["powerplatform"] += 4

        # Manifest hints
        for hint, lang in MANIFEST_HINTS.items():
            if hint.startswith(".") and lower.endswith(hint):
                counter[lang] += 4
            elif lower.endswith("/" + hint) or lower == hint:
                counter[lang] += 4

        # Extension-based
        dot = lower.rfind(".")
        if dot != -1:
            ext = lower[dot:]
            lang = EXT_TO_LANG.get(ext)
            if lang:
                counter[lang] += 1

    expanded = Counter()
    for k, v in counter.items():
        if k == "javascript/typescript":
            expanded["javascript"] += v
            expanded["typescript"] += v
        else:
            expanded[k] += v

    return [lang for lang, score in expanded.most_common() if score > 0]
