import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={
 list:()=>api('/jobs'),
 get:id=>api('/jobs/'+id),
 create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),
 approve:(id,body={})=>api('/jobs/'+id+'/approve',{method:'POST',body:JSON.stringify(body)}),
 withdraw:(id,body)=>api('/jobs/'+id+'/withdraw',{method:'POST',body:JSON.stringify(body)}),
 resubmit:(id,body={})=>api('/jobs/'+id+'/resubmit',{method:'POST',body:JSON.stringify(body)}),
 reviewHistory:id=>api('/jobs/'+id+'/review-history')
};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
