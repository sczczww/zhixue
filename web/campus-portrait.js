'use strict';
const CampusPortrait=(()=>{
  const {q,title,link,note,table,cell,row,groupTitle}=CampusViews.ui;
  const num=(value,places=2)=>value==null?'—':number(value,places);
  const sub=text=>`<small class="table-sub">${html(text)}</small>`;
  const section=(label,action='')=>`<div class="section-line">${groupTitle(label)}${action}</div>`;
  const numberWithUnit=(value,unit)=>value==null?'—':q(value)+' '+unit;

  function metrics(p) {
    const c=p.credits, m=p.metrics;
    const values=[
      ['累计绩点',profileGpaText(p),p.metrics.gpaPendingCourses?'仅已确认计入的课程':'按计入课程的学分加权'],
      ['已获学分',numberWithUnit(c.earned,'学分'),'通过课程去重'],
      ['计入 / 要求学分',q(c.credited)+' / '+q(c.total),'按培养类别核算'],
      ['未通过课程',numberWithUnit(m.failedCourses,'门'),numberWithUnit(m.failedCredits,'学分')]
    ];
    return `<dl class="profile-facts">${values.map(([name,value,detail])=>
      `<div><dt>${html(name)}</dt><dd>${html(value)}</dd><dd class="fact-detail">${html(detail)}</dd></div>`).join('')}</dl>`;
  }

  function shortEvidence(alert) {
    const evidence=alert.evidence?.[0];
    if(!evidence)return '详见预警记录';
    let value=evidence.value;
    if(Array.isArray(value)) {
      if(value.every(x=>typeof x==='number'))value=value.map(q).join(' → ');
      else {
        const first=value.slice(0,2).join('、');
        const unit=evidence.label.includes('课程')?'门':'项';
        value=value.length>2?first+' 等 '+value.length+' '+unit:first;
      }
    } else if(typeof value==='number') {
      const unit=evidence.label.includes('学分')?' 学分':evidence.label==='尚未通过课程'?' 门':evidence.label.includes('均分')?' 分':'';
      value=q(value)+unit;
    }
    return evidence.label+(value==null?'':'：'+value);
  }

  function warningSummary(p,student) {
    const alerts=p.alerts.filter(a=>a.active);
    const manage=student?link('myalerts','全部预警'):'';
    const content=alerts.length?table(['预警事项','等级','帮扶进展','操作'],alerts.map(a=>row(
      `<td><strong>${html(a.title)}</strong>${sub(shortEvidence(a))}</td>`,
      `<td>${badge(a.level,a.levelName)}</td>`,
      `<td>${html(a.statusName)}${sub(a.ownerName+'负责')}</td>`,
      `<td><button type="button" class="campus-link" data-action="alert" data-id="${html(a.id)}">${student?'依据与反馈':'依据与跟进'}</button></td>`
    )).join(''),true):note('当前已导入记录没有触发知学预警。');
    return section('当前预警（'+alerts.length+' 条）',manage)+content;
  }

  function academicDetails(p,student) {
    const trend=[...(p.trend||[])].sort((a,b)=>a.term.localeCompare(b.term));
    const results=trend.length?table(['学期','加权均分','平均绩点'],[...trend].reverse().map(t=>
      row(cell(t.term),cell(num(t.score,1)),cell(num(t.gpa)))).join('')):note('暂无已发布的学期成绩。');
    const points=trend.map(t=>({term:t.term,gpa:t.gpa}));
    const chart=points.some(t=>t.gpa!=null)?`<details class="sheet-detail"><summary>查看学期绩点趋势图</summary>
      <campus-gpa-chart role="img" aria-label="学期平均绩点趋势，具体数值见学期成绩表" data-points="${html(JSON.stringify(points))}"></campus-gpa-chart></details>`:'';
    const categories=p.credits.categories||[];
    const creditTable=categories.length?table(['类别','要求','计入','剩余'],categories.map(c=>
      row(cell(c.name),cell(q(c.required)),cell(q(c.credited)),cell(q(c.remaining)))).join('')):note('暂无分类学分记录。');
    return `<div class="sheet-pair"><section class="sheet-compact">${section('学期成绩',student?link('grades','成绩明细'):'')}
      ${results}${chart}${p.metrics.currentGradesPending?note('本学期暂无已发布成绩。'):''}</section>
      <section class="sheet-compact">${section('分类学分',student?link('credits','学分核对明细'):'')}${creditTable}
      ${note(p.metrics.dataQuality.historyComplete?'各类别分别核算，单位为学分。':'当前缺口按已导入记录估算，历史成绩待核对。')}</section></div>`;
  }

  function actions(tasks,student,suggestion) {
    const pending=tasks.filter(t=>!t.completed);
    const completed=tasks.length-pending.length;
    const titleBar=section('学习行动',student?link('plan','我的行动计划'):'');
    if(!tasks.length)return titleBar+note('暂无学习行动记录。')+(suggestion?note(suggestion):'');
    const rows=items=>items.map(t=>row(
      `<td><strong>${html(t.title)}</strong>${t.assignedName?sub(t.assignedName+'安排'):''}</td>`,
      cell(t.dueDate||'未设置'),cell(t.completed?'已完成':'待完成'),
      ...(student?[t.completed?cell('—'):`<td><button type="button" class="campus-link" data-action="task-toggle" data-id="${html(t.id)}" data-complete="true">标记完成</button></td>`]:[])
    )).join('');
    const columns=student?['行动事项','计划完成日期','状态','操作']:['行动事项','计划完成日期','状态'];
    const first=pending.slice(0,3),rest=[...pending.slice(3),...tasks.filter(t=>t.completed)];
    return titleBar+note('待完成 '+pending.length+' 项，已完成 '+completed+' 项。')+
      (first.length?table(columns,rows(first),true):'')+
      (rest.length?`<details class="sheet-detail"><summary>其余行动记录（${rest.length} 项）</summary>${table(columns,rows(rest),true)}</details>`:'');
  }

  function advisorDetail(p) {
    const j=p.junior,quality=p.metrics.dataQuality;
    const juniors=j?.enabled?`<p class="business-note">${html(j.message)} 后续平均每学期需修 ${j.creditsPerTerm==null?'待核对':q(j.creditsPerTerm)+' 学分'}。</p>
      ${j.missingCourses?.length?note('需核实修读安排：'+j.missingCourses.join('、')):''}`:'';
    const checks=(p.credits.checks||[]).map(c=>row(cell(c.name),cell(q(c.target)),cell(q(c.value)),
      cell(c.met?'已达到':quality.historyComplete?'待完成':'待核对'))).join('');
    return `<details class="sheet-detail"><summary>分类、专项与后续修读要求</summary>
      ${creditBars(p.credits)}${checks?table(['专项要求','要求值','当前值','结果'],checks):''}${juniors}</details>
      <details class="sheet-detail"><summary>课程修读明细（${p.courses.length} 门）</summary>
      <div class="business-filter"><label>课程 <input type="search" id="profile-course-query" placeholder="名称或代码"></label>
      <label>修读状态 <select id="profile-course-filter"><option value="">全部</option><option value="failed">未通过</option><option value="enrolled">在读</option><option value="passed">已通过</option><option value="remaining">尚无通过记录</option></select></label></div>
      <div class="business-table-wrap"><table class="business-table"><thead><tr><th>课程名称</th><th>学分</th><th>成绩</th><th>修读状态</th></tr></thead><tbody id="profile-course-list"></tbody></table></div>
      <div id="course-pager" class="table-bottom"></div></details>`;
  }

  function body(p,tasks,student) {
    const s=p.student;
    const metadata=`<div class="business-meta sheet-identity"><strong>${html(s.name)}</strong><span>${html(s.id)}</span>
      <span>${html(s.className)} · ${html(s.majorName)}</span><span>辅导员 ${html(s.counselorName)}</span></div>`;
    const assistant=`<button type="button" class="campus-link" data-action="ask" data-student="${html(s.id)}"
      data-question="${student?'请结合我的学情和预警依据，给出下一步学习建议。':'请结合这位学生的学情和预警依据，给出下一步帮扶建议。'}">让知学解释画像</button>`;
    return `<div class="school-portrait">${metadata}<div class="sheet-assessment"><span>画像特征</span><b>${html(s.portrait||'待核对')}</b>${assistant}</div>
      ${metrics(p)}${(p.metrics.dataNotes||[]).map(note).join('')}${warningSummary(p,student)}
      ${academicDetails(p,student)}${actions(tasks,student,p.alerts.some(a=>a.active)?p.suggestions?.[0]:null)}${student?'':advisorDetail(p)}
      <details class="sheet-detail"><summary>数据与核算依据</summary>${(p.sources||[]).map(note).join('')}${note(p.metrics.gpaMethod||'绩点根据已发布的成绩换算。')}
      <p class="business-note"><a href="${html(p.metrics.gpaSource)}" target="_blank" rel="noopener noreferrer">校规第十二条 ↗</a></p></details></div>`;
  }
  async function mine() {
    const ticket=S.ticket, id=S.user.id;
    const [p,plan]=await Promise.all([request(apiStudent(id)),request('/api/my/plan')]);
    if(ticket!==S.ticket)return '';
    S.profile=p;
    return title('我的学情画像',link('riskcheck','检查下学期选课风险',true))+body(p,plan.tasks||[],true);
  }
  return {mine,staff:p=>body(p,p.studyTasks||[],false),shortEvidence};
})();
