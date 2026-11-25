from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Issue:
    code: str
    row_type: str
    record_id: str | None
    message: str
    related_ids: tuple[str, ...] = ()


def publication_status(issues: list[Issue]) -> tuple[list[dict], list[str], bool]:
    issues = sorted(issues, key=lambda issue: (issue.row_type, issue.record_id or '', issue.code))
    table = [dict(asdict(issue), related_ids=list(issue.related_ids)) for issue in issues]
    warnings = [f'{issue.code} [{issue.record_id or issue.row_type}] {issue.message}' for issue in issues]
    return table, warnings, not issues
