/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,review_status:'pending'|'approved'|'withdrawn',review_version:number,approval_batch_id:number|null,approval_batch:Object|null,withdraw_reason:string,created_by:number}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean,lifecycle:'active'|'withdrawn',approval_batch_id:number|null}} ReportSchedule */
/** @typedef {{id:number,report_id:number,filename:string,destination:string,created_at:number,approval_batch_id:number|null,withdrawn_at:number|null,status:'available'|'withdrawn',downloadable:boolean}} Delivery */
export {};
