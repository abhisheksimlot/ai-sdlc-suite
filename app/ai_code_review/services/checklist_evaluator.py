def evaluate_checklist(issues_by_category: dict) -> dict:
    """
    A category FAILS if at least ONE issue exists in that category.
    This logic must be identical for ZIP and Repo runs.
    """
    checklist = {}

    for category, issues in issues_by_category.items():
        checklist[category] = {
            "status": "FAIL" if issues else "PASS",
            "issue_count": len(issues),
        }

    return checklist