"""补退款（settlement）口径。

已出账批次保留它自己那一版费率算出的逐笔金额；修订批次用修订后的费率重算。
补退款按使用编号把两批逐笔对上：

* 新旧都有且分组（档案馆、渠道）不变：只补或退差额 ``新金额 - 旧金额``；
* 新旧都有但换馆或换渠道：先在原分组全额冲回，再在新分组全额记入；
* 只在修订批次出现（新增）：全额收取；
* 只在已出账批次出现（撤销）：全额冲回。

任何一笔缺价（没有命中费率、费率冲突、合同问题）都会拦住整批出账。
"""

PRICED = 'priced'

SUPPLEMENT = 'supplement'  # 同组补收差额
REFUND = 'refund'          # 同组退还差额
CHARGE = 'charge'          # 新增全额收取
REVERSAL = 'reversal'      # 撤销或换组全额冲回


class SettlementError(ValueError):
    """A batch cannot be settled. ``code`` mirrors the publication issue codes."""

    def __init__(self, code: str, message: str, usage_ids: tuple[str, ...] = ()):
        super().__init__(message)
        self.code = code
        self.message = message
        self.usage_ids = tuple(usage_ids)


def _index(details: list[dict], label: str) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in details:
        usage_id = row.get('usage_id')
        if not usage_id:
            raise SettlementError('invalid_usage_row', f'{label}缺少使用编号。')
        if usage_id in indexed:
            raise SettlementError('duplicate_usage_id', f'{label}使用编号重复：{usage_id}。', (usage_id,))
        indexed[usage_id] = row
    return indexed


def _unpriced(indexed: dict[str, dict], label: str) -> list[str]:
    return sorted(usage_id for usage_id, row in indexed.items()
                  if row.get('status') != PRICED or row.get('fee_cents') is None)


def _fee(row: dict | None) -> int:
    return int(row['fee_cents']) if row else 0


def _line(usage_id: str, entry_type: str, amount: int, group: dict,
          old: dict | None, new: dict | None) -> dict | None:
    if amount == 0:
        return None  # 零金额不占一行，不影响任何分组净额。
    return {
        'usage_id': usage_id,
        'entry_type': entry_type,
        'amount_cents': amount,
        'group_archive': group['archive'],
        'group_channel': group['channel'],
        'group_use_kind': group['use_kind'],
        'old_archive': old['archive'] if old else None,
        'old_channel': old['channel'] if old else None,
        'old_use_kind': old['use_kind'] if old else None,
        'old_fee_cents': old['fee_cents'] if old else None,
        'old_rate_id': old.get('rate_id') if old else None,
        'new_archive': new['archive'] if new else None,
        'new_channel': new['channel'] if new else None,
        'new_use_kind': new['use_kind'] if new else None,
        'new_fee_cents': new['fee_cents'] if new else None,
        'new_rate_id': new.get('rate_id') if new else None,
    }


def _same_group(old: dict, new: dict) -> bool:
    return (old['archive'], old['channel']) == (new['archive'], new['channel'])


def settle(old_details: list[dict], new_details: list[dict]) -> dict:
    """按使用编号核对已出账批次与修订批次，返回补退款明细。"""
    old_index = _index(old_details, '已出账批次')
    new_index = _index(new_details, '修订批次')
    unpriced = _unpriced(old_index, '已出账批次') + _unpriced(new_index, '修订批次')
    if unpriced:
        raise SettlementError('unpriced_usage', '存在缺价的使用，整批不能出账。', tuple(unpriced))

    lines: list[dict] = []

    def emit(*args) -> None:
        line = _line(*args)
        if line is not None:
            lines.append(line)

    for usage_id in sorted(set(old_index) | set(new_index)):
        old = old_index.get(usage_id)
        new = new_index.get(usage_id)
        if old and new:
            if _same_group(old, new):
                delta = _fee(new) - _fee(old)
                entry = SUPPLEMENT if delta > 0 else REFUND
                emit(usage_id, entry, delta, new, old, new)
            else:
                # 换馆或换渠道：原分组先冲回，再记入新分组。
                emit(usage_id, REVERSAL, -_fee(old), old, old, new)
                emit(usage_id, CHARGE, _fee(new), new, old, new)
        elif new:
            emit(usage_id, CHARGE, _fee(new), new, None, new)
        else:
            emit(usage_id, REVERSAL, -_fee(old), old, old, None)

    groups: dict[tuple[str, str], dict] = {}
    for line in lines:
        key = (line['group_archive'], line['group_channel'])
        group = groups.setdefault(key, {
            'archive': key[0], 'channel': key[1],
            'charge_cents': 0, 'reversal_cents': 0,
            'supplement_cents': 0, 'refund_cents': 0,
            'charge_count': 0, 'reversal_count': 0,
            'supplement_count': 0, 'refund_count': 0,
            'net_cents': 0, 'line_count': 0,
        })
        entry = line['entry_type']
        # 补收、新增记为正向金额；退还、冲回以正数量级展示。
        group[f'{entry}_cents'] += abs(line['amount_cents'])
        group[f'{entry}_count'] += 1
        group['net_cents'] += line['amount_cents']
        group['line_count'] += 1

    group_summary = [groups[key] for key in sorted(groups)]
    totals = {
        entry: sum(group[f'{entry}_cents'] for group in group_summary)
        for entry in (CHARGE, REVERSAL, SUPPLEMENT, REFUND)
    }
    old_total = sum(_fee(row) for row in old_index.values())
    new_total = sum(_fee(row) for row in new_index.values())
    net_cents = sum(line['amount_cents'] for line in lines)
    group_total = sum(group['net_cents'] for group in group_summary)
    expected = new_total - old_total
    balanced = (net_cents == expected and group_total == net_cents
                and totals[SUPPLEMENT] - totals[REFUND] + totals[CHARGE] - totals[REVERSAL] == net_cents)

    return {
        'old_usage_count': len(old_index),
        'new_usage_count': len(new_index),
        'line_count': len(lines),
        'old_total_cents': old_total,
        'new_total_cents': new_total,
        'net_cents': net_cents,
        'gross_charge_cents': totals[CHARGE] + totals[SUPPLEMENT],
        'gross_refund_cents': totals[REVERSAL] + totals[REFUND],
        'entry_totals': totals,
        'expected_net_cents': expected,
        'lines': lines,
        'group_summary': group_summary,
        'reconciliation': {
            'line_total_cents': net_cents,
            'group_total_cents': group_total,
            'net_cents': net_cents,
            'difference_cents': expected - net_cents,
            'balanced': balanced,
        },
    }
