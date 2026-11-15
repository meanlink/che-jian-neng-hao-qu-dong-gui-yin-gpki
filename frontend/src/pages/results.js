import {jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {chart} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
const REVIEW={pending:'待负责人复核',approved:'已获业务批准',withdrawn:'已撤回 · 仅留审计'};
function reviewLabel(j){return REVIEW[j.review_status]||(j.approved?'已获业务批准':'待负责人复核');}
function reviewPanel(j,history){
 const b=(history&&history.batches||[])[0];
 const shownBatch=j.review_status==='approved'||j.review_status==='withdrawn'?b:null;
 const isAdmin=session.user.role==='admin',isCreator=j.created_by===session.user.id;
 const canApprove=isAdmin&&j.status==='completed'&&j.review_status==='pending'&&!isCreator;
 const canWithdraw=isAdmin&&j.review_status==='approved';
 const canResubmit=j.review_status==='withdrawn'&&(isAdmin||(isCreator&&session.user.role==='analyst'));
 const rows=(history&&history.batches||[]).map(x=>'<tr><td>'+x.id+'</td><td>'+esc(x.status==='active'?'生效中':'已撤回')+'</td><td>'+esc(x.approved_by_name||x.approved_by)+' · '+date(x.approved_at)+'</td><td>'+esc(x.withdrawn_by_name||x.withdrawn_by||'—')+(x.withdrawn_at?' · '+date(x.withdrawn_at):'')+'</td><td>'+esc(x.withdraw_reason||'—')+'</td></tr>').join('');
 return '<section class="method-sheet compact review-sheet"><p class="eyebrow">APPROVAL / WITHDRAWAL</p><h3>审批与撤回</h3>'+
  '<p class="review-state">当前状态：<strong>'+esc(reviewLabel(j))+'</strong>'+(shownBatch?'<span> · 批准批次 #'+shownBatch.id+' · '+esc(shownBatch.approved_by_name||shownBatch.approved_by)+'</span>':'')+'</p>'+
  (j.review_status==='withdrawn'?'<p class="warning">结论已撤回，原因：'+esc(j.withdraw_reason||'—')+'。已归档文件仅保留审计记录，不可下载；旧分发计划不能复活，重新批准后须另建计划。</p>':'')+
  (isCreator&&j.review_status==='pending'?'<p class="hint">你是本结论的创建者，不能批准自己的结论，请由其他业务负责人复核。</p>':'')+
  '<div class="review-actions">'+
   (canApprove?'<button class="primary" id="approve-job">批准此业务结论</button>':'')+
   (canWithdraw?'<button class="button" id="open-withdraw">撤回此结论</button>':'')+
   (canResubmit?'<button class="primary" id="resubmit-job">重新送审</button>':'')+
  '</div>'+
  '<div id="withdraw-form" hidden><label>撤回原因（必填）<input id="withdraw-reason" maxlength="500" placeholder="例如：发现用错样本"></label><div class="review-actions"><button class="button" id="confirm-withdraw">确认撤回</button><button class="text-button" id="cancel-withdraw">取消</button></div></div>'+
  '<p class="hint">仅当前获批批次的结论可进入分发；撤回后旧计划与旧下载链接不可恢复。</p>'+
  (rows?'<div class="table-wrap"><table><thead><tr><th>批准批次</th><th>状态</th><th>批准人 / 时间</th><th>撤回人 / 时间</th><th>撤回原因</th></tr></thead><tbody>'+rows+'</tbody></table></div>':'')+
 '</section>';
}
export async function results(id){
 workspace.jobs=await jobs.list();const j=id?await jobs.get(id):(workspace.jobs.find(j=>j.id===workspace.selectedJob)||workspace.jobs[0]);
 if(j&&!workspace.jobs.some(x=>x.id===j.id))workspace.jobs.push(j);
 if(!j)return heading('04 / REVIEW','结果复核','尚无分析结果。')+'<div class="empty">先到分析工作台，选择批次并提交一次计算。<a href="#/workbench">前往工作台 ↗</a></div>';
 workspace.selectedJob=j.id;const r=j.result||{};
 const history=j.status==='completed'?await jobs.reviewHistory(j.id):null;
 return heading('04 / REVIEW','结果复核与业务解释',j.name,'<button class="button" id="refresh-results">刷新结果 ↻</button>')+'<div class="result-selector"><label>分析记录<select id="select-job">'+workspace.jobs.map(x=>'<option value="'+x.id+'" '+(x.id===j.id?'selected':'')+'>'+esc(x.name)+' · '+esc(x.status)+'</option>').join('')+'</select></label>'+status(j.status)+'<span>'+date(j.created_at)+'</span><span class="approval '+(j.review_status||'')+'">'+esc(reviewLabel(j))+'</span></div>'+(j.status==='completed'?'<section class="result-lead"><p class="eyebrow">COMPUTED FINDING</p><h2>'+esc(r.summary)+'</h2><div class="metrics">'+(r.metrics||[]).map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'<small>'+esc(m.unit||'')+'</small></strong></div>').join('')+'</div></section><section class="panel">'+chart(r.chart)+'</section><div class="two-columns"><section class="panel"><div class="section-title"><h2>业务解释</h2><span>由计算结果生成</span></div><ol class="questions">'+(r.findings||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ol>'+(r.warnings||[]).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+'</section>'+reviewPanel(j,history)+'</div><section class="panel"><div class="section-title"><h2>结果明细</h2><span>'+(r.table?.rows?.length||0)+' 行</span></div>'+table(r.table?.columns||[],r.table?.rows||[])+'</section>':'<section class="panel empty">'+(j.status==='failed'?'计算失败：'+esc(j.error)+'。请返回工作台调整参数或数据。':'后台正在执行计算。点击刷新结果查看最新进展。')+'<a href="#/workbench">返回工作台 ↗</a></section>');
}
export function bindResults(refresh){
 document.querySelector('#refresh-results')?.addEventListener('click',refresh);
 document.querySelector('#select-job')?.addEventListener('change',e=>{workspace.selectedJob=Number(e.target.value);location.hash='#/results/'+e.target.value;});
 const act=async(fn,ok)=>{try{await fn();notify(ok);await refresh();}catch(e){notify(e.message,true);}};
 document.querySelector('#approve-job')?.addEventListener('click',()=>act(()=>jobs.approve(workspace.selectedJob,{version:workspace.jobs.find(j=>j.id===workspace.selectedJob)?.review_version}),'已批准，可创建分发计划'));
 document.querySelector('#open-withdraw')?.addEventListener('click',()=>{const f=document.querySelector('#withdraw-form');f.hidden=false;document.querySelector('#withdraw-reason').focus();});
 document.querySelector('#cancel-withdraw')?.addEventListener('click',()=>{document.querySelector('#withdraw-form').hidden=true;});
 document.querySelector('#confirm-withdraw')?.addEventListener('click',()=>{const reason=document.querySelector('#withdraw-reason').value.trim();if(!reason)return notify('请填写撤回原因',true);act(()=>jobs.withdraw(workspace.selectedJob,{reason,version:workspace.jobs.find(j=>j.id===workspace.selectedJob)?.review_version}),'结论已撤回，旧归档仅留审计');});
 document.querySelector('#resubmit-job')?.addEventListener('click',()=>act(()=>jobs.resubmit(workspace.selectedJob,{version:workspace.jobs.find(j=>j.id===workspace.selectedJob)?.review_version}),'已重新送审，等待负责人复核'));
}
