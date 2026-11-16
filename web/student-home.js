'use strict';

const StudentHome = (() => {
  const quantity = value => value == null ? '—' : Number(value).toLocaleString('zh-CN', {maximumFractionDigits: 1});
  const nav = (page,label,style='hs-text-link') =>
    `<button type="button" class="${style}" data-page="${page}">${html(label)}${ico('next')}</button>`;
  const panelHead = (title,action='') =>
    `<div class="hs-panel-head"><h2>${html(title)}</h2>${action}</div>`;
  const alertButton = (alert,label,follow=false,style='hs-text-link') =>
    `<button type="button" class="${style}" data-action="alert" data-id="${html(alert.id)}"${follow?' data-ix-follow="true"':''}>${html(label)}${ico('next')}</button>`;
  const activeAlerts = profile => (profile.alerts||[]).filter(a=>a.active)
    .sort((a,b)=>b.level-a.level||String(b.updatedAt).localeCompare(String(a.updatedAt)));
  const incomplete = profile => Boolean(profile.metrics.dataQuality?.historyNeedsVerification||
    profile.metrics.dataQuality?.historyComplete===false||profile.metrics.dataQuality?.enrollmentComplete===false);
  const modeLabel = () => S.status.ai?.configured&&S.status.ai.mode==='remote'?'大模型已接入':'本地学情工作流';

  function assistantAction(profile,alert) {
    return alert?PlanEvidence.help({...alert,studentId:profile.student.id},'hs-assistant-action'):
      `<button type="button" class="hs-assistant-action" data-action="ask" data-student="${html(profile.student.id)}" data-question="请结合我的学情和培养要求，核对当前风险并建议下一步学习安排。">${ico('assistant')}分析学情与下一步${ico('next')}</button>`;
  }

  function warnings(profile) {
    const alerts=activeAlerts(profile),lead=alerts[0];
    const unconfirmed=(profile.alerts||[]).filter(a=>a.signalState==='unconfirmed').length;
    const counts=[1,2,3].filter(level=>alerts.some(a=>a.level===level)).map(level=>
      `<span class="hs-level-count level${level}">${['','轻度','一般','危急'][level]} ${alerts.filter(a=>a.level===level).length} 条</span>`).join('');
    const head=panelHead('当前学业预警',nav('myalerts',alerts.length?`全部 ${alerts.length} 条`:'预警记录'));
    let body;
    if(lead) {
      const evidence=lead.evidence?.[0];
      body=`<div class="hs-risk-lead"><div class="hs-risk-title">${badge(lead.level,lead.levelName)}<h3>${html(lead.title)}</h3></div>
        <p class="hs-risk-evidence">${html(CampusPortrait.shortEvidence(lead))}</p>
        ${evidence?.rule?`<p class="hs-risk-rule"><span>触发规则</span>${html(evidence.rule)}</p>`:''}
        ${evidence?.source?`<p class="hs-risk-source"><span>数据依据</span>${html(evidence.source)}</p>`:''}
        ${lead.suggestions?.[0]?`<p class="hs-risk-advice">${ico('next')}${html(lead.suggestions[0])}</p>`:''}
        <div class="hs-risk-links">${alertButton(lead,'查看完整依据',false,'hs-button')}<small>按项目规则分级 · ${html(date(lead.updatedAt))}更新</small></div></div>`;
      const rest=alerts.slice(1,3).map(a=>`<div class="hs-other-risk"><div>${badge(a.level,a.levelName)}<strong>${html(a.title)}</strong><p>${html(CampusPortrait.shortEvidence(a))}</p></div>${alertButton(a,'查看依据')}</div>`).join('');
      if(rest)body+=`<div class="hs-other-risks">${rest}</div>`;
    } else {
      const pending=incomplete(profile)||unconfirmed>0;
      body=`<div class="hs-risk-empty">${ico(pending?'file':'check')}<div><h3>${pending?'先确认数据，再核对学业风险':'当前记录未触发预警'}</h3>
        <p>${pending?'成绩或选课覆盖仍需确认，暂不能据此判断整体风险。':'继续核对培养要求和下学期安排，提前发现遗漏与冲突。'}</p>
        ${nav(pending?'credits':'riskcheck',pending?'核对已有记录':'检查下学期风险')}</div></div>`;
    }
    return `<section class="hs-panel hs-alerts" aria-label="当前学业预警">${head}
      ${alerts.length>1?`<div class="hs-risk-counts" aria-label="预警等级分布">${counts}</div>`:''}
      ${incomplete(profile)&&lead?'<p class="hs-data-warning">数据覆盖待确认：以下预警仅依据已导入的记录。</p>':''}
      ${unconfirmed?`<p class="hs-data-warning">另有 ${unconfirmed} 条历史预警因数据覆盖待核对而暂停判断，跟进记录仍保留。</p>`:''}
      ${body}<div class="hs-risk-assistant">${assistantAction(profile,lead)}<span>${modeLabel()}</span></div></section>`;
  }

  function nextTerm(profile,risk) {
    const head=panelHead('下学期选课风险',nav('riskcheck','完整检查'));
    if(!risk)return `<section class="hs-panel hs-next-term">${head}<div class="hs-unavailable"><p>选课风险暂未载入，当前学业预警仍可查看。</p>${nav('mine','重新载入')}</div></section>`;
    const c=risk.credits,j=risk.junior;
    const verified=risk.coverage.historyComplete&&risk.coverage.enrollmentComplete;
    const mode={demo:'模拟开课与课表',mixed:'导入与模拟开课混合',configured:'已导入开课记录',unavailable:'暂无目标学期开课记录'}[risk.dataMode]||'开课来源待核对';
    const future=j.ifPassedAverage==null?(j.remainingTerms===0?'培养期末':j.enabled?'待核对':'大三起评估'):quantity(j.ifPassedAverage);
    const rows=risk.priority.slice(0,3).map(c=>`<li><div class="hs-course-record"><strong>${html(c.name)}</strong>
      <p><span>${html(c.reason)}</span><span>${html(c.category)} · ${quantity(c.credits)} 学分</span>${c.score==null?'':`<span>成绩 ${quantity(c.score)} 分</span>`}</p></div>
      <div class="hs-record-actions"><button type="button" class="hs-text-link" data-home-course="${html(c.code)}" aria-label="查看${html(c.name)}的修读记录">记录</button>
      <button type="button" class="hs-text-link hs-compare-link" data-home-risk-course="${html(c.id)}" aria-label="比较${html(c.name)}选与暂不选">比较安排${ico('next')}</button></div></li>`).join('');
    const planNote=risk.plan.kind==='saved'?`已保存第 ${risk.plan.version} 版方案 · ${(planStatus[risk.plan.status]||risk.plan.status||'草稿')}`:'尚未保存个人方案';
    return `<section class="hs-panel hs-next-term" aria-label="下学期选课风险">${head}
      <div class="hs-risk-meta"><span>${html(risk.term)} 学期</span><span>${html(mode)}</span></div>
      ${verified?'':'<p class="hs-data-warning">成绩或选课覆盖待核对，以下为已导入记录的条件试算。</p>'}
      <dl class="hs-projection">
        <div><dt>当前分类缺口${verified?'':'（待核对）'}</dt><dd>${quantity(c.remaining)}<small> 学分</small></dd></div>
        <div><dt>在读通过后预计缺口</dt><dd>${quantity(c.ifPassedRemaining)}<small> 学分</small></dd></div>
        <div><dt>后续每学期平均需修</dt><dd class="${j.ifPassedAverage==null?'is-pending':''}">${future}${j.ifPassedAverage==null?'':'<small> 学分</small>'}</dd></div>
      </dl>
      <p class="hs-assumption">假设本学期符合路径的 ${quantity(c.studying)} 学分全部通过，再按类别重算。${j.ifPassedAverage==null?'':`后续均值按剩余 ${j.remainingTerms} 个常规学期计算。`}</p>
      <div class="hs-priority-heading"><h3>优先核对的课程</h3><span>${risk.priority.length} 门</span></div>
      ${rows?`<ul class="hs-course-records">${rows}</ul>`:'<p class="hs-empty-copy">当前记录没有列入优先核对清单的课程，可继续核对下学期建议课程。</p>'}
      ${risk.priority.length>3?nav('riskcheck',`查看其余 ${risk.priority.length-3} 门及建议课程`):''}
      <div class="hs-plan-entry"><span>${html(planNote)}</span><button type="button" class="hs-button" data-action="open-planner" data-term="${html(risk.term)}" data-student="${html(profile.student.id)}">${risk.plan.kind==='saved'?'查看下学期方案':'制定下学期方案'}${ico('next')}</button></div></section>`;
  }

  function followup(profile,alert,detail) {
    const head=panelHead('辅导员跟进',alert?alertButton(alert,'记录与反馈',true):'');
    if(!alert)return `<section class="hs-panel hs-follow">${head}<p class="hs-follow-owner">负责辅导员 <strong>${html(profile.student.counselorName||'待分配')}</strong></p>
      <p class="hs-empty-copy">当前没有预警处置记录。出现预警后，可在这里查看负责老师和跟进进度。</p></section>`;
    const stages=[['new','待联系'],['contacted','已联系'],['supporting','帮扶中'],['review','待复查'],['closed','已结案']];
    const current=alert.status;
    const stageHtml=stages.map(([key,label])=>`<li class="${key===current?'is-current':''}"${key===current?' aria-current="step"':''}><i aria-hidden="true"></i><span>${label}</span></li>`).join('');
    const recent=detail?.events?.at(-1);
    const today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
    const due=alert.nextReview&&alert.nextReview<=today&&current!=='closed';
    const record=!detail?`<div class="hs-unavailable"><p>跟进明细暂未载入。</p>${nav('mine','重新载入')}</div>`:
      recent?`<div class="hs-recent-event"><span>最近记录</span><p class="hs-event-meta">${html(recent.actor)} · ${html(recent.action)} · ${html(date(recent.createdAt))}</p>
        <p class="hs-event-note">${html(recent.plan||recent.note||'已记录本次处理进展。')}</p></div>`:'<p class="hs-empty-copy">暂未记录具体帮扶措施，可在记录与反馈中查看后续更新。</p>';
    return `<section class="hs-panel hs-follow" aria-label="辅导员跟进">${head}
      <p class="hs-follow-context">对应预警：${html(alert.title)}</p>
      <p class="hs-follow-owner">负责辅导员 <strong>${html(alert.ownerName)}</strong></p>
      <ol class="hs-case-stages" aria-label="处置阶段，当前${html(alert.statusName)}">${stageHtml}</ol>
      ${!alert.active?`<p class="hs-follow-condition">${html(alert.signalStateName)} · 处置状态以跟进记录为准</p>`:''}
      ${record}<div class="hs-review-date ${due?'is-due':''}">${ico('ledger')}<span>${alert.nextReview?`约定复查 ${html(alert.nextReview)}${due?' · 日期已到':''}`:'复查日期尚未约定'}</span></div>
      ${alertButton(alert,'反馈我的学习进展',true,'hs-button hs-full-button')}</section>`;
  }

  function credits(profile) {
    const c=profile.credits,credited=c.credited??c.earned;
    const ratio=c.total>0?Math.max(0,Math.min(100,credited/c.total*100)):0;
    const modules=(c.categories||[]).map(item=>{
      const earned=item.credited??item.earned;
      const percentage=item.required>0?Math.max(0,Math.min(100,earned/item.required*100)):0;
      return `<div class="hs-credit-category"><div><span>${html(item.name)}</span><span><b>${quantity(earned)}</b> / ${quantity(item.required)}</span></div>
        <div class="hs-progress" aria-hidden="true"><i style="width:${percentage}%"></i></div></div>`;
    }).join('');
    return `<section class="hs-panel hs-credit">${panelHead('培养方案学分',nav('credits','详细核对'))}
      <div class="hs-credit-number"><strong>${quantity(credited)}</strong><span>/ ${quantity(c.total)} 学分</span></div>
      <div class="hs-credit-caption"><span>已计入培养要求</span><b>${c.total>0?quantity(ratio)+'%':'待核对'}</b></div>
      <div class="hs-progress hs-progress-total" aria-hidden="true"><i style="width:${ratio}%"></i></div>
      <div class="hs-credit-modules">${modules}</div>
      <p class="hs-footnote">${profile.metrics.dataQuality?.historyNeedsVerification?'按已导入记录核算，历史成绩覆盖待确认。':'各类别分别核算，超修学分不能直接抵扣其他类别缺口。'}</p></section>`;
  }

  function trend(profile) {
    const points=(profile.trend||[]).map(({term,gpa})=>({term,gpa})).sort((a,b)=>a.term.localeCompare(b.term));
    const text=points.map(t=>t.term+' 学期 '+(t.gpa==null?'暂无可计算绩点':number(t.gpa,2))).join('，');
    const note=profile.metrics.gpaPendingCourses?`${profile.metrics.gpaPendingCourses} 门课程的绩点待核对`:'按已确认计入的课程学分加权';
    const chart=points.some(p=>p.gpa!=null)?
      `<campus-gpa-chart role="img" aria-label="学期平均绩点走势" aria-describedby="hs-trend-values" data-points="${html(JSON.stringify(points))}"></campus-gpa-chart>
        <span class="a11y-only" id="hs-trend-values">${html(text)}</span>`:
      '<div class="hs-chart-empty">成绩公布后，可以在这里查看学期变化。</div>';
    return `<section class="hs-panel hs-trend">${panelHead('成绩与修读',nav('grades','成绩明细'))}
      <div class="hs-portrait-facts"><div class="hs-gpa"><strong>${html(profileGpaText(profile))}</strong><div><span>累计绩点</span><small>${html(note)}</small></div></div>
        <div class="hs-study-load"><span><span>本学期</span><span>已记录选课</span></span><strong>${quantity(profile.metrics.selectedCredits)}<small> 学分</small></strong></div></div>
      ${chart}<p class="hs-chart-caption">学期平均绩点 · 满分 4.0</p></section>`;
  }

  function actions(plan) {
    if(!plan)return `<section class="hs-panel hs-actions">${panelHead('我的学习行动')}<div class="hs-unavailable"><p>行动清单暂未载入。</p>${nav('mine','重新载入')}</div></section>`;
    const tasks=plan.tasks||[],items=tasks.filter(t=>!t.completed),completed=tasks.length-items.length;
    const rows=items.slice(0,3).map(task=>`<article class="hs-task">
      <button type="button" class="hs-task-check" data-action="task-toggle" data-id="${html(task.id)}" data-complete="true" aria-label="标记完成：${html(task.title)}">${ico('check')}</button>
      <div><strong>${html(task.title)}</strong><small>${task.dueDate?html(date(task.dueDate))+' 前完成':html(taskSources[task.source]||'学习行动')}${task.assignedName?' · '+html(task.assignedName)+'安排':''}</small></div></article>`).join('');
    const content=rows||`<div class="hs-action-empty"><span>${ico('check')}</span><div><strong>${completed?'当前行动已完成':'把下一步落实到行动'}</strong>
      <p>可先请知学结合预警拟定草案，核对后采纳。</p></div></div>`;
    return `<section class="hs-panel hs-actions">${panelHead('我的学习行动',`<span class="hs-count">${items.length} 项待完成</span>`)}
      ${content}${nav('plan',items.length?'查看行动清单':'添加学习行动','hs-button hs-full-button')}
      <p class="hs-action-hint">完成后可向辅导员反馈，由老师继续复查。</p></section>`;
  }

  async function view() {
    const ticket=S.ticket,id=S.user.id;
    const results=await Promise.allSettled([request(apiStudent(id)),request('/api/my/plan'),request(apiStudent(id)+'/selection-risk')]);
    if(ticket!==S.ticket)return '';
    if(results[0].status!=='fulfilled')throw results[0].reason;
    const profile=results[0].value,plan=results[1].status==='fulfilled'?results[1].value:null,risk=results[2].status==='fulfilled'?results[2].value:null;
    S.profile=profile;
    const alerts=activeAlerts(profile),cases=[...(profile.alerts||[])].sort((a,b)=>
      Number(a.status==='closed')-Number(b.status==='closed')||String(b.updatedAt).localeCompare(String(a.updatedAt)));
    const relevant=alerts[0]||cases[0];
    let detail=null;
    if(relevant) {
      try { detail=await request('/api/alerts/'+encodeURIComponent(relevant.id)); }
      catch { /* The risk and action sections remain available if this optional request fails. */ }
    }
    if(ticket!==S.ticket)return '';
    const notes=(profile.metrics?.dataNotes||[]).map(note=>`<p>${html(note)}</p>`).join('');
    return `<div class="hs-home">
      <header class="hs-heading"><div><h1>我的学情</h1><p>${html(profile.student.name)}<span>·</span>${html(profile.student.majorName)}<span>·</span>第 ${quantity(profile.credits.semester)} 学期</p></div>
        <div class="hs-heading-actions"><span>${html(S.status.term||'')} 学期</span>${nav('riskcheck','检查下学期风险','hs-button hs-primary')}</div></header>
      <div class="hs-board">${warnings(profile)}${nextTerm(profile,risk)}
        <aside class="hs-support" aria-label="师生跟进与行动">${followup(profile,relevant,detail)}${actions(plan)}</aside>
        <section class="hs-portrait" aria-label="多维学情画像"><div class="hs-portrait-heading"><h2>学情画像</h2><span>成绩、修课与培养方案核对</span></div>
          <div class="hs-portrait-grid">${trend(profile)}${credits(profile)}</div></section>
      </div>
      ${notes?`<details class="hs-data-notes"><summary>数据说明与核算口径</summary>${notes}</details>`:''}
    </div>`;
  }

  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-home-course],[data-home-risk-course]');
    if(!button||button.disabled)return;
    button.disabled=true;
    try {
      if(button.hasAttribute('data-home-risk-course'))await CampusRisk.openCourse(button.dataset.homeRiskCourse,S.user.id);
      else await IndependentUI.openCourseRecords(button.dataset.homeCourse,button.dataset.homeState||'');
    } catch(error) { toast(error.message); }
    finally { if(button.isConnected)button.disabled=false; }
  });
  return {view};
})();
