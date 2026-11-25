from ..intake.models import ArchiveRow
from ..publication.gate import Issue
from .contracts import check_contract
from .rates import RateBook


def price_usages(usages: list[ArchiveRow], contracts: dict[str, ArchiveRow], rates: RateBook
                 ) -> tuple[list[dict], list[Issue]]:
    details = []
    issues = []
    for usage in sorted(usages, key=lambda row: (row.used_on, row.record_id)):
        detail = {
            'usage_id': usage.record_id, 'contract_id': usage.contract_id, 'asset': usage.asset,
            'archive': usage.archive, 'channel': usage.channel, 'use_kind': usage.use_kind,
            'used_on': usage.used_on.isoformat(), 'usage_seconds': usage.usage_seconds,
            'rate_id': None, 'rate_effective_on': None, 'unit_seconds': None, 'rate_cents': None,
            'billable_units': None, 'fee_cents': None, 'status': 'priced',
        }
        contract_issue = check_contract(usage, contracts)
        if contract_issue:
            issues.append(contract_issue)
            detail['status'] = contract_issue.code
        else:
            candidates = rates.applicable(usage)
            if len(candidates) == 1:
                rate = candidates[0]
                units = (usage.usage_seconds + rate.unit_seconds - 1) // rate.unit_seconds
                detail.update(rate_id=rate.record_id, rate_effective_on=rate.effective_on.isoformat(),
                              unit_seconds=rate.unit_seconds, rate_cents=rate.rate_cents,
                              billable_units=units, fee_cents=units * rate.rate_cents)
            elif candidates:
                ids = tuple(rate.record_id for rate in candidates)
                issues.append(Issue('ambiguous_rate', 'usage', usage.record_id,
                                    f'生效日 {candidates[0].effective_on} 有多条费率。', ids))
                detail['status'] = 'ambiguous_rate'
            else:
                issues.append(Issue('missing_rate', 'usage', usage.record_id,
                                    f'在使用日 {usage.used_on} 没有匹配的已生效费率。'))
                detail['status'] = 'missing_rate'
        details.append(detail)
    return details, issues
