'use strict';
const CampusViews = (() => {
  const q = v => v==null?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2});
  const safe=html, stateNames={passed:'已通过',failed:'未通过',enrolled:'在读',remaining:'未修'};
  const link=(id,title,primary=false)=>`<button class="campus-button ${primary?'is-primary':''}" data-page="${id}">${safe(title)}</button>`;
  const title=(name,aside='')=>`<div class="business-title"><h1>${safe(name)}</h1><div>${aside}</div></div>`;
  const note=value=>`<p class="business-note">${safe(value)}</p>`;
  const table=(labels,rows,mobileRecords=false)=>`<div class="business-table-wrap"><table class="business-table"${mobileRecords?' data-campus-records':''}><thead><tr>${labels.map(l=>`<th scope="col">${safe(l)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
  const cell=(v,cls='')=>`<td class="${cls}">${safe(v)}</td>`;
  const row=(...cells)=>`<tr>${cells.join('')}</tr>`;
  const flag=(label,tone='quiet')=>`<span class="course-flag ${tone}">${safe(label)}</span>`;
  const flagCell=(l,t)=>`<td>${flag(l,t)}</td>`;
  const groupTitle=(s)=>`<h2 class="business-subtitle">${safe(s)}</h2>`;
  const button=(id,text)=>`<button class="campus-link" data-page="${id}">${safe(text)} ›</button>`;
  const uri=s=>apiStudent(S.user.id)+'/'+s;
  function metrics(items){return `<dl class="credit-strip">${items.map(([label,value,sub])=>`<div><dt>${safe(label)}</dt><dd>${q(value)}<small>学分</small></dd><dd class="metric-hint">${safe(sub)}</dd></div>`).join('')}</dl>`;}
  function checks(a){return (a.checks||[]).map(c=>row(cell(c.name),cell(q(c.target)),cell(q(c.value)),flagCell(c.met?'已达到':a.quality.historyComplete?'尚未达到':'待核对',c.met?'pass':'quiet'),cell(c.sourcePage?'第 '+c.sourcePage+' 页':'—'))).join('');}
  function courseState(c,a){return c.state==='remaining'&&!a.quality.historyComplete?'无已导入记录':stateNames[c.state];}
  function tree(a){
    const filter=document.querySelector('#unmet-only')?.checked||false;
    const search=(document.querySelector('#campus-course-search')?.value||'').trim().toLowerCase();
    const courseTbl=items=>table(['课程名称','课程代码','性质','学分','修读状态'],items.map(c=>row(cell(c.name),cell(c.code),cell(c.required?'必修':'选修'),cell(q(c.credits)),flagCell(courseState(c,a),c.state==='passed'?'pass':c.state==='failed'?'risk':'quiet'))).join(''));
    return a.categories.map(cat=>{
      const all=a.courses.filter(c=>c.category===cat.name&&c.appliesToLanguage);
      const visible=all.filter(c=>(!filter||c.state!=='passed')&&(!search||(c.code+' '+c.name).toLowerCase().includes(search)));
      if((search||filter)&&!visible.length)return '';
      const names=[...new Set(visible.map(c=>c.submodule))];
      const sub=names.map(n=>{const items=visible.filter(c=>c.submodule===n), s=cat.subcategories?.find(x=>x.name===n);
        return `<details class="child-branch" ${search?'open':''}><summary><span>${safe(n)}</span><small>${s?'计入 '+q(s.credited)+' / '+q(s.required)+' 学分':items.length+' 门'}</small></summary>${courseTbl(items)}</details>`;}).join('');
      return `<details class="course-branch" ${search?'open':''}><summary><span>${safe(cat.name)}</span><small>计入 <b>${q(cat.credited)}</b> / ${q(cat.required)} 学分</small></summary>${sub||note('当前目录没有匹配课程。')}</details>`;
    }).join('')||note('没有符合筛选条件的课程。');
  }
  async function credits(){
    const ticket=S.ticket,a=await request(uri('campus-audit'));if(ticket!==S.ticket)return '';CampusViews.audit=a;
    const t=a.report.totals;
    const bands=a.categories.map(c=>({...c,enrolled:a.courses.filter(k=>k.appliesToLanguage&&k.category===c.name&&k.enrolledNow&&k.state!=='passed').reduce((n,k)=>n+k.credits,0),
      status:c.remaining<=0?'学分已满足':a.quality.historyComplete?'修读中':'待核对'}));
    const current=c=>q(c.enrolled)+(a.quality.enrollmentComplete?'':'（已导入）');
    const categories=bands.map(c=>row(cell(c.name),cell(q(c.required)),cell(q(c.earned)),cell(q(c.credited)),cell(q(c.remaining)),cell(current(c)),flagCell(c.status,c.remaining<=0?'pass':'quiet'))).join('');
    const smallSummary=`<div class="mobile-credit-summary"><div class="mobile-credit-labels" aria-hidden="true"><span>课程类别</span><span>计入学分</span><span>剩余学分</span></div>${bands.map(c=>`<details><summary aria-label="${safe(c.name)}，已计入 ${q(c.credited)} 学分，还需 ${q(c.remaining)} 学分，展开其余字段"><span>${safe(c.name)}</span><b>${q(c.credited)}</b><b>${q(c.remaining)}</b></summary><div>要求 ${q(c.required)}　已获 ${q(c.earned)}　在读 ${current(c)} 学分<br>核对结果：${safe(c.status)}</div></details>`).join('')}</div>`;
    return title('学分核对明细',link('riskcheck','检查下学期选课风险',true))+
      `<div class="business-meta"><strong>${safe(a.student.majorName)}</strong><span>${safe(a.student.cohort)} 级</span><span>${safe(a.pathAudit?.name||'个人培养路径')}</span>${button('path','查看修读路径')}</div>`+
      `<p class="school-reference"><a href="${CampusRoutes.schoolHome}" target="_blank" rel="noopener noreferrer">打开郑大教务平台 ↗</a><span>学生全部服务 › 培养方案 › 培养方案完成情况</span></p>`+
      metrics([['毕业要求',t.required,'当前专业培养方案'],['已计入要求',t.credited,'按课程类别与子类核算'],['还需完成',t.remaining,a.quality.historyComplete?'按各类缺口合计':'根据现有记录估算']])+
      (a.notes||[]).map(note).join('')+`<div class="section-line">${groupTitle('分类学分汇总')}${button('reconcile','查看学分差异')}</div>`+
      `<div class="wide-credit-summary">${table(['课程类别','要求学分','已获学分','计入学分','剩余学分','在读学分','核对结果'],categories)}</div>`+smallSummary+
      `<div class="section-line">${groupTitle('课程修读明细')}<div class="tree-actions"><button id="expand-tree">展开全部</button><span> / </span><button id="collapse-tree">收起全部</button></div></div>
      <div class="business-filter"><label>课程查询 <input id="campus-course-search" type="search" placeholder="课程名称或代码"></label><label><input type="checkbox" id="unmet-only"> 仅看未完成课程</label></div>
      <div id="course-tree">${tree(a)}</div>`+
      `<details class="special-checks"><summary>查看专项培养要求</summary>${table(['核对项目','要求值','当前值','结果','方案出处'],checks(a))}</details>`+
      note('课程目录含选修备选项；未修的选修课不一定是毕业缺口。在读学分未计入已获学分。');
  }
  async function reconcile(){
    const ticket=S.ticket,a=await request(uri('campus-audit')), r=a.report,t=r.totals;if(ticket!==S.ticket)return '';const totalDiff=Math.round((t.recordedPassed-t.credited)*100)/100;
    CampusViews.report=r;
    const detail=[...r.excluded.map(c=>row(cell(c.name+' · '+c.code),cell(c.reason),cell(q(c.credits)),cell('核对课程目录或外语路线'))),
      ...r.categoryDifferences.map(c=>row(cell(c.name),cell('类别或子类计入上限、课程分类'),cell(q(c.difference)),cell('本类已获 '+q(c.earned)+'，计入 '+q(c.credited))))].join('');
    if(window.IndependentUI)return IndependentUI.reconciliation(r,detail);
    return title('学分差异核对',link('credits','返回学分核对明细'))+
      metrics([['成绩记录已通过',t.recordedPassed,'同一门课通过多次只计一次'],['符合当前路线',t.routeEarned,'按专业目录与外语路线筛选'],['已计入分类要求',t.credited,'按培养方案分类计算']])+
      `<div class="reconcile-result"><strong>${totalDiff?'有 '+q(totalDiff)+' 学分未计入当前分类要求':'三项学分目前一致'}</strong><span>${r.historyComplete?'基于当前修读记录':'历史记录尚未确认完整'}。差异不等于挂科，也不代表已获学校认定。</span></div>`+
      groupTitle('差异明细')+(detail?table(['课程或类别','差异原因','学分差额','核对方向'],detail):note('未发现路线排除或分类计入差额。'))+
      groupTitle('外语路线试算')+`<div class="business-filter"><label>试算路线 <select id="language-trial"><option value="">选择另一条外语路线</option>${(r.languageTrials||[]).filter(l=>l.id!==r.currentLanguage).map(l=>`<option value="${safe(l.id)}">${safe(l.name)}</option>`).join('')}</select></label><span>仅试算，不保存修读选择。</span></div><div id="trial-result" aria-live="polite"></div>`+
      groupTitle('待确认的模块归属')+((r.pendingAllocation||[]).length?table(['课程名称','学分','状态'],r.pendingAllocation.map(c=>row(cell(c.name),cell(q(c.credits)),cell('有多个可归属模块，请在修读路径中核对'))).join('')):note('当前没有待分配的共享课程。'))+
      note('模块归属单独核对，不重复加到上面的差额。替代或认定课程以学院审核为准。')+
      `<div class="business-actions">${link('path','核对个人修读路径')}<button class="campus-button is-primary" data-action="ask" data-question="请解释我的学分差异，哪些已通过的学分未计入？">让知学解释当前学分</button></div>`;
  }
  function gradeList(d,term='',mode='all'){
    const results=d.items.filter(r=>(!term||r.term===term)&&(mode==='all'||(mode==='pending'?r.score==null:r.score!=null&&r.score<60)));
    if(!results.length)return note('该条件下没有成绩记录。');
    return [...new Set(results.map(r=>r.term))].map(s=>groupTitle(s+' 学期')+table(['课程名称','学分','绩点','成绩','状态'],results.filter(r=>r.term===s).map(r=>row(
      `<td><strong>${safe(r.name)}</strong><small class="table-sub">${safe(r.code)}　${safe(r.category)}</small></td>`,
      cell(q(r.credits)),`<td>${r.gradePoint==null?'—':number(r.gradePoint,1)}${r.gpaScope==='excluded'?'<small class="table-sub">任选 · 不计平均</small>':r.gpaScope==='unconfirmed'?'<small class="table-sub">统计范围待核对</small>':''}</td>`,
      cell(r.score??'—'),flagCell(r.score==null?'待出分':r.score<60?'未通过':'已通过',r.score==null?'quiet':r.score<60?'risk':'pass'))).join(''))).join('');
  }
  async function grades(){
    const ticket=S.ticket,d=await request(uri('transcript'));if(ticket!==S.ticket)return '';CampusViews.transcript=d;if(window.IndependentUI)return IndependentUI.grades(d,gradeList);return title('我的成绩',link('credits','查看学分核对明细'))+
      `<div class="business-filter"><label>学年学期 <select id="grade-term"><option value="">全部学期</option>${[...new Set(d.items.map(r=>r.term))].map(t=>`<option>${safe(t)}</option>`).join('')}</select></label><label>成绩状态 <select id="grade-state"><option value="all">全部记录</option><option value="pending">待出分</option><option value="failed">未通过</option></select></label></div>`+
      note(d.note)+`<details class="sheet-detail"><summary>绩点换算依据</summary>${note(d.gpaMethod)}
      <p class="business-note">${d.gpaBands.map(([low,points],i,all)=>`${low===0?'低于 60':low+'–'+(i?all[i-1][0]-1:100)} 分：${Number(points).toFixed(1)}`).join('　')}</p>
      <p class="business-note"><a href="${safe(d.gpaSource)}" target="_blank" rel="noopener noreferrer">校规第十二条 ↗</a></p></details><div id="grade-list">${gradeList(d)}</div>`;
  }
  async function path(){
    const a=await request(uri('curriculum-audit'));S.ws.audit=a;return title('个人修读路径',link('credits','查看学分核对明细'))+preferencesForm(a)+groupTitle('已选进阶模块')+
      ((a.moduleAudits||[]).filter(m=>m.selected).map(auditModule).join('')||note('尚未选择进阶模块。'))+groupTitle('路径专项要求')+auditCheckList(a.pathAudit?.checks);
  }
  async function myalerts(){
    const d=await request('/api/alerts');S.alerts=d.items||[];
    return title('我的学业预警',link('riskcheck','检查下学期选课风险',true)+link('plan','我的行动计划'))+
      (S.alerts.length?table(['预警事项','预警等级','信号状态','帮扶进展','负责辅导员','操作'],S.alerts.map(a=>row(
        `<td><strong>${safe(a.title)}</strong><small class="table-sub">${safe(a.kindName)}</small></td>`,`<td>${badge(a.level,a.levelName)}</td>`,cell(a.signalStateName),cell(a.statusName),cell(a.ownerName),
        `<td><button class="campus-link" data-action="alert" data-id="${safe(a.id)}">查看依据与反馈</button></td>`)).join('')):
        `<div class="campus-empty">${ico('ledger')}<strong>无预警记录</strong><p>可在学分核对明细中查看当前修读记录。</p>${button('credits','查看学分核对明细')}</div>`);
  }
  document.addEventListener('input',e=>{if(['campus-course-search','unmet-only'].includes(e.target.id)&&CampusViews.audit){$('#course-tree').innerHTML=tree(CampusViews.audit);}});
  document.addEventListener('change',e=>{if(['grade-term','grade-state'].includes(e.target.id))$('#grade-list').innerHTML=gradeList(CampusViews.transcript,$('#grade-term').value,$('#grade-state').value);});
  document.addEventListener('change',e=>{if(e.target.id!=='language-trial')return;const r=CampusViews.report,l=r?.languageTrials?.find(x=>x.id===e.target.value);
    $('#trial-result').innerHTML=!l?'':`<div class="reconcile-result"><strong>${safe(l.name)}路线：预计计入 ${q(l.credited)} 学分${l.delta?'，比当前'+(l.delta>0?'多':'少')+q(Math.abs(l.delta))+' 学分':'，与当前相同'}</strong><span>其余条件不变，预计还需 ${q(l.remaining)} 学分。${r.historyComplete?'':'历史记录尚未确认完整。'}</span></div>`+
      (l.changedCourses.length?table(['课程名称','课程代码','学分','试算变化'],l.changedCourses.map(c=>row(cell(c.name),cell(c.code),cell(q(c.credits)),cell(c.enters?'进入该路线':'不属于该路线'))).join('')):note('两条路线中没有已通过课程改变归属。'))+
      `<button class="campus-link" data-action="ask" data-question="请试算改成${safe(l.name)}路线后的学分差异，并解释哪些课程改变归属。">让知学解释这次试算 ›</button>`;});
  document.addEventListener('click',e=>{const id=e.target.id;if(['expand-tree','collapse-tree'].includes(id))for(const d of $$('#course-tree details'))d.open=id==='expand-tree';});
  return {credits,reconcile,grades,path,myalerts,ui:{q,link,title,note,table,cell,row,flag,groupTitle}};
})();
