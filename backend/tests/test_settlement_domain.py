"""补退款口径的纯逻辑测试：不依赖数据库、Web 框架。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.settlement.settle import (  # noqa: E402
    CHARGE, REFUND, REVERSAL, SUPPLEMENT, SettlementError, settle,
)


def row(usage_id, archive, channel, use_kind, rate_id, fee, used_on='2026-11-01', status='priced'):
    return {'usage_id': usage_id, 'archive': archive, 'channel': channel, 'use_kind': use_kind,
            'used_on': used_on, 'usage_seconds': 15, 'rate_id': rate_id, 'fee_cents': fee,
            'status': status}


def lines_by_usage(result, usage_id):
    return [line for line in result['lines'] if line['usage_id'] == usage_id]


def test_supplement_when_rate_rises():
    old = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200)]
    new = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-02', 2200)]
    result = settle(old, new)
    [line] = result['lines']
    assert line['entry_type'] == SUPPLEMENT
    assert line['amount_cents'] == 1000
    assert result['net_cents'] == 1000
    assert result['reconciliation']['balanced'] is True


def test_refund_when_rate_drops():
    old = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 2200)]
    new = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-02', 1200)]
    result = settle(old, new)
    [line] = result['lines']
    assert line['entry_type'] == REFUND
    assert line['amount_cents'] == -1000
    assert result['net_cents'] == -1000
    assert result['group_summary'][0]['refund_cents'] == 1000
    assert result['reconciliation']['balanced'] is True


def test_unchanged_usage_emits_no_line():
    old = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200)]
    new = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200)]
    result = settle(old, new)
    assert result['lines'] == []
    assert result['net_cents'] == 0
    assert result['reconciliation']['balanced'] is True


def test_channel_change_reverses_old_then_charges_new_group():
    old = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200)]
    new = [row('U-001', '市影像馆', '馆内展映', '素材镜头', 'R-02', 900)]
    result = settle(old, new)
    reversal, charge = result['lines']
    assert reversal['entry_type'] == REVERSAL
    assert reversal['amount_cents'] == -1200
    assert (reversal['group_archive'], reversal['group_channel']) == ('市影像馆', '纪录片发行')
    assert charge['entry_type'] == CHARGE
    assert charge['amount_cents'] == 900
    assert (charge['group_archive'], charge['group_channel']) == ('市影像馆', '馆内展映')
    groups = {group['channel']: group for group in result['group_summary']}
    assert groups['纪录片发行']['net_cents'] == -1200
    assert groups['馆内展映']['net_cents'] == 900
    assert result['net_cents'] == -300


def test_archive_change_reverses_old_then_charges_new_group():
    old = [row('U-004', '海岸档案馆', '纪录片发行', '素材镜头', 'R-COAST', 2100)]
    new = [row('U-004', '市影像馆', '纪录片发行', '素材镜头', 'R-CITY', 2400)]
    result = settle(old, new)
    assert [line['entry_type'] for line in result['lines']] == [REVERSAL, CHARGE]
    assert result['net_cents'] == 300
    assert result['reconciliation']['balanced'] is True


def test_added_usage_fully_charged():
    old = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200)]
    new = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200),
           row('U-002', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 2400)]
    result = settle(old, new)
    [line] = result['lines']
    assert line['usage_id'] == 'U-002'
    assert line['entry_type'] == CHARGE and line['amount_cents'] == 2400
    assert result['net_cents'] == 2400


def test_revoked_usage_fully_reversed():
    old = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200),
           row('U-002', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 2400)]
    new = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200)]
    result = settle(old, new)
    [line] = result['lines']
    assert line['usage_id'] == 'U-002'
    assert line['entry_type'] == REVERSAL and line['amount_cents'] == -2400
    assert result['net_cents'] == -2400


def test_unpriced_usage_in_either_batch_blocks_settlement():
    old = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200)]
    new = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', None, None, status='missing_rate')]
    with pytest.raises(SettlementError) as error:
        settle(old, new)
    assert error.value.code == 'unpriced_usage'
    assert 'U-001' in error.value.usage_ids


def test_zero_priced_usage_is_priced_not_missing():
    old = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200)]
    new = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-02', 0)]
    result = settle(old, new)
    assert result['lines'][0]['entry_type'] == REFUND
    assert result['lines'][0]['amount_cents'] == -1200


def test_duplicate_usage_id_in_revision_is_rejected():
    old = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200)]
    new = [row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200),
           row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200)]
    with pytest.raises(SettlementError) as error:
        settle(old, new)
    assert error.value.code == 'duplicate_usage_id'


def test_reconciliation_always_balances_for_mixed_batch():
    old = [
        row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 2400),
        row('U-002', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 1200),
        row('U-003', '市影像馆', '纪录片发行', '素材镜头', 'R-02', 2200),
        row('U-004', '海岸档案馆', '纪录片发行', '素材镜头', 'R-COAST', 2100),
    ]
    new = [
        row('U-001', '市影像馆', '纪录片发行', '素材镜头', 'R-01', 2400),
        row('U-002', '市影像馆', '纪录片发行', '素材镜头', 'R-02', 1800),   # 费率下调
        row('U-003', '市影像馆', '馆内展映', '素材镜头', 'R-EX', 900),         # 换渠道
        row('U-005', '市影像馆', '馆内展映', '新闻短片', 'R-NEWS', 1500),      # 新增
    ]
    result = settle(old, new)
    assert result['expected_net_cents'] == result['net_cents']
    assert result['reconciliation']['balanced'] is True
    assert result['gross_charge_cents'] - result['gross_refund_cents'] == result['net_cents']
