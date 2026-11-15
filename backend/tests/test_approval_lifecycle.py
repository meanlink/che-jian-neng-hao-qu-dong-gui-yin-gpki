import time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from migrations.initial import migrate
from src.models import ApprovalBatch, Audit, Dataset, Delivery, Job, User
from src.services import approvals, reports
from src.services.business import analyze, seed_records
from src.utils.security import hash_password


@pytest.fixture()
def db(monkeypatch, tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/test.db')
    session = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr('src.config.database.engine', engine, raising=False)
    monkeypatch.setattr('src.config.database.Session', session, raising=False)
    monkeypatch.setattr('migrations.initial.engine', engine, raising=False)
    migrate()
    s = session()
    admin = User(email='owner@demo.local', name='负责人', role='admin', password=hash_password('x'))
    other = User(email='admin2@demo.local', name='第二负责人', role='admin', password=hash_password('x'))
    analyst = User(email='analyst@demo.local', name='分析员', role='analyst', password=hash_password('x'))
    viewer = User(email='viewer@demo.local', name='观察员', role='viewer', password=hash_password('x'))
    s.add_all([admin, other, analyst, viewer]); s.flush()
    rows = seed_records()
    d = Dataset(name='批次', source='x.csv', records=rows, checksum='abc', created_at=time.time())
    s.add(d); s.flush()
    result = analyze(rows, {'max_features': 2, 'scenario_pct': 10})
    job = Job(name='归因试验', dataset_id=d.id, params={'max_features': 2}, status='completed',
              result=result, created_by=analyst.id, created_at=time.time(), finished_at=time.time())
    s.add(job); s.flush()
    yield {'s': s, 'job': job, 'admin': admin, 'other': other, 'analyst': analyst, 'viewer': viewer, 'dataset': d}
    s.close()


class Plan:
    def __init__(self, name='简报', job_id=0):
        self.name = name
        self.job_id = job_id
        self.destination = '业务复核组'
        self.interval_seconds = 60
        self.delay_seconds = 0


def make_plan(s, job, name='简报'):
    return reports.create(s, Plan(name, job.id))


def test_creator_cannot_approve_own_conclusion_even_as_admin(db):
    s, job, analyst = db['s'], db['job'], db['analyst']
    analyst.role = 'admin'; s.commit()
    with pytest.raises(Exception) as exc:
        approvals.approve(s, job, analyst, '')
    assert '创建者无权批准' in str(exc.value)
    approvals.approve(s, job, db['other'], '样本口径已核对'); s.commit()
    assert job.approved and job.review_status == 'approved' and job.approval_batch_id


def test_duplicate_approve_records_one_batch_and_one_audit(db):
    s, job, other = db['s'], db['job'], db['other']
    approvals.approve(s, job, other, 'ok'); s.commit()
    job, changed = approvals.approve(s, job, other, 'ok')
    assert changed is False
    batches = s.scalars(select(ApprovalBatch).where(ApprovalBatch.job_id == job.id)).all()
    audits = [a for a in s.scalars(select(Audit).where(Audit.action == 'job.approve')) if a.detail.get('id') == job.id]
    assert len(batches) == 1 and len(audits) == 1


def test_withdraw_seals_archives_and_plans_but_keeps_audit(db):
    s, job, other = db['s'], db['job'], db['other']
    approvals.approve(s, job, other, ''); s.commit()
    plan = make_plan(s, job); s.commit()
    delivery = reports.deliver(s, plan); s.commit()
    approvals.withdraw(s, job, other, '发现用错样本'); s.commit()
    s.refresh(delivery); s.refresh(plan)
    assert delivery.withdrawn_at is not None and delivery.filename
    assert plan.lifecycle == 'withdrawn' and plan.enabled is False
    allowed, reason = approvals.archive_access(s, delivery)
    assert not allowed and '撤回' in reason
    batch = s.get(ApprovalBatch, job.approval_batch_id)
    assert batch.status == 'withdrawn'
    assert batch.withdraw_reason == '发现用错样本'
    assert batch.approved_by == other.email


def test_duplicate_withdraw_is_idempotent(db):
    s, job, other = db['s'], db['job'], db['other']
    approvals.approve(s, job, other, ''); s.commit()
    approvals.withdraw(s, job, other, '原因 A'); s.commit()
    job, changed = approvals.withdraw(s, job, other, '原因 A')
    assert changed is False
    audits = [a for a in s.scalars(select(Audit).where(Audit.action == 'job.withdraw')) if a.detail.get('id') == job.id]
    assert len(audits) == 1


def test_withdraw_requires_reason(db):
    s, job, other = db['s'], db['job'], db['other']
    approvals.approve(s, job, other, ''); s.commit()
    with pytest.raises(Exception) as exc:
        approvals.withdraw(s, job, other, '   ')
    assert exc.value.status_code == 422


def test_reapproval_new_batch_old_plan_and_link_stay_dead(db):
    s, job, other = db['s'], db['job'], db['other']
    approvals.approve(s, job, other, 'b1'); s.commit()
    old_batch = job.approval_batch_id
    old_plan = make_plan(s, job, '旧简报'); s.commit()
    old_delivery = reports.deliver(s, old_plan); s.commit()
    approvals.withdraw(s, job, other, '样本错误'); s.commit()
    approvals.resubmit(s, job, db['analyst'], '已换正确样本'); s.commit()
    assert job.review_status == 'pending'
    job, changed = approvals.resubmit(s, job, db['analyst'], '已换正确样本')
    assert changed is False
    with pytest.raises(Exception):
        approvals.approve(s, job, db['analyst'], '')
    approvals.approve(s, job, other, 'b2'); s.commit()
    assert job.approval_batch_id != old_batch
    assert s.get(ApprovalBatch, old_batch).status == 'withdrawn'
    assert not approvals.archive_access(s, old_delivery)[0]
    with pytest.raises(Exception) as exc:
        reports.create(s, Plan('旧计划复活'))
    assert exc.value.status_code == 409
    new_plan = make_plan(s, job, '新简报'); s.commit()
    assert new_plan.approval_batch_id == job.approval_batch_id
    s.refresh(old_delivery)
    assert old_delivery.withdrawn_at is not None
    new_delivery = reports.deliver(s, new_plan); s.commit()
    assert approvals.archive_access(s, new_delivery)[0]
    assert new_delivery.approval_batch_id == job.approval_batch_id


def test_withdrawn_plan_does_not_deliver(db):
    s, job, other = db['s'], db['job'], db['other']
    approvals.approve(s, job, other, ''); s.commit()
    plan = make_plan(s, job); s.commit()
    approvals.withdraw(s, job, other, '停止'); s.commit()
    before = len(s.scalars(select(Delivery)).all())
    plan.next_run = time.time() - 1
    assert reports.deliver(s, plan) is None
    s.commit()
    assert len(s.scalars(select(Delivery)).all()) == before


def test_resubmit_requires_creator_or_admin(db):
    s, job, other = db['s'], db['job'], db['other']
    approvals.approve(s, job, other, ''); s.commit()
    approvals.withdraw(s, job, other, 'x'); s.commit()
    with pytest.raises(Exception) as exc:
        approvals.resubmit(s, job, db['viewer'], '')
    assert exc.value.status_code == 403
    # an analyst who did not create the conclusion may not resubmit it either
    colleague = User(email='analyst2@demo.local', name='另一分析员', role='analyst', password=hash_password('x'))
    s.add(colleague); s.commit()
    with pytest.raises(Exception) as exc:
        approvals.resubmit(s, job, colleague, '')
    assert exc.value.status_code == 403
    approvals.resubmit(s, job, db['analyst'], '创建者送审'); s.commit()
    assert job.review_status == 'pending'


def test_stale_review_revision_rejected(db):
    s, job, other = db['s'], db['job'], db['other']
    approvals.approve(s, job, other, ''); s.commit()
    version = job.review_version
    approvals.withdraw(s, job, other, 'x'); s.commit()
    with pytest.raises(Exception) as exc:
        approvals.approve(s, job, other, '', version)
    assert exc.value.status_code == 409
