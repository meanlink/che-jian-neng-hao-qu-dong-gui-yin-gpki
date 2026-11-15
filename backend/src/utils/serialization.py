import hashlib, json
from src.models import ApprovalBatch
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j,db=None):
    from src.services.approvals import batch_summary
    batch = db.get(ApprovalBatch, j.approval_batch_id) if (db is not None and j.approval_batch_id) else None
    data = {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at','review_status','review_version','approval_batch_id','created_by']}
    data['approval_batch'] = batch_summary(batch) if batch else None
    data['withdraw_reason'] = batch.withdraw_reason if (batch and batch.status=='withdrawn') else ''
    return data
def report_dict(r):
    data = {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled','lifecycle','approval_batch_id','withdrawn_at','recertified_at']}
    data['status'] = 'withdrawn' if r.lifecycle=='withdrawn' else ('enabled' if r.enabled else 'paused')
    return data
def delivery_dict(d, db=None):
    from src.services.approvals import archive_access, batch_summary
    data = {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination','approval_batch_id','withdrawn_at','superseded_at']}
    # 是否可下载以服务端批次校验为准，列表不另行推断
    data['downloadable'], data['status_reason'] = archive_access(db, d) if db is not None else (d.withdrawn_at is None and d.superseded_at is None, '')
    data['status'] = 'available' if data['downloadable'] else 'withdrawn'
    batch = db.get(ApprovalBatch, d.approval_batch_id) if (db is not None and d.approval_batch_id) else None
    data['approval_batch'] = batch_summary(batch) if batch else None
    return data
