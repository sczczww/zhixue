'use strict';
const CampusRisk = (() => {
  const {q,link,title,note,table,cell,row,groupTitle}=CampusViews.ui;
  const modeNames={demo:'模拟开课与课表',mixed:'导入与模拟开课混合',configured:'已导入开课数据',unavailable:'目标学期暂无开课数据'};
  let selectedStudent=null, report=null, lastChoice=null, compareRun=0;

  function reset(){selectedStudent=null;report=null;lastChoice=null;compareRun++;}
  function entryButton(studentId,label='检查下学期选课风险') {
    return `<button class="btn" type="button" data-risk-for="${html(studentId)}">${ico('analytics')}${html(label)}</button>`;
  }
  function plannerButton(data) {
    return `<button class="campus-button is-primary" data-action="open-planner" data-term="${html(data.term)}"
      data-student="${html(data.student.id)}">打开下学期方案</button>`;
  }
  function rosterSelect(rows,id) {
    return `<div class="business-filter"><label>所负责的学生 <select id="risk-student"><option value="">选择学生</option>
      ${rows.map(s=>`<option value="${html(s.id)}" ${s.id===id?'selected':''}>${html(s.name)} · ${html(s.id)}</option>`).join('')}</select></label></div>`;
  }
  function alertRows(data) {
    const profile=S.user.role==='student'?link('mine','我的学情画像'):
      `<button class="campus-button" data-action="profile" data-id="${html(data.student.id)}">查看学生画像</button>`;
    const rows=data.alerts.map(a=>`<div class="risk-alert-row">${badge(a.level,a.levelName)}<strong>${html(a.title)}</strong>
        <span>${html(a.ownerName)} · ${html(a.statusName)}</span>
        <button class="campus-link" data-action="alert" data-id="${html(a.id)}">${S.user.role==='student'?'查看依据与反馈':'查看依据与跟进'}</button></div>`);
    return `<section><div class="section-line">${groupTitle('已触发的学业预警')}${profile}</div>
      ${rows.join('')||note('当前记录中没有已触发的项目预警。')}</section>`;
  }
  function courseRows(rows) {
    return table(['课程名称','检查依据','下学期开课','操作'],rows.map(c=>{
      const offer=c.offering;
      const schedule=!offer?'暂无开课记录':!offer.available?'记录为暂不开课':offer.scheduleText;
      const details=offer&&offer.available?`<small class="table-sub">余量 ${q(offer.seats)}${offer.isDemo?' · 模拟开课':''}</small>`:'';
      return row(
        `<td><strong>${html(c.name)}</strong><small class="table-sub">${html(c.code)} · ${c.required?'必修/限选':'选修'} · ${q(c.credits)} 学分</small></td>`,
        `<td>${html(c.reason)}<small class="table-sub">${html(c.action)}</small></td>`,
        `<td>${html(schedule)}${details}</td>`,
        `<td><button class="campus-link" data-check-course="${html(c.id)}">比较选与暂不选</button></td>`);
    }).join(''));
  }
  function studyFacts(data) {
    const credits=data.credits;
    const categories=credits.categories.map(c=>row(cell(c.name),cell(q(c.required)),cell(q(c.credited)),cell(q(c.studying)),cell(q(c.remaining)),cell(q(c.ifPassedRemaining)))).join('');
    const studying=data.studying.map(c=>row(cell(c.name),cell(q(c.credits)),cell(c.inRoute?c.category:'路线归属待核对'),cell('在读 · 待出分'))).join('');
    const recognition=data.recognition.courses.map(c=>row(cell(c.name),cell(q(c.credits)),cell(c.state),cell(c.reason))).join('');
    const junior=data.junior;
    let guidance='';
    if(junior.ifPassedAverage!=null)guidance=note(`大三及以后规划：若本学期在读均通过，余下 ${junior.remainingTerms} 个常规学期平均需修 ${q(junior.ifPassedAverage)} 学分。`);
    else if(junior.remainingTerms===0)guidance=note('已到常规培养期末，请向学院核对后续修读时间。');
    return `<section><div class="section-line">${groupTitle('学分与认定依据')}${S.user.role==='student'?link('credits','学分核对明细'):''}</div>
      ${guidance}
      <details class="risk-details"><summary>分模块学分与在读课程（${data.studying.length} 门）</summary>
        ${table(['类别','要求学分','已计入','在读学分','当前缺口','在读通过后缺口'],categories)}
        ${studying?table(['课程名称','学分','归属','状态'],studying):note('本次未读到在读课程记录。')}</details>
      <details class="risk-details"><summary>课程归属与待认定事项${recognition?'（'+data.recognition.courses.length+' 门）':''}</summary>
        ${recognition?table(['课程名称','学分','修读记录','待核对原因'],recognition):note('当前记录没有列出需要核对归属的单门课程。')}
        ${data.recognition.pathNote?note(data.recognition.pathNote):''}
        ${note('课程替代、计划外课程归属和最终认定以教务审核结果为准。')}</details></section>`;
  }
  async function view() {
    const ticket=S.ticket;
    report=null;lastChoice=null;compareRun++;
    let selector='';
    let id=S.user.id;
    if(S.user.role!=='student') {
      const roster=await request('/api/students');
      if(ticket!==S.ticket)return '';
      id=roster.items.some(s=>s.id===selectedStudent)?selectedStudent:null;
      selector=rosterSelect(roster.items,id);
      if(!id&&window.IndependentUI)return IndependentUI.riskPicker(selector);
      if(!id)return title('学生选课风险检查')+selector+note('选择学生，查看其下学期修读安排、预警依据和帮扶进展。');
    }
    const data=await request(apiStudent(id)+'/selection-risk');
    if(ticket!==S.ticket)return '';
    report=data;
    const base=data.plan.kind==='saved'?'已保存方案':'参考组合';
    const quality=[];
    if(!data.coverage.historyComplete)quality.push('历史成绩覆盖待核对');
    if(!data.coverage.enrollmentComplete)quality.push('本学期选课覆盖待核对');
    const source=modeNames[data.dataMode];
    const compareNote=`按${base}（${data.plan.courseIds.length} 门）比较单门课程。其余课程相同，分别核对两种安排的学分和冲突。`;
    if(window.IndependentUI)return IndependentUI.risk(data,{selector,source,quality,compareNote,courseRows,alertRows,studyFacts});
    return title('下学期选课风险检查',plannerButton(data))+selector+
      `<div class="business-meta"><strong>${html(data.student.name)} · ${html(data.student.majorName)}</strong>
        <span>当前第 ${data.semester} 学期</span><span>检查学期 ${html(data.term)}</span><span>${html(source)}</span></div>`+
      (quality.length?`<p class="risk-review-note">${html(quality.join('，'))}。以下仅按已导入记录试算，缺记录的课程须先核实。</p>`:'')+
      alertRows(data)+
      `<p class="risk-credit-sentence">当前分类缺口 <b>${q(data.credits.remaining)}</b> 学分。本学期符合路线的在读课程共 <b>${q(data.credits.studying)}</b> 学分。若在读课程均通过，按类别重新核算，预计仍需 <b>${q(data.credits.ifPassedRemaining)}</b> 学分。</p>`+
      `<section><div class="section-line">${groupTitle('优先核对的课程')}
        <button class="campus-link" data-action="ask" data-student="${html(id)}" data-question="请解释这位学生的下学期选课风险，列出需要优先核实的课程和依据。">让知学解释检查结果</button></div>
        ${note(compareNote)}${data.priority.length?courseRows(data.priority):note('根据现有记录，没有列入优先核对清单的课程。')}
        <details class="risk-details"><summary>培养方案建议下学期修读的必修或限选课（${data.upcoming.length} 门）</summary>
        ${data.upcoming.length?courseRows(data.upcoming):note('当前目录没有匹配到该建议学期的课程。')}</details>
        <div id="risk-comparison" aria-live="polite" tabindex="-1"></div></section>`+
      studyFacts(data);
  }
  async function compare(id) {
    const data=report;
    if(!data)return;
    const course=[...data.priority,...data.upcoming].find(c=>c.id===id);
    if(!course)return;
    const destination=document.getElementById('risk-comparison');
    if(!destination)return;
    const run=++compareRun;
    lastChoice=null;
    destination.innerHTML=note('正在检查课程组合…');
    try {
      const choice=await request(apiStudent(data.student.id)+'/selection-risk/compare',{method:'POST',
        body:JSON.stringify({courseId:id})});
      if(run!==compareRun||data!==report||!destination.isConnected)return;
      lastChoice=choice;
      destination.innerHTML=comparisonView(data,choice);
    } catch(error) {
      if(run!==compareRun||!destination.isConnected)return;
      destination.innerHTML=note(error.message);
    }
    destination.focus();
  }

  async function openCourse(courseId,studentId=S.user.id) {
    selectedStudent=studentId;
    const loading=go('riskcheck'),ticket=S.ticket;
    await loading;
    if(ticket!==S.ticket||S.page!=='riskcheck'||report?.student.id!==studentId)return;
    if(![...report.priority,...report.upcoming].some(course=>course.id===courseId)) {
      toast('课程清单已更新，请从当前清单重新选择。');
      return;
    }
    await compare(courseId);
  }

  function comparisonView(data,choice) {
    const variants=[['with','选这门'],['without','暂不选']];
    const editable=S.user.role==='student'&&!['submitted','approved'].includes(choice.baseStatus);
    const canAssessMissing=data.coverage.historyComplete&&data.coverage.enrollmentComplete;
    const variantsHtml=variants.map(([key,label])=>{
      const option=choice[key];
      const issues=option.issues.map(i=>`<li>${html(i.message)}<small class="table-sub">${html(i.source)}</small></li>`).join('');
      return `<div class="choice-option"><h4>${label}</h4><div>选入 ${option.courseIds.length} 门 · 已纳入核算 ${q(option.credits)} 学分</div>
        <strong>${option.eligible?'预计分类缺口 '+q(option.remaining)+' 学分':'有约束待处理'}</strong>
        ${issues?`<ul>${issues}</ul>`:note('已知课表、先修和名额检查通过。')}
        ${canAssessMissing?note('到建议学期、仍待安排的必修或限选课 '+option.missingRequired+' 门。'):note('修读记录待核实。')}
        ${editable&&option.eligible?`<button class="campus-button" data-use-risk-choice="${key}">按“${label}”打开规划草稿</button>`:''}</div>`;
    }).join('');
    let difference='有约束的方案请先核对开课、先修或时段，再试算缺口。';
    if(choice.gain!==null)difference=choice.gain?`其他课程相同时，选这门预计可多补${choice.course.category}类 ${q(choice.gain)} 学分。`:
      '两种安排的分类缺口相同，仍需单独核对必修与模块要求。';
    return `<div class="risk-comparison"><h3>《${html(choice.course.name)}》选课比较</h3>
      <p>${choice.baseKind==='saved'?'以已保存方案为基础。':'以参考组合为基础。'}预计缺口按本学期在读课程及该方案课程全部通过试算。</p>
      <div class="choice-options">${variantsHtml}</div><p>${html(difference)}</p>
      <button class="campus-link" data-action="ask" data-student="${html(data.student.id)}"
        data-question="请对比下学期选课风险，解释课程代码 ${html(choice.course.code)} 选与暂不选的差异。">让知学解释这两种安排</button></div>`;
  }

  async function openChoice(key) {
    if(!report||!lastChoice||S.user.role!=='student'||!['with','without'].includes(key))return;
    const option=lastChoice[key];
    if(!option.eligible||['submitted','approved'].includes(lastChoice.baseStatus))return;
    const id=report.student.id,term=lastChoice.term,draftKey=id+'|'+term;
    if(S.ws.planDrafts[draftKey]?.dirty) {
      toast('已打开此前未保存的草稿。保存后可以再带入比较结果。');
    } else {
      const choice=lastChoice,context=report,ticket=S.ticket;
      const evidence=await request(apiStudent(id)+'/selection-risk/record',{method:'POST',
        body:JSON.stringify({courseId:choice.course.id,fingerprint:choice.fingerprint})});
      if(ticket!==S.ticket||context!==report||choice!==lastChoice)return;
      S.ws.planDrafts[draftKey]={dirty:true,courseIds:[...option.courseIds],
        expectedVersion:choice.baseVersion,comparison:{...evidence,choice:key}};
      toast('课程和比较依据已带入草稿，保存后可随方案提交。');
    }
    S.ws.planStudent=id;S.ws.planTerm=term;
    window.IndependentUI?.showDraftOnOpen();
    await go('planner');
  }
  document.addEventListener('click',event=>{
    const entry=event.target.closest('[data-risk-for]');
    if(entry){selectedStudent=entry.dataset.riskFor;go('riskcheck');return;}
    const check=event.target.closest('[data-check-course]');
    if(check)compare(check.dataset.checkCourse);
    const use=event.target.closest('[data-use-risk-choice]');
    if(use&&!use.disabled){
      use.disabled=true;
      openChoice(use.dataset.useRiskChoice).catch(error=>toast(error.message)).finally(()=>{
        if(use.isConnected)use.disabled=false;
      });
    }
  });
  document.addEventListener('change',event=>{
    if(event.target.id==='risk-student'){selectedStudent=event.target.value||null;go('riskcheck');}
  });
  return {view,reset,entryButton,openCourse};
})();
