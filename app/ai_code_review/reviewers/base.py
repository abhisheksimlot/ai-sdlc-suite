from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Issue:
    language: str
    file_path: str
    line_start: int
    line_end: int
    severity: str            # "LOW"|"MEDIUM"|"HIGH"|"CRITICAL"
    category: str            # "Security"|"Reliability"|"Maintainability"|"Performance"|"Style"
    title: str
    detail: str
    remediation: str
    confidence: str          # "High"|"Medium"|"Low"
    rule_id: Optional[str] = None


@dataclass
class ReviewResult:
    issues: List[Issue]
    checklist: List[Dict[str, Any]]  # {category,item,result,notes}
    overall: str                     # "PASS"|"FAIL"
    summary: str


class Reviewer:
    name: str

    def supports(self, language: str) -> bool:
        raise NotImplementedError

    def review(self, files: Dict[str, str], language: str) -> List[Issue]:
        raise NotImplementedError
