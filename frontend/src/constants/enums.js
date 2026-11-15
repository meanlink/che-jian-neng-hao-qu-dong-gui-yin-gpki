export const Role={admin:'业务负责人',analyst:'分析员',viewer:'观察员'};
export const JobStatus={queued:'排队中',running:'计算中',completed:'已完成',failed:'执行失败'};
export const ReviewStatus={pending:'待负责人复核',approved:'已获业务批准',withdrawn:'已撤回'};
export const PlanLifecycle={active:'生效中',withdrawn:'已随结论撤回'};
export const DeliveryStatus={available:'可下载',withdrawn:'已撤回 · 仅审计'};
export const AuditAction={'job.approve':'结论批准','job.withdraw':'结论撤回','job.resubmit':'重新送审','delivery.download_denied':'下载被拒绝'};
