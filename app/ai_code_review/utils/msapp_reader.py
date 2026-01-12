import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict


@dataclass(frozen=True)
class MsappArtifact:
    internal_path: str
    text: str
    kind: str  # "json" | "text"


@dataclass(frozen=True)
class CanvasFormulaHit:
    location: str     # friendly location: Screen=... Control=... Property=...
    line: int         # best-effort line within the artifact text
    snippet: str      # the formula/value snippet


def is_probably_msapp_zip(msapp_bytes: bytes) -> bool:
    return len(msapp_bytes) >= 4 and msapp_bytes[0:2] == b"PK"


def read_msapp_in_memory(msapp_bytes: bytes, max_file_bytes: int = 2_000_000) -> List[MsappArtifact]:
    if not is_probably_msapp_zip(msapp_bytes):
        return []

    artifacts: List[MsappArtifact] = []
    with zipfile.ZipFile(io.BytesIO(msapp_bytes)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if info.file_size > max_file_bytes:
                continue

            name = info.filename
            lower = name.lower()
            if not (lower.endswith(".json") or lower.endswith(".txt") or lower.endswith(".fx") or lower.endswith(".yaml")):
                continue

            with z.open(info) as f:
                raw = f.read()
            text = raw.decode("utf-8", errors="replace")

            kind = "json" if lower.endswith(".json") else "text"
            artifacts.append(MsappArtifact(internal_path=name, text=text, kind=kind))

    return artifacts


# ---- Friendly extraction helpers ----
FX_TOKENS = [
    "Patch(", "Collect(", "ClearCollect(", "Remove(", "RemoveIf(",
    "LookUp(", "Filter(", "Search(", "ForAll(", "Concurrent(",
    "IfError(", "Notify(", "Set(", "UpdateContext(", "Navigate(",
    "With(", "SortByColumns(", "AddColumns(", "DropColumns("
]
TOKEN_RE = re.compile("|".join(re.escape(t) for t in FX_TOKENS))


def _safe_json_load(text: str) -> Optional[object]:
    try:
        return json.loads(text)
    except Exception:
        return None


def _find_line(text: str, needle: str) -> int:
    idx = text.find(needle)
    if idx < 0:
        return 1
    return text.count("\n", 0, idx) + 1


def _walk_json(obj: object, path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else str(k)
            yield (new_path, v)
            yield from _walk_json(v, new_path)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_path = f"{path}[{i}]"
            yield (new_path, v)
            yield from _walk_json(v, new_path)


def extract_canvas_formula_hits(artifacts: List[MsappArtifact], max_hits: int = 400) -> List[CanvasFormulaHit]:
    """
    Attempts to extract formulas with friendly locations:
      Screen=... Control=... Property=...
    Falls back to internal_path when structure is unknown.
    """
    hits: List[CanvasFormulaHit] = []

    # Try to discover screens from CanvasManifest.json (if present)
    screens: Dict[str, str] = {}  # internal id -> screen name
    for a in artifacts:
        if a.internal_path.lower().endswith("canvasmanifest.json"):
            data = _safe_json_load(a.text)
            if isinstance(data, dict):
                # best-effort: scan for items that look like screens
                for p, v in _walk_json(data):
                    if isinstance(v, dict):
                        name = v.get("Name") or v.get("DisplayName")
                        typ = v.get("Type") or v.get("ControlType") or ""
                        if name and ("screen" in str(typ).lower()):
                            screens[p] = str(name)

    # Common formula-bearing property names in Canvas
    formula_props = {
        "OnSelect", "OnVisible", "OnHidden", "OnChange", "OnStart",
        "Items", "Default", "Text", "Visible", "DisplayMode",
        "OnSuccess", "OnFailure",
    }

    for a in artifacts:
        if len(hits) >= max_hits:
            break
        if len(a.text) > 700_000:
            continue

        # JSON-based structured extraction (better, if possible)
        if a.kind == "json":
            data = _safe_json_load(a.text)
            if data is not None:
                # Find leaf strings that contain known PowerFx tokens
                for p, v in _walk_json(data):
                    if len(hits) >= max_hits:
                        break

                    if isinstance(v, str) and TOKEN_RE.search(v):
                        # Attempt to infer friendly location from path
                        # We look for ".Name" keys nearby or a Screen/Control context
                        # This is heuristic; still far better than raw file paths.
                        friendly = None

                        # Heuristics:
                        # - if path contains something like Screens[...]
                        # - if path contains ".Controls" etc.
                        lower_path = p.lower()

                        # property name is last segment
                        prop = p.split(".")[-1]
                        prop_name = prop if prop in formula_props else prop

                        # try find screen name by matching known screen path fragments
                        screen_name = None
                        for sid, sname in screens.items():
                            if sid.lower() in lower_path:
                                screen_name = sname
                                break

                        # attempt control name: look for "...Name" within same object by scanning siblings is hard here,
                        # so we fallback to something stable
                        # We'll use a trimmed path as control hint
                        control_hint = None
                        m = re.search(r"(controls?\[[0-9]+\])", lower_path)
                        if m:
                            control_hint = m.group(1)
                        else:
                            # last parent segment
                            parent = ".".join(p.split(".")[:-1])
                            control_hint = parent.split(".")[-1] if parent else "Control"

                        if screen_name:
                            friendly = f"Screen={screen_name} :: Control={control_hint} :: Property={prop_name}"
                        else:
                            friendly = f"Control={control_hint} :: Property={prop_name}"

                        line = _find_line(a.text, v[:30])  # best-effort
                        hits.append(CanvasFormulaHit(
                            location=f"{friendly} ({a.internal_path})",
                            line=line,
                            snippet=v.strip()[:800],
                        ))
                continue  # JSON succeeded; skip text-line scan

        # Text scan fallback (older/unknown structures)
        lines = a.text.splitlines()
        for idx, line in enumerate(lines):
            if len(hits) >= max_hits:
                break
            if TOKEN_RE.search(line):
                block = "\n".join(lines[max(0, idx - 1): min(len(lines), idx + 6)]).strip()
                hits.append(CanvasFormulaHit(
                    location=f"{a.internal_path}",
                    line=idx + 1,
                    snippet=block[:800],
                ))

    return hits
