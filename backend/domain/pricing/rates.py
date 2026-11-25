from bisect import bisect_right
from collections import defaultdict
from datetime import date

from ..intake.models import ArchiveRow
from ..publication.gate import Issue


class RateBook:
    def __init__(self, rows: list[ArchiveRow]):
        groups = defaultdict(lambda: defaultdict(list))
        for row in sorted(rows, key=lambda item: item.record_id):
            groups[row.scope()][row.effective_on].append(row)
        self.groups = groups
        self.dates = {scope: sorted(boundaries) for scope, boundaries in groups.items()}

    def conflicts(self) -> list[Issue]:
        issues = []
        for scope, boundaries in self.groups.items():
            for effective_on, rows in boundaries.items():
                if len(rows) > 1:
                    ids = tuple(row.record_id for row in rows)
                    scope_text = ' / '.join(scope)
                    issues.append(Issue('conflicting_rate_rules', 'rate', ids[0],
                                        f'{scope_text} 在 {effective_on} 有多条费率。', ids))
        return issues

    def applicable(self, usage: ArchiveRow) -> list[ArchiveRow]:
        scope = usage.scope()
        dates: list[date] = self.dates.get(scope, [])
        position = bisect_right(dates, usage.used_on) - 1
        return self.groups[scope][dates[position]] if position >= 0 else []
