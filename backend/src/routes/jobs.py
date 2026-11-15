from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Audit, ApprovalBatch, Job
from src.schemas.job import JobInput, ReviewNote
from src.middlewares.auth import current_user, can_write, can_review
from src.services import jobs, approvals
from src.services.audit import record
from src.utils.serialization import job_dict
router=APIRouter(prefix='/jobs')


def _lock(db, id):
    j=db.scalars(select(Job).where(Job.id==id).with_for_update()).first()
    if not j: raise HTTPException(404,'分析任务不存在')
    return j


@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    return [job_dict(j,db) for j in db.scalars(select(Job).order_by(Job.id.desc()).limit(100))]
@router.post('',status_code=201)
def create(data:JobInput,db=Depends(get_db),u=Depends(can_write)):
    j=jobs.create(db,data,u); record(db,u.email,'job.create',{'id':j.id,'params':j.params})
    db.commit(); jobs.enqueue(j.id); return job_dict(j,db)
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    return job_dict(j,db)
@router.get('/{id}/review-history')
def review_history(id:int,db=Depends(get_db),u=Depends(current_user)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    batches=[approvals.batch_summary(b) for b in db.scalars(select(ApprovalBatch).where(ApprovalBatch.job_id==id).order_by(ApprovalBatch.id.desc()))]
    events=[{'id':a.id,'actor':a.actor,'action':a.action,'detail':a.detail,'at':a.at} for a in db.scalars(select(Audit).where(Audit.action.in_(('job.approve','job.withdraw','job.resubmit'))).order_by(Audit.id.desc())) if a.detail.get('id')==id][:200]
    return {'job':job_dict(j,db),'batches':batches,'events':events}
@router.post('/{id}/approve')
def approve(id:int,data:ReviewNote|None=None,db=Depends(get_db),u=Depends(can_review)):
    j=_lock(db,id)
    data=data or ReviewNote()
    j,changed=approvals.approve(db,j,u,data.note,data.version)
    db.commit()
    return {**job_dict(j,db),'changed':changed}
@router.post('/{id}/withdraw')
def withdraw(id:int,data:ReviewNote|None=None,db=Depends(get_db),u=Depends(can_review)):
    j=_lock(db,id)
    data=data or ReviewNote()
    j,changed=approvals.withdraw(db,j,u,data.reason,data.version)
    db.commit()
    return {**job_dict(j,db),'changed':changed}
@router.post('/{id}/resubmit')
def resubmit(id:int,data:ReviewNote|None=None,db=Depends(get_db),u=Depends(current_user)):
    j=_lock(db,id)
    data=data or ReviewNote()
    j,changed=approvals.resubmit(db,j,u,data.note,data.version)
    db.commit()
    return {**job_dict(j,db),'changed':changed}
