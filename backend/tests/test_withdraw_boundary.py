"""Concurrency between withdrawal and distribution.

SQLite cannot emulate MySQL row locks, so the boundary is exercised through
explicit ordering here and covered end-to-end in the container run:
  * snapshot committed before the withdrawal        -> sealed, download refused
  * snapshot attempt after the withdrawal boundary  -> nothing produced
  * retry of the same withdraw/approve/resubmit      -> no extra history row
"""
import json
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
def world(monkeypatch, tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/boundary.db')
    session = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr('src.config.database.engine', engine, raising=False)
    monkeypatch.setattr('src.config.database.Session', session, raising=False)
    monkeypatch.setattr('migrations.initial.engine', engine, raising=False)
    monkeypatch.setattr('src.config.settings.ARTIFACT_DIR', str(tmp_path / 'artifacts'), raising=False)
    migrate()
    s = session()
    creator = User(email='creator@demo.local', name='创建者', role='admin', password=hash_password('x'))
    reviewer = User(email='reviewer@demo.local', name='复核人', role='admin', password=hash_password('x'))
    s.add_all([creator, reviewer]); s.flush()
    rows = seed_records()
    d = Dataset(name='批次', source='x.csv', records=rows, checksum='c', created_at=time.time())
    s.add(d); s.flush()
    result = json.loads(json.dumps(analyze(rows, {'max_features': 2, 'scenario_pct': 10}), allow_nan=False))
    job = Job(name='归因试验', dataset_id=d.id, params={'max_features': 2}, status='completed', result=result,
              created_by=creator.id, created_at=time.time(), finished_at=time.time())
    s.add(job); s.flush()
    yield {'s': s, 'job': job, 'reviewer': reviewer, 'tmp': tmp_path}
    s.close()


def plan(job_id):
    return type('D', (), {'name': '简报', 'job_id': job_id, 'destination': '业务复核组',
                          'interval_seconds': 60, 'delay_seconds': 0})()


def test_existing_archive_sealed_and_next_snapshot_blocked(world):
    s, job, reviewer = world['s'], world['job'], world['reviewer']
    approvals.approve(s, job, reviewer, '批准'); s.commit()
    old_batch = job.approval_batch_id
    p = reports.create(s, plan(job.id)); s.commit()
    archive = reports.deliver(s, p); s.commit()
    assert archive.approval_batch_id == old_batch
    approvals.withdraw(s, job, reviewer, '样本选错'); s.commit()
    s.refresh(archive); s.refresh(p)
    assert archive.withdrawn_at is not None
    # subsequent request for the same link is refused even though the file exists
    ok, reason = approvals.archive_access(s, archive)
    assert not ok and '撤回' in reason
    assert (world['tmp'] / 'artifacts' / archive.filename).exists()
    # a second delivery attempt after the boundary creates nothing
    before = s.scalar(select(Delivery.id).where(Delivery.report_id == p.id).order_by(Delivery.id.desc()))
    p.next_run = time.time() - 1
    assert reports.deliver(s, p) is None
    s.commit()
    assert s.scalar(select(Delivery.id).where(Delivery.report_id == p.id).order_by(Delivery.id.desc())) == before


def test_reapproval_does_not_revive_old_archive_or_plan(world):
    s, job, reviewer = world['s'], world['job'], world['reviewer']
    approvals.approve(s, job, reviewer, '批准'); s.commit()
    p = reports.create(s, plan(job.id)); s.commit()
    archive = reports.deliver(s, p); s.commit()
    old_plan_id = p.id
    approvals.withdraw(s, job, reviewer, '撤回'); s.commit()
    approvals.resubmit(s, job, world['s'].get(User, job.created_by), ''); s.commit()
    approvals.approve(s, job, reviewer, '重新批准'); s.commit()
    s.refresh(p); s.refresh(archive)
    assert p.lifecycle == 'withdrawn' and not p.enabled
    assert archive.withdrawn_at is not None
    assert not approvals.archive_access(s, archive)[0]
    new_plan = reports.create(s, plan(job.id)); s.commit()
    assert new_plan.approval_batch_id == job.approval_batch_id != archive.approval_batch_id
    new_archive = reports.deliver(s, new_plan); s.commit()
    assert approvals.archive_access(s, new_archive)[0]


def test_history_counts_once_per_intent(world):
    s, job, reviewer = world['s'], world['job'], world['reviewer']
    for _ in range(3):
        approvals.approve(s, job, reviewer, '批准')
    s.commit()
    approvals.withdraw(s, job, reviewer, '原因')
    approvals.withdraw(s, job, reviewer, '原因')
    s.commit()
    creator = s.get(User, job.created_by)
    for _ in range(3):
        approvals.resubmit(s, job, creator, '说明')
    s.commit()
    counts = {}
    for a in s.scalars(select(Audit)):
        if a.detail.get('id') == job.id:
            counts[a.action] = counts.get(a.action, 0) + 1
    assert counts == {'job.approve': 1, 'job.withdraw': 1, 'job.resubmit': 1}
    batches = s.scalars(select(ApprovalBatch).where(ApprovalBatch.job_id == job.id)).all()
    assert len(batches) == 1 and batches[0].status == 'withdrawn'
