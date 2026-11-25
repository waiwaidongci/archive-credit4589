from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.analysis.contracts import Decision, RunStatus
from app.analysis.models import Review
from app.analysis.repository import get_run
from app.billing.models import Settlement
from app.clock import utc_iso
from app.data.repository import get_dataset
from app.database import Session
from app.errors import Problem
from app.ops.audit import audit
from domain.settlement.settle import SettlementError, settle


def _batch(db, run, label: str, require_approval: bool) -> dict:
    if run.status != RunStatus.completed:
        raise Problem(409, 'run_not_completed', f'{label}尚未完成计价，不能出账')
    result = run.result or {}
    tables = result.get('tables') or {}
    details = tables.get('usage_pricing')
    if not isinstance(details, list):
        raise Problem(409, 'run_result_missing', f'{label}缺少逐笔计价明细')
    review = db.get(Review, run.id)
    if require_approval and (review is None or review.decision != Decision.approved):
        raise Problem(409, 'base_not_approved', '只有已批准出账的批次才能作为旧账接续')
    return {'run_id': run.id, 'details': details, 'review': review,
            'dataset': get_dataset(db, run.dataset_id), 'summary': result.get('summary') or {}}


def _describe_batch(batch: dict) -> dict:
    dataset = batch['dataset']
    review = batch['review']
    return {
        'run_id': batch['run_id'],
        'dataset': {'id': dataset.id, 'name': dataset.name, 'checksum': dataset.checksum,
                    'row_count': dataset.row_count},
        'summary': batch['summary'],
        'review': None if review is None else {'decision': review.decision, 'reviewer': review.reviewer},
    }


def _build_report(settlement: Settlement, base: dict, revision: dict, result: dict) -> dict:
    return {
        'settlement_id': settlement.id,
        'base_run_id': settlement.base_run_id,
        'revision_run_id': settlement.revision_run_id,
        'posted_by': settlement.posted_by,
        'base': _describe_batch(base),
        'revision': _describe_batch(revision),
        'result': {
            'summary': {key: result[key] for key in (
                'old_usage_count', 'new_usage_count', 'line_count', 'old_total_cents',
                'new_total_cents', 'net_cents', 'gross_charge_cents', 'gross_refund_cents',
                'expected_net_cents')},
            'tables': {'settlement_lines': result['lines'],
                       'settlement_groups': result['group_summary']},
            'reconciliation': result['reconciliation'],
        },
    }


def _settle_once(base_run_id: int, revision_run_id: int, actor: str) -> tuple[Settlement, bool]:
    if base_run_id == revision_run_id:
        raise Problem(422, 'same_run', '旧账与修订批次不能是同一次运行')
    try:
        with Session.begin() as db:
            base_run = get_run(db, base_run_id, lock=True)
            revision_run = get_run(db, revision_run_id)
            previous = db.scalar(select(Settlement).where(Settlement.base_run_id == base_run_id))
            if previous is not None:
                if previous.revision_run_id == revision_run_id:
                    return previous, False
                raise Problem(409, 'base_already_settled',
                              '这份旧账已由另一份修订批次接续，不能重复出账')
            base = _batch(db, base_run, '已出账批次', require_approval=True)
            revision = _batch(db, revision_run, '修订批次', require_approval=False)
            try:
                result = settle(base['details'], revision['details'])
            except SettlementError as exc:
                raise Problem(409, exc.code, str(exc)) from None
            if not result['reconciliation']['balanced']:
                raise Problem(409, 'settlement_unbalanced', '补退款明细与两批总额未对平')
            settlement = Settlement(base_run_id=base_run_id, revision_run_id=revision_run_id,
                                    posted_by=actor, report={})
            db.add(settlement)
            db.flush()
            settlement.report = _build_report(settlement, base, revision, result)
            audit(db, actor, 'settlement_posted', f'settlement/{settlement.id}')
            return settlement, True
    except IntegrityError:
        # 并发：另一事务抢先写入了这份旧账的接续记录。
        with Session() as db:
            previous = db.scalar(select(Settlement).where(Settlement.base_run_id == base_run_id))
        if previous is not None and previous.revision_run_id == revision_run_id:
            return previous, False
        raise Problem(409, 'base_already_settled', '这份旧账已由另一份修订批次接续，不能重复出账') from None


def post_settlement(base_run_id: int, revision_run_id: int, actor: str) -> tuple[Settlement, bool]:
    return _settle_once(base_run_id, revision_run_id, actor)


def describe(settlement: Settlement) -> dict:
    return {**settlement.report,
            'created_at': utc_iso(settlement.created_at)}


def get_settlement(db, settlement_id: int) -> Settlement:
    settlement = db.get(Settlement, settlement_id)
    if settlement is None:
        raise Problem(404, 'settlement_not_found', '补退款出账记录不存在')
    return settlement
