"""Approval lifecycle: approve, withdraw and resubmit an analysis conclusion.

One job points at exactly one approval batch. Withdrawal seals that batch for
good; re-approval always creates a fresh batch, so nothing tied to the old
batch (plans, archives, download links) can come back to life.

Retries are idempotent for the reviewer's intended state: repeating an approve,
withdraw or resubmit records no extra history row and produces no extra batch.
A caller acting on an older review revision (stale screen) gets 409 instead.
"""
import time
from fastapi import HTTPException
from sqlalchemy import select
from src.models import ApprovalBatch, Delivery, Job, Report
from src.services.audit import record


def batch_summary(batch):
    if not batch:
        return None
    return {
        'id': batch.id,
        'status': batch.status,
        'approved_by': batch.approved_by,
        'approved_by_name': batch.approved_by_name,
        'approved_at': batch.approved_at,
        'approve_note': batch.approve_note,
        'withdrawn_by': batch.withdrawn_by,
        'withdrawn_by_name': batch.withdrawn_by_name,
        'withdrawn_at': batch.withdrawn_at,
        'withdraw_reason': batch.withdraw_reason,
    }


def _stale(job, version):
    if version is not None and version != (job.review_version or 0):
        raise HTTPException(409, '结论状态已变化，请刷新后重试')
    return False


def approve(db, job, user, note='', version=None):
    """Approve a pending conclusion. Retrying the same approval is a no-op."""
    if job.created_by == user.id:
        raise HTTPException(403, '分析创建者无权批准自己的结论，请由其他业务负责人复核')
    if job.status != 'completed':
        raise HTTPException(409, '仅已完成结果可以批准')
    if job.review_status == 'approved' and job.approved:
        return job, False
    if job.review_status != 'pending':
        raise HTTPException(409, '结论已撤回，须重新送审后才能批准')
    _stale(job, version)
    batch = ApprovalBatch(
        job_id=job.id, status='active', approved_by=user.email, approved_by_name=user.name,
        approved_at=time.time(), approve_note=(note or '').strip()[:500],
    )
    db.add(batch)
    db.flush()
    job.approval_batch_id = batch.id
    job.review_status = 'approved'
    job.approved = True
    record(db, user.email, 'job.approve', {'id': job.id, 'batch': batch.id, 'note': batch.approve_note})
    return job, True


def withdraw(db, job, user, reason, version=None):
    """Withdraw an approved conclusion. Retrying the same withdrawal is a no-op."""
    reason = (reason or '').strip()
    if job.review_status == 'withdrawn' and not job.approved:
        return job, False
    if job.review_status != 'approved' or not job.approved:
        raise HTTPException(409, '仅已批准的结论可以撤回')
    if not reason:
        raise HTTPException(422, '撤回结论必须填写原因')
    _stale(job, version)
    now = time.time()
    batch = db.get(ApprovalBatch, job.approval_batch_id, with_for_update=True) if job.approval_batch_id else None
    if batch and batch.status == 'active':
        batch.status = 'withdrawn'
        batch.withdrawn_by = user.email
        batch.withdrawn_by_name = user.name
        batch.withdrawn_at = now
        batch.withdraw_reason = reason[:500]
    job.approved = False
    job.review_status = 'withdrawn'
    job.review_version = (job.review_version or 0) + 1
    # 撤回生效界：this blocks on the row lock held by an in-flight delivery snapshot,
    # so every snapshot committed before the boundary is sealed and no new one starts.
    for plan in db.scalars(select(Report).where(Report.job_id == job.id, Report.lifecycle == 'active').with_for_update()):
        plan.enabled = False
        plan.lifecycle = 'withdrawn'
        plan.withdrawn_at = now
    if batch:
        for archive in db.scalars(select(Delivery).where(
                Delivery.approval_batch_id == batch.id,
                Delivery.withdrawn_at.is_(None),
                Delivery.superseded_at.is_(None)).with_for_update()):
            archive.withdrawn_at = now
    record(db, user.email, 'job.withdraw', {
        'id': job.id, 'batch': job.approval_batch_id, 'reason': reason[:500],
    })
    return job, True


def resubmit(db, job, user, note='', version=None):
    """Send a withdrawn conclusion back for review. Retrying the same resubmit is a no-op."""
    if job.review_status == 'pending':
        return job, False
    if job.review_status != 'withdrawn':
        raise HTTPException(409, '仅已撤回的结论可以重新送审')
    if user.role not in ('admin', 'analyst') or (user.role == 'analyst' and user.id != job.created_by):
        raise HTTPException(403, '仅分析创建者或业务负责人可以重新送审')
    _stale(job, version)
    job.review_status = 'pending'
    job.approved = False
    job.review_version = (job.review_version or 0) + 1
    record(db, user.email, 'job.resubmit', {
        'id': job.id, 'batch': job.approval_batch_id, 'note': (note or '').strip()[:500],
    })
    return job, True


def archive_access(db, delivery):
    """A download link lives and dies with the approval batch that produced it."""
    if delivery.withdrawn_at is not None or delivery.superseded_at is not None:
        return False, '该归档所属的批准批次已撤回，文件仅保留审计记录'
    plan = db.get(Report, delivery.report_id)
    job = db.get(Job, plan.job_id) if plan else None
    if not plan or not job:
        return False, '归档来源计划不存在'
    if not job.approved or job.review_status != 'approved':
        return False, '该归档所属的批准批次已撤回，文件仅保留审计记录'
    if not delivery.approval_batch_id or job.approval_batch_id != delivery.approval_batch_id:
        return False, '旧批准批次的归档不能随重新批准恢复，仅供审计'
    batch = db.get(ApprovalBatch, delivery.approval_batch_id)
    if not batch or batch.status != 'active':
        return False, '该归档所属的批准批次已撤回，文件仅保留审计记录'
    return True, ''
