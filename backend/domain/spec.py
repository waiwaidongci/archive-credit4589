from .intake.dataset import record_key, validate_rows
from .intake.demo import seed
from .intake.models import ArchiveRow, PivotOptions
from .pricing.charges import price_usages
from .pricing.contracts import index_contracts
from .pricing.rates import RateBook
from .publication.gate import Issue, publication_status
from .reporting.pivot import DIMENSIONS, build_pivot, reconcile


TITLE = '影像档案授权费生效口径透视'
METHOD = '按使用日匹配合同及最近已生效费率，逐笔向上取整计费单位，以整数分核对层级透视。'
SEED_NAME = 'archive-credit-2026-12-02.csv'
ROW_MODEL = ArchiveRow
OPTIONS_MODEL = PivotOptions


def analyze(rows: list[ArchiveRow], options: PivotOptions) -> dict:
    validate_rows(rows)
    contracts, issues = index_contracts([row for row in rows if row.row_type == 'contract'])
    rate_rows = [row for row in rows if row.row_type == 'rate']
    rates = RateBook(rate_rows)
    issues.extend(rates.conflicts())
    usages = [row for row in rows if row.row_type == 'usage']
    details, usage_issues = price_usages(usages, contracts, rates)
    issues.extend(usage_issues)
    if not usages:
        issues.append(Issue('no_usage', 'dataset', None, '批次缺少授权使用记录。'))

    priced = [row for row in details if row['status'] == 'priced']
    total = sum(row['fee_cents'] for row in priced)
    dimensions = DIMENSIONS[options.pivot_order]
    pivot = build_pivot(priced, dimensions)
    reconciliation = reconcile(pivot, dimensions, total, len(priced))
    balanced = all(row['balanced'] for row in reconciliation)
    if not balanced:
        issues.append(Issue('pivot_mismatch', 'dataset', None, '计价明细与透视层级未对平。'))
    issue_table, warnings, publishable = publication_status(issues)
    return {
        'summary': {'contract_count': len(contracts), 'rate_count': len(rate_rows),
                    'usage_count': len(usages), 'priced_count': len(priced),
                    'unpriced_count': len(usages) - len(priced), 'issue_count': len(issues),
                    'total_fee_cents': total, 'currency': 'CNY', 'pivot_order': list(dimensions),
                    'balanced': balanced},
        'tables': {'usage_pricing': details, 'pivot': pivot, 'reconciliation': reconciliation,
                   'issues': issue_table},
        'warnings': warnings,
        'publishable': publishable,
    }
