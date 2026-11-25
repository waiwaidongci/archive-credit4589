"""端到端：导入→计价→复核→补退款出账，走真实 FastAPI 路由与领域逻辑。"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def client(tmp_path):
    os.environ['DATABASE_URL'] = f'sqlite:///{tmp_path / "api.db"}'
    os.environ['REDIS_URL'] = 'redis://127.0.0.1:6379/15'
    os.environ['JWT_SECRET'] = 'x' * 40
    os.environ['SEED_DEMO'] = 'true'
    for name in [key for key in sys.modules
                 if key == 'app' or key.startswith('app.') or key == 'scripts'
                 or key.startswith('scripts.') or key == 'domain' or key.startswith('domain.')]:
        del sys.modules[name]

    from fastapi.testclient import TestClient
    import app.main as main
    with TestClient(main.app) as test_client:
        yield test_client


def login(client, email='analyst@demo.local'):
    response = client.post('/api/auth/login',
                           json={'email': email, 'password': 'Local-demo-2026!'})
    assert response.status_code == 200, response.text
    return {'Authorization': f'Bearer {response.json()["access_token"]}'}


def run_analysis(client, headers, dataset_id):
    from app.analysis.runner import run_next
    response = client.post(f'/api/datasets/{dataset_id}/runs', json={'options': {}}, headers=headers)
    assert response.status_code == 202, response.text
    run_id = response.json()['id']
    while run_next():
        pass
    result = client.get(f'/api/runs/{run_id}', headers=headers)
    return run_id, result.json()


def seed_rows():
    from domain.spec import seed
    return seed()


def test_billing_flow_supplement_and_refund(client):
    analyst = login(client)
    reviewer = login(client, 'reviewer@demo.local')

    rows = seed_rows()
    imported = client.post('/api/datasets', json={'name': 'base.csv', 'rows': rows}, headers=analyst)
    assert imported.status_code == 201, imported.text
    base_dataset = imported.json()['id']
    base_run, base_result = run_analysis(client, analyst, base_dataset)
    assert base_result['status'] == 'completed'
    assert base_result['result']['publishable'] is True

    approved = client.post(f'/api/runs/{base_run}/review',
                           json={'decision': 'approved', 'note': '旧账核对'}, headers=reviewer)
    assert approved.status_code == 201, approved.text

    # 修订批次：U-004 换馆且改挂市影像馆合同（原 2100 分冲回，新 3300 分记入）。
    revised = [dict(row) for row in rows]
    for row in revised:
        if row['record_id'] == 'U-004' and row['row_type'] == 'usage':
            row.update(archive='市影像馆', channel='纪录片发行', use_kind='素材镜头',
                       contract_id='C-CITY')
    imported = client.post('/api/datasets', json={'name': 'revised.csv', 'rows': revised}, headers=analyst)
    assert imported.status_code == 201, imported.text
    revision_dataset = imported.json()['id']
    revision_run, revision_result = run_analysis(client, analyst, revision_dataset)
    assert revision_result['result']['publishable'] is True
    revision_fees = {row['usage_id']: row['fee_cents']
                     for row in revision_result['result']['tables']['usage_pricing']}
    assert revision_fees['U-004'] == 3300

    settlement = client.post('/api/settlements',
                             json={'base_run_id': base_run, 'revision_run_id': revision_run},
                             headers=reviewer)
    assert settlement.status_code == 201, settlement.text
    body = settlement.json()
    lines = body['result']['tables']['settlement_lines']
    u004 = [line for line in lines if line['usage_id'] == 'U-004']
    assert [line['entry_type'] for line in u004] == ['reversal', 'charge']
    assert u004[0]['amount_cents'] == -2100
    assert (u004[0]['group_archive'], u004[0]['group_channel']) == ('海岸档案馆', '纪录片发行')
    assert u004[1]['amount_cents'] == 3300
    assert (u004[1]['group_archive'], u004[1]['group_channel']) == ('市影像馆', '纪录片发行')
    # 只有 U-004 一处变化，净补 1200 分；各层对平。
    assert [line['usage_id'] for line in lines] == ['U-004', 'U-004']
    assert body['result']['summary']['net_cents'] == 1200
    assert body['result']['reconciliation']['balanced'] is True

    # 报告可按原样查回，且带 CSV 导出。
    fetched = client.get(f'/api/settlements/{body["settlement_id"]}', headers=reviewer)
    assert fetched.status_code == 200
    assert fetched.json()['result']['summary']['net_cents'] == body['result']['summary']['net_cents']
    csv_resp = client.get(f'/api/settlements/{body["settlement_id"]}/csv?table=settlement_lines',
                          headers=reviewer)
    assert csv_resp.status_code == 200
    assert 'entry_type' in csv_resp.text


def test_billing_rejects_second_revision(client):
    analyst = login(client)
    reviewer = login(client, 'reviewer@demo.local')
    rows = seed_rows()
    base_dataset = client.post('/api/datasets', json={'name': 'b1.csv', 'rows': rows},
                               headers=analyst).json()['id']
    base_run, _ = run_analysis(client, analyst, base_dataset)
    client.post(f'/api/runs/{base_run}/review',
                json={'decision': 'approved', 'note': 'ok'}, headers=reviewer)

    revised = [dict(row) for row in rows]
    for row in revised:
        if row['record_id'] == 'U-005' and row['row_type'] == 'usage':
            row['usage_seconds'] = 60
    rev_dataset = client.post('/api/datasets', json={'name': 'b2.csv', 'rows': revised},
                              headers=analyst).json()['id']
    revision_run, _ = run_analysis(client, analyst, rev_dataset)

    first = client.post('/api/settlements',
                        json={'base_run_id': base_run, 'revision_run_id': revision_run},
                        headers=reviewer)
    assert first.status_code == 201, first.text
    second = client.post('/api/settlements',
                         json={'base_run_id': base_run, 'revision_run_id': revision_run},
                         headers=reviewer)
    assert second.status_code == 200  # 幂等
    assert second.json()['settlement_id'] == first.json()['settlement_id']


def test_unapproved_base_cannot_settle(client):
    analyst = login(client)
    reviewer = login(client, 'reviewer@demo.local')
    rows = seed_rows()
    dataset = client.post('/api/datasets', json={'name': 'c1.csv', 'rows': rows},
                          headers=analyst).json()['id']
    base_run, _ = run_analysis(client, analyst, dataset)  # 未复核
    revision_run, _ = run_analysis(client, analyst, dataset)
    response = client.post('/api/settlements',
                           json={'base_run_id': base_run, 'revision_run_id': revision_run},
                           headers=reviewer)
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'base_not_approved'


def test_analyst_cannot_post_settlement(client):
    analyst = login(client)
    response = client.post('/api/settlements',
                           json={'base_run_id': 1, 'revision_run_id': 2}, headers=analyst)
    assert response.status_code == 403
