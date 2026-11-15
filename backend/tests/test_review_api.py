import json
import time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from fastapi.testclient import TestClient

from migrations.initial import migrate
from src.models import Dataset, Job, Report, User
from src.services.business import analyze, seed_records
from src.utils.security import hash_password


@pytest.fixture()
def app(monkeypatch, tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/api.db', connect_args={'check_same_thread': False})
    session = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr('src.config.database.engine', engine, raising=False)
    monkeypatch.setattr('src.config.database.Session', session, raising=False)
    monkeypatch.setattr('migrations.initial.engine', engine, raising=False)
    monkeypatch.setenv('SEED_DEMO', 'false')
    monkeypatch.setenv('ARTIFACT_DIR', str(tmp_path / 'artifacts'))
    monkeypatch.setattr('src.config.settings.ARTIFACT_DIR', str(tmp_path / 'artifacts'), raising=False)
    migrate()
    s = session()
    admin = User(email='owner@demo.local', name='林知', role='admin', password=hash_password('Demo123!'))
    other = User(email='admin2@demo.local', name='何川', role='admin', password=hash_password('Demo123!'))
    analyst = User(email='analyst@demo.local', name='陈舟', role='analyst', password=hash_password('Demo123!'))
    viewer = User(email='viewer@demo.local', name='周禾', role='viewer', password=hash_password('Demo123!'))
    s.add_all([admin, other, analyst, viewer]); s.flush()
    rows = seed_records()
    d = Dataset(name='批次', source='x.csv', records=rows, checksum='abc', created_at=time.time())
    s.add(d); s.flush()
    result = json.loads(json.dumps(analyze(rows, {'max_features': 2, 'scenario_pct': 10}), allow_nan=False))
    job = Job(name='负责人本人发起的结论', dataset_id=d.id, params={'max_features': 2}, status='completed',
              result=result, created_by=admin.id, created_at=time.time(), finished_at=time.time())
    s.add(job); s.commit()
    job_id = job.id
    s.close()
    client = TestClient(__import__('src.main', fromlist=['app']).app)
    yield {'client': client, 'session': session, 'job_id': job_id, 'tmp': tmp_path}
    client.close()


def auth(client, email):
    r = client.post('/auth/login', json={'email': email, 'password': 'Demo123!'})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def make_plan(session, job_id, name='简报'):
    from src.services import reports
    with session() as s:
        plan = reports.create(s, type('D', (), {'name': name, 'job_id': job_id, 'destination': '业务复核组',
                                                 'interval_seconds': 60, 'delay_seconds': 0})())
        s.commit()
        return plan.id


def run_delivery(session, plan_id):
    from src.services import reports
    with session() as s:
        delivery = reports.deliver(s, s.get(Report, plan_id))
        s.commit()
        return delivery.id if delivery else None


def test_api_full_withdrawal_cycle(app):
    c = app['client']
    session = app['session']
    job_id = app['job_id']
    owner = auth(c, 'owner@demo.local')
    second = auth(c, 'admin2@demo.local')
    analyst = auth(c, 'analyst@demo.local')
    viewer = auth(c, 'viewer@demo.local')

    # creator (an admin) may not approve own conclusion; analysts cannot approve at all
    r = c.post(f'/jobs/{job_id}/approve', headers=owner, json={'note': '自批'})
    assert r.status_code == 403 and '创建者无权批准' in r.json()['detail']
    r = c.post(f'/jobs/{job_id}/approve', headers=analyst, json={})
    assert r.status_code == 403
    r = c.post(f'/jobs/{job_id}/approve', headers=second, json={'note': '口径已核对'})
    assert r.status_code == 200
    body = r.json()
    assert body['review_status'] == 'approved' and body['approval_batch']['approved_by_name'] == '何川'
    old_batch = body['approval_batch_id']

    plan_id = make_plan(session, job_id, '例会简报')
    delivery_id = run_delivery(session, plan_id)
    assert delivery_id
    r = c.get(f'/deliveries/{delivery_id}/download?format=csv', headers=viewer)
    assert r.status_code == 200 and r.content

    # withdraw without reason is rejected, with reason succeeds
    r = c.post(f'/jobs/{job_id}/withdraw', headers=second, json={'reason': ' '})
    assert r.status_code == 422
    r = c.post(f'/jobs/{job_id}/withdraw', headers=second, json={'reason': '发现用错样本'})
    assert r.status_code == 200 and r.json()['changed'] is True
    assert r.json()['review_status'] == 'withdrawn'
    batch = r.json()['approval_batch']
    assert batch['status'] == 'withdrawn' and batch['withdraw_reason'] == '发现用错样本'

    # retry withdraw is idempotent: no extra history
    r = c.post(f'/jobs/{job_id}/withdraw', headers=second, json={'reason': '发现用错样本'})
    assert r.status_code == 200 and r.json()['changed'] is False
    audits = [a for a in c.get('/audits', headers=owner).json() if a['action'] == 'job.withdraw']
    assert len(audits) == 1
    r = c.get(f'/jobs/{job_id}', headers=analyst).json()
    assert r['review_status'] == 'withdrawn' and r['withdraw_reason'] == '发现用错样本'

    # archived file kept for audit but download refused
    for fmt in ('csv', 'json'):
        r = c.get(f'/deliveries/{delivery_id}/download?format={fmt}', headers=viewer)
        assert r.status_code == 410 and '撤回' in r.json()['detail']
    denied = [a for a in c.get('/audits', headers=owner).json() if a['action'] == 'delivery.download_denied']
    assert len(denied) == 2 and denied[0]['detail']['batch'] == old_batch
    inbox = c.get('/deliveries', headers=viewer).json()
    d = next(x for x in inbox if x['id'] == delivery_id)
    assert d['filename'] and d['downloadable'] is False and d['status'] == 'withdrawn'

    # old plan is dead; cannot re-enable; cannot create under withdrawn conclusion
    r = c.post(f'/reports/{plan_id}/toggle', headers=second)
    assert r.status_code == 409
    r = c.post('/reports', headers=second, json={'name': '旧计划复活', 'job_id': job_id, 'destination': '业务复核组',
                                                 'interval_seconds': 60, 'delay_seconds': 0})
    assert r.status_code == 409
    plans = c.get('/reports', headers=owner).json()
    assert next(p for p in plans if p['id'] == plan_id)['lifecycle'] == 'withdrawn'

    # approval is blocked until resubmission; duplicate resubmit adds no history
    r = c.post(f'/jobs/{job_id}/approve', headers=second, json={})
    assert r.status_code == 409 and '重新送审' in r.json()['detail']
    r = c.post(f'/jobs/{job_id}/resubmit', headers=owner, json={'note': '已换正确样本'})
    assert r.status_code == 200 and r.json()['review_status'] == 'pending'
    r = c.post(f'/jobs/{job_id}/resubmit', headers=owner, json={})
    assert r.json()['changed'] is False
    r = c.post(f'/jobs/{job_id}/approve', headers=second, json={'note': '新批次复核'})
    assert r.status_code == 200
    result = r.json()
    assert result['approval_batch_id'] != old_batch
    assert result['approval_batch']['id'] != batch['id']

    # old delivery stays dead even after re-approval; old plan does not revive
    r = c.get(f'/deliveries/{delivery_id}/download?format=csv', headers=viewer)
    assert r.status_code == 410
    r = c.post(f'/reports/{plan_id}/toggle', headers=second)
    assert r.status_code == 409
    # a new plan under the new batch works and its archive downloads
    new_plan_id = make_plan(session, job_id, '新简报')
    new_delivery_id = run_delivery(session, new_plan_id)
    assert new_delivery_id != delivery_id
    r = c.get(f'/deliveries/{new_delivery_id}/download?format=csv', headers=viewer)
    assert r.status_code == 200
    # review history lets the inbox reconcile approver, reason, batch and status
    h = c.get(f'/jobs/{job_id}/review-history', headers=viewer).json()
    assert [b['status'] for b in h['batches']] == ['active', 'withdrawn']
    assert h['batches'][1]['withdraw_reason'] == '发现用错样本'
    assert h['batches'][1]['approved_by'] == 'admin2@demo.local'
    assert [e['action'] for e in h['events']] == ['job.approve', 'job.resubmit', 'job.withdraw', 'job.approve']


def test_duplicate_resubmit_and_stale_version(app):
    c = app['client']
    job_id = app['job_id']
    owner = auth(c, 'owner@demo.local')
    second = auth(c, 'admin2@demo.local')
    c.post(f'/jobs/{job_id}/approve', headers=second, json={})
    version = c.get(f'/jobs/{job_id}', headers=owner).json()['review_version']
    c.post(f'/jobs/{job_id}/withdraw', headers=second, json={'reason': 'r'})
    r = c.post(f'/jobs/{job_id}/approve', headers=second, json={'version': version})
    assert r.status_code == 409
    r = c.post(f'/jobs/{job_id}/resubmit', headers=owner, json={'version': version})
    assert r.status_code == 409
    r = c.post(f'/jobs/{job_id}/resubmit', headers=owner, json={})
    assert r.status_code == 200
    h = c.get(f'/jobs/{job_id}/review-history', headers=owner).json()
    assert len([e for e in h['events'] if e['action'] == 'job.resubmit']) == 1


def test_withdraw_boundary_seals_archive_and_blocks_new_snapshot(app):
    """A snapshot committed before the withdrawal boundary is sealed; a delivery
    attempt after the boundary produces nothing. Old links never come back."""
    from src.services import approvals, reports
    session = app['session']
    job_id = app['job_id']
    with session() as s:
        job = s.get(Job, job_id)
        other = s.scalar(select(User).where(User.email == 'admin2@demo.local'))
        approvals.approve(s, job, other, 'b1'); s.commit()
        plan = reports.create(s, type('D', (), {'name': '并发简报', 'job_id': job_id, 'destination': '业务复核组',
                                                 'interval_seconds': 60, 'delay_seconds': 0})()); s.commit()
        first = reports.deliver(s, plan); s.commit()
        first_id = first.id
        approvals.withdraw(s, job, other, '撤回'); s.commit()
        assert reports.deliver(s, plan) is None
        s.commit()
        assert approvals.archive_access(s, s.get(type(first), first_id))[0] is False
