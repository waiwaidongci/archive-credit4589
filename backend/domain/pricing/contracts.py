from ..intake.models import ArchiveRow
from ..publication.gate import Issue


def index_contracts(rows: list[ArchiveRow]) -> tuple[dict[str, ArchiveRow], list[Issue]]:
    contracts = {row.record_id: row for row in rows}
    issues = [Issue('invalid_contract_interval', 'contract', row.record_id,
                    f'合同开始日 {row.starts_on} 晚于结束日 {row.ends_on}。')
              for row in rows if row.starts_on > row.ends_on]
    return contracts, issues


def check_contract(usage: ArchiveRow, contracts: dict[str, ArchiveRow]) -> Issue | None:
    contract = contracts.get(usage.contract_id)
    code = None
    message = ''
    if contract is None:
        code, message = 'missing_contract', '使用记录引用的合同未登记。'
    elif contract.starts_on > contract.ends_on:
        code, message = 'unusable_contract', '合同起止日无效。'
    elif usage.scope() != contract.scope():
        code, message = 'contract_scope_mismatch', '档案馆、渠道或使用类别超出合同授权范围。'
    elif not contract.starts_on <= usage.used_on <= contract.ends_on:
        code = 'outside_contract_interval'
        message = f'使用日 {usage.used_on} 超出合同区间 {contract.starts_on} 至 {contract.ends_on}。'
    if code:
        return Issue(code, 'usage', usage.record_id, message, (usage.contract_id,))
    return None
