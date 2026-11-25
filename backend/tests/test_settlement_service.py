"""补退款出账的服务层测试：真实 SQL 引擎（SQLite），覆盖幂等与单次接续。"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def billing(tmp_path):
    os.environ['DATABASE_URL'] = f'sqlite:///{tmp_path / "test.db"}'
    os.environ['REDIS_URL'] = 'redis://127.0.0.1:6379/15'
    os.environ['JWT_SECRET'] = 'x' * 40
    # 重新加载依赖引擎的模块，让它们指向本次临时库。
    for name in [key for key in sys.modules
                 if key == 'app' or key.startswith('app.') or key == 'scripts'
                 or key.startswith('scripts.')]:
        del sys.modules[name]
    import app.database as database
    from scripts.init_db import initialize
    initialize()

    from app.analysis.contracts import Decision, RunStatus
    from app.analysis.models import AnalysisRun, Review
    from app.auth.models import Account
    from app.auth.roles import Role
    from app.data.models import Dataset
    from app.errors import Problem
    from app.billing import service

    with database.Session.begin() as db:
        db.add(Account(email='reviewer@demo.local', role=Role.reviewer, password_hash='x$y'))
    return {'db': database, 'Run': AnalysisRun, 'Review': Review, 'Dataset': Dataset,
            'Decision': Decision, 'RunStatus': RunStatus, 'service': service, 'Problem': Problem}


def make_usage(usage_id, archive, channel, use_kind, fee, rate_id='R-1', status='priced'):
    return {'usage_id': usage_id, 'archive': archive, 'channel': channel, 'use_kind': use_kind,
            'used_on': '2026-11-01', 'usage_seconds': 15, 'rate_id': rate_id,
            'fee_cents': fee, 'status': status}


def add_run(billing, dataset_id, details, approved):
    Run, Review, Decision, RunStatus = (billing['Run'], billing['Review'],
                                        billing['Decision'], billing['RunStatus'])
    with billing['db'].Session.begin() as db:
        run = Run(dataset_id=dataset_id, status=RunStatus.completed, options={},
                  result={'tables': {'usage_pricing': details}, 'summary': {'total_fee_cents': 0}},
                  requested_by='analyst@demo.local')
        db.add(run)
        db.flush()
        if approved:
            db.add(Review(run_id=run.id, decision=Decision.approved, note='ok',
                          reviewer='reviewer@demo.local'))
        return run.id


def add_dataset(billing):
    with billing['db'].Session.begin() as db:
        dataset = billing['Dataset'](name='d.csv', checksum='abc', row_count=1,
                                     created_by='seed')
        db.add(dataset)
        db.flush()
        return dataset.id


def test_post_requires_approved_base(billing):
    dataset_id = add_dataset(billing)
    base = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1200)], approved=False)
    revision = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1500)], approved=False)
    with pytest.raises(billing['Problem']) as error:
        billing['service'].post_settlement(base, revision, 'reviewer@demo.local')
    assert error.value.code == 'base_not_approved'


def test_post_computes_net_and_freezes_report(billing):
    dataset_id = add_dataset(billing)
    base = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1200)], approved=True)
    revision = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1500)], approved=False)
    settlement, created = billing['service'].post_settlement(base, revision, 'reviewer@demo.local')
    assert created is True
    assert settlement.report['result']['summary']['net_cents'] == 300
    # 冻结快照：之后即使 revision 结果被改写，报告仍按原样返回。
    with billing['db'].Session.begin() as db:
        run = db.get(billing['Run'], revision)
        run.result = {'tables': {'usage_pricing': [make_usage('U1', 'A', 'doc', 'm', 9999)]}}
    with billing['db'].Session() as db:
        from app.billing.service import get_settlement
        assert get_settlement(db, settlement.id).report['result']['summary']['net_cents'] == 300


def test_repost_same_pair_is_idempotent(billing):
    dataset_id = add_dataset(billing)
    base = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1200)], approved=True)
    revision = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1500)], approved=False)
    first, created = billing['service'].post_settlement(base, revision, 'r@demo.local')
    again, created_again = billing['service'].post_settlement(base, revision, 'r@demo.local')
    assert created is True and created_again is False
    assert first.id == again.id


def test_second_revision_cannot_reuse_same_base(billing):
    dataset_id = add_dataset(billing)
    base = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1200)], approved=True)
    rev_one = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1500)], approved=False)
    rev_two = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1800)], approved=False)
    billing['service'].post_settlement(base, rev_one, 'r@demo.local')
    with pytest.raises(billing['Problem']) as error:
        billing['service'].post_settlement(base, rev_two, 'r@demo.local')
    assert error.value.code == 'base_already_settled'


def test_unpriced_revision_blocks_whole_batch(billing):
    dataset_id = add_dataset(billing)
    base = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1200)], approved=True)
    revision = add_run(billing, dataset_id,
                       [make_usage('U1', 'A', 'doc', 'm', None, status='missing_rate')], approved=False)
    with pytest.raises(billing['Problem']) as error:
        billing['service'].post_settlement(base, revision, 'r@demo.local')
    assert error.value.code == 'unpriced_usage'


def test_concurrent_revisions_only_one_continues_base(billing):
    import threading

    dataset_id = add_dataset(billing)
    base = add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', 1200)], approved=True)
    revisions = [add_run(billing, dataset_id, [make_usage('U1', 'A', 'doc', 'm', fee)], approved=False)
                 for fee in (1500, 1800)]

    outcomes = []
    barrier = threading.Barrier(len(revisions))

    def attempt(revision):
        barrier.wait()
        try:
            settlement, created = billing['service'].post_settlement(
                base, revision, 'r@demo.local')
            outcomes.append(('ok', created, settlement.revision_run_id))
        except billing['Problem'] as exc:
            outcomes.append(('problem', exc.code, revision))

    threads = [threading.Thread(target=attempt, args=(revision,)) for revision in revisions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    created = [item for item in outcomes if item[0] == 'ok' and item[1]]
    blocked = [item for item in outcomes if item[0] == 'problem']
    assert len(created) == 1, outcomes
    assert len(blocked) == 1, outcomes
    assert blocked[0][1] in {'base_already_settled'}
    # 旧账只接续一次：库里只有一条结算记录。
    from sqlalchemy import func, select
    with billing['db'].Session() as db:
        count = db.scalar(select(func.count()).select_from(billing['service'].Settlement))
    assert count == 1
