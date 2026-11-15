import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from sqlalchemy import select
from src.models import ApprovalBatch, Job, Report, Delivery
from src.config import settings


def _certified(db, job):
    """A job may feed distribution only when it is approved under its current active batch."""
    if not job or job.status != 'completed' or not job.approved or job.review_status != 'approved':
        return False
    if not job.approval_batch_id:
        return False
    batch = db.get(ApprovalBatch, job.approval_batch_id)
    return bool(batch and batch.status == 'active')


def create(db, data):
    j=db.get(Job,data.job_id)
    if not _certified(db, j):
        raise HTTPException(409,'请先选择已完成且获批准的当前批次分析结果；已撤回或旧批次的结论不能建立计划')
    r=Report(name=data.name, job_id=j.id, destination=data.destination, interval_seconds=data.interval_seconds, next_run=time.time()+data.delay_seconds, enabled=True, approval_batch_id=j.approval_batch_id, lifecycle='active')
    db.add(r); db.flush()
    return r


def deliver(db, report):
    """Create an archive snapshot. Lock rows so a concurrent withdrawal either lands
    before this snapshot (nothing is produced) or after it (the snapshot is sealed)."""
    job = db.scalars(select(Job).where(Job.id == report.job_id).with_for_update()).first()
    if not job or not _certified(db, job) or report.lifecycle != 'active' or not report.enabled:
        return
    if report.approval_batch_id != job.approval_batch_id:
        # The plan was certified under an older batch; it must never deliver again.
        return
    out=io.StringIO()
    out.write('﻿')
    table=job.result.get('table',{})
    cols=table.get('columns',[])
    writer=csv.writer(out)
    def safe(v):
        if isinstance(v,(int,float)) and not isinstance(v,bool): return v
        text=str(v)
        return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows',[]): writer.writerow([safe(row.get(c['key'],'')) for c in cols])
    data=out.getvalue().encode('utf-8')
    delivery=Delivery(report_id=report.id, created_at=time.time(), checksum=hashlib.sha256(data).hexdigest(), filename='', destination=report.destination, approval_batch_id=job.approval_batch_id)
    db.add(delivery); db.flush()
    delivery.filename=f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(settings.ARTIFACT_DIR,exist_ok=True)
    with open(os.path.join(settings.ARTIFACT_DIR,delivery.filename),'wb') as f:f.write(data)
    with open(os.path.join(settings.ARTIFACT_DIR,delivery.filename+'.json'),'w') as f: json.dump({'job':job.name,'params':job.params,'result':job.result,'checksum':delivery.checksum,'approval_batch':job.approval_batch_id},f,ensure_ascii=False,allow_nan=False)
    report.next_run=time.time()+report.interval_seconds
    return delivery
