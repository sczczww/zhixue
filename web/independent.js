'use strict';

// The independent entrance supplies layouts. The campus entrance and both sets of
// controls use the same signed-in user, records, mutations and planning checks.
window.IndependentUI = (() => {
  const studentMenu = [
    [['mine', '我的学情', 'overview'], ['myalerts', '我的预警', 'bell'], ['plan', '学习行动', 'check']],
    [['credits', '学分核对', 'ledger'], ['riskcheck', '选课风险检查', 'analytics'], ['planner', '学期选课规划', 'curriculum'], ['curriculum', '培养方案', 'file']],
    [['assistant', '知学助手', 'assistant']]
  ];
  const staffMenu = [
    [['overview', '工作概览', 'overview'], ['ledger', '帮扶台账', 'ledger'], ['students', '学生画像', 'students']],
    [['submissions', '学生选课方案', 'curriculum'], ['riskcheck', '选课风险检查', 'analytics'], ['analytics', '群体洞察', 'analytics'], ['curriculum', '培养方案', 'file']],
    [['assistant', '知学助手', 'assistant']]
  ];
  const q = value => value == null ? '—' : Number(value).toLocaleString('zh-CN', {maximumFractionDigits: 2});
  const jump = (page, label, style='ix-link') => `<button type="button" class="${style}" data-page="${page}">${html(label)} ${ico('next')}</button>`;
  const detail = (id, label, style='ix-link',follow=false) => `<button type="button" class="${style}" data-action="alert" data-id="${html(id)}" ${follow?'data-ix-follow="true"':''}>${html(label)} ${ico('next')}</button>`;
  const title = (name, context='', action='') => `<header class="ix-title"><div><h1>${html(name)}</h1>${context?`<p>${html(context)}</p>`:''}</div>${action}</header>`;
  const section = (name, content, aside='') => `<section class="ix-section"><div class="ix-section-head"><h2>${html(name)}</h2>${aside}</div>${content}</section>`;
  const fold = (name, content) => `<details class="ix-fold"><summary>${html(name)}</summary><div>${content}</div></details>`;
  const mark = `<span class="ix-mark" aria-hidden="true"><svg viewBox="0 0 40 40" fill="none"><path d="M9 9.5c4 0 7.2 1.5 10.5 4.3v17c-3.3-2.7-6.6-4.2-10.5-4.4V9.5Z" fill="#d6e7b5"/><path d="M22 13.5c2.5-2.1 5.6-3.8 9.2-4.1v16.9a19 19 0 0 0-9.2 4.3V13.5Z" fill="white"/><path d="M15 6l4.5 2.4v2.3L15 8.4V6Z" fill="#d6e7b5"/></svg></span>`;
  const brand = `<div class="ix-brand">${mark}<strong>知学</strong></div>`;
  let tabChoices = new Map();

  function login(accounts) {
    document.body.classList.remove('home-preview');
    const demo = accounts.find(a=>a.id==='2024CS013') || accounts.find(a=>a.role==='student');
    const staff = accounts.find(a=>a.role==='counselor');
    const admin = accounts.find(a=>a.role==='admin');
    const demoButton = (user,label) => user ? `<button type="button" class="ix-demo-role" data-action="demo" data-id="${html(user.id)}">${html(label)} ${ico('next')}</button>` : '';
    $('#app').innerHTML = `<main class="ix-login">
      <div class="ix-login-copy">${brand}<div class="ix-auth"><h1>登录知学</h1><p class="ix-login-sub">学业预警与成长支持工作台</p>
      <form id="login"><label class="form-item">学号 / 工号<input class="field" name="username" autocomplete="username" placeholder="输入学号或工号" required></label>
      <label class="form-item">密码<input class="field" name="password" type="password" autocomplete="current-password" placeholder="输入密码" required></label>
      <div class="inline-error" id="login-error" hidden></div><button class="btn primary ix-enter" type="submit">进入工作台 ${ico('arrow')}</button></form>
      ${accounts.length?`<section class="ix-demo"><h2>使用模拟账号体验</h2><div>${demoButton(demo,'学生')}${demoButton(staff,'辅导员')}${demoButton(admin,'管理员')}</div></section>`:''}</div>
      <a class="ix-other" href="/campus">${ico('curriculum')} 校园工作台 ${ico('next')}</a></div>
      <div class="ix-login-photo"><img src="/assets/media/study-desk.webp" alt="" width="1040" height="1300" fetchpriority="high"></div></main>`;
    window.scrollTo({top:0,behavior:'instant'});
  }

  function frame() {
    tabChoices = new Map();
    CampusRisk.reset();
    CampusRegisters.reset();
    const user=S.user, student=user.role==='student';
    const groups=student?studentMenu:staffMenu;
    const groupNames = student?['我的工作台','学业规划','咨询']:['工作台','学业管理','咨询'];
    const navItem=([page,label,icon])=>`<button type="button" class="nav-item" data-page="${page}">${ico(icon)}<span>${html(label)}</span></button>`;
    $('#app').innerHTML=`<div class="app-frame ix-frame"><a class="ix-skip" href="#page">跳至内容</a>
      <aside class="rail" id="workspace-navigation">${brand}<button class="icon-btn rail-close" type="button" data-action="mobile-nav-close" aria-label="关闭导航">${ico('close')}</button>
      <nav aria-label="主菜单">${groups.map((group,i)=>`<div class="ix-nav-group"><div class="nav-label">${groupNames[i]}</div>${group.map(navItem).join('')}</div>`).join('')}${user.role==='admin'?navItem(['settings','数据与设置','settings']):''}</nav>
      <div class="rail-bottom"><a class="ix-other" href="/campus">${ico('curriculum')} 校园工作台 ${ico('next')}</a>
      <button class="user-button" data-action="account"><span class="avatar">${html(user.name.slice(-2))}</span><span><strong>${html(user.name)}</strong><small>${html(roles[user.role])}</small></span>${ico('next')}</button></div></aside>
      <main class="main-area"><header class="masthead"><button class="icon-btn mobile-menu" data-action="menu" aria-label="展开导航" aria-controls="workspace-navigation" aria-expanded="false">${ico('menu')}</button>
      <div class="crumb"><span>${html(roles[user.role])}工作台</span><span aria-hidden="true"> / </span><b id="crumb">工作台</b></div>
      <div class="masthead-tools">${S.demo?'<span class="ix-demo-label"><i></i>模拟数据</span>':''}<button class="icon-btn" data-action="notifications" aria-label="站内通知">${ico('bell')}</button></div></header>
      <div class="page" id="page" tabindex="-1"></div></main></div>`;
    configureMobileNavigation();
  }

  function onView(page) {
    document.body.classList.toggle('home-preview',page==='mine'&&S.user.role==='student');
    $$('.rail [data-page]').forEach(el=>{
      if(el.dataset.page===page)el.setAttribute('aria-current','page');
      else el.removeAttribute('aria-current');
    });
  }
  function afterView(page) {
    const labels={planner:'学期选课规划',riskcheck:'选课风险检查',reconcile:'学分差异核对',grades:'成绩明细'};
    if(page==='reconcile'||page==='grades'){
      const parent=$('.rail [data-page="credits"]');
      parent?.classList.add('active');
      parent?.setAttribute('aria-current','location');
    }
    $('#crumb').textContent=$(`.rail [data-page="${page}"] span`)?.textContent || labels[page] || '工作台';
    window.scrollTo({top:0,behavior:'instant'});
  }

  function tabs(group, entries, label) {
    const current=entries.some(([key])=>key===tabChoices.get(group))?tabChoices.get(group):entries[0][0];
    return `<div class="ix-tabs" data-ix-group="${group}"><div class="ix-tabbar" role="tablist" aria-label="${html(label)}">
      ${entries.map(([key,name])=>`<button type="button" role="tab" id="ix-${group}-${key}-tab" aria-controls="ix-${group}-${key}" aria-selected="${key===current}" tabindex="${key===current?0:-1}" data-ix-tab="${key}">${html(name)}</button>`).join('')}</div>
      ${entries.map(([key,,content])=>`<div class="ix-tabpanel" role="tabpanel" tabindex="0" id="ix-${group}-${key}" aria-labelledby="ix-${group}-${key}-tab" ${key===current?'':'hidden'}>${content}</div>`).join('')}</div>`;
  }
  function selectTab(group,key,focus=false) {
    const container=document.querySelector(`[data-ix-group="${group}"]`);
    if(!container)return;
    const buttons=$$(':scope > .ix-tabbar > [data-ix-tab]',container);
    if(!buttons.some(b=>b.dataset.ixTab===key))return;
    tabChoices.set(group,key);
    buttons.forEach(b=>{
      const selected=b.dataset.ixTab===key;
      b.setAttribute('aria-selected',String(selected));
      b.tabIndex=selected?0:-1;
      document.getElementById(b.getAttribute('aria-controls')).hidden=!selected;
      if(selected&&focus)b.focus();
    });
  }
  document.addEventListener('click',event=>{
    const tab=event.target.closest('[data-ix-tab]');
    if(tab)selectTab(tab.closest('[data-ix-group]').dataset.ixGroup,tab.dataset.ixTab);
    const next=event.target.closest('[data-ix-stage]');
    if(next)selectTab('planning',next.dataset.ixStage,true);
  });
  document.addEventListener('keydown',event=>{
    const tab=event.target.closest('[data-ix-tab]');
    if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const bar=tab.parentElement, buttons=$$('[data-ix-tab]',bar);
    const at=buttons.indexOf(tab), n=buttons.length;
    const next=event.key==='Home'?0:event.key==='End'?n-1:(at+(event.key==='ArrowLeft'?-1:1)+n)%n;
    selectTab(bar.parentElement.dataset.ixGroup,buttons[next].dataset.ixTab,true);
  });

  function routeRow(page,icon,name,note) {
    return `<button class="ix-route" data-page="${page}"><span class="ix-route-icon">${ico(icon)}</span><span><strong>${html(name)}</strong><small>${html(note)}</small></span>${ico('next')}</button>`;
  }
  function metric(label,value,unit='') {
    return `<div><dt>${html(label)}</dt><dd>${html(value)}${unit?`<small>${html(unit)}</small>`:''}</dd></div>`;
  }
  function creditMeter(c) {
    const credited=c.credited??c.earned, hasTotal=Number(c.total)>0;
    const ratio=hasTotal?Math.min(100,Math.max(0,100*(credited||0)/c.total)):0;
    return `<div class="ix-credit-meter"><div>计入培养要求的学分</div><p><b>${q(credited)}</b> <span>/ ${q(c.total)}</span></p>
      <div class="ix-meter-track" aria-hidden="true"><i style="width:${ratio}%"></i></div><small>分类要求尚差 ${q(c.remaining)} 学分</small></div>`;
  }
  function spotlight({label,headline,body,action,aside}) {
    return `<section class="ix-focus"><div class="ix-focus-main">${label?`<div class="ix-focus-label">${html(label)}</div>`:''}<h2>${html(headline)}</h2><p>${html(body)}</p>${action}</div>${aside||''}</section>`;
  }
  function alertEvidence(a) {
    return CampusPortrait.shortEvidence(a);
  }
  async function mine() { return StudentHome.view(); }

  function sectionRow(name,note,action) {
    return `<div class="ix-list-row"><div><strong>${html(name)}</strong><small>${html(note)}</small></div>${action}</div>`;
  }
  function riskFilters() {
    return `<div class="tools"><div class="segmented" role="tablist" aria-label="筛选风险等级">${[['','全部'],['3','危急'],['2','一般'],['1','轻微']].map(([id,n])=>`<button role="tab" aria-selected="${S.level===id}" class="${S.level===id?'active':''}" data-action="level" data-value="${id}">${n}</button>`).join('')}</div><label class="search">${ico('search')}<input class="field" id="queue-query" value="${html(S.query)}" placeholder="姓名或学号" aria-label="搜索预警学生"></label></div><div id="queue-table"></div>`;
  }
  async function overview() {
    const ticket=S.ticket;
    const [d,result]=await Promise.all([request('/api/overview'),request('/api/alerts')]);
    if(ticket!==S.ticket)return '';
    S.overview=d;S.alerts=result.items||[];S.pageNo=1;
    const active=S.alerts.filter(a=>a.active);
    const items=d.todos||[], first=items[0];
    const focal=first?{label:first.nextReview?'优先复查':'优先跟进',headline:`${first.studentName} · ${first.title}`,body:[first.levelName,first.statusName,first.nextReview?`复查日期 ${first.nextReview.slice(0,10)}`:alertEvidence(first)].filter(Boolean).join(' · '),action:detail(first.id,'打开跟进记录','ix-focus-action',true)}:
      {label:'学生跟进',headline:'当前没有待跟进预警',body:'可以查看已记录的帮扶进展或学生提交的方案。',action:jump('ledger','查看帮扶台账','ix-focus-action')};
    const aside=`<dl class="ix-case-counts">${metric('需关注学生',q(d.activeStudents),'人')}${metric('在管学生',q(d.students),'人')}</dl>`;
    const todo=items.slice(1).map(a=>sectionRow(`${a.studentName} · ${a.title}`,[a.statusName,a.nextReview?`复查 ${a.nextReview.slice(0,10)}`:''].filter(Boolean).join(' · '),detail(a.id,'跟进','ix-link',true))).join('')||'<p class="ix-empty">当前没有其他待跟进事项。</p>';
    const counts=new Map();
    active.forEach(a=>counts.set(a.kindName,(counts.get(a.kindName)||0)+1));
    const distribution=[...counts.entries()].sort((a,b)=>b[1]-a[1]).map(([name,n])=>`<div class="ix-bar-row"><span>${html(name)}</span><i><b style="width:${100*n/Math.max(1,active.length)}%"></b></i><strong>${q(n)} 条</strong></div>`).join('')||'<p class="ix-empty">暂无有效预警。</p>';
    return title('工作概览',[S.user.name,S.status.term?S.status.term+' 学期':''].filter(Boolean).join(' · '),btn('导出台账','export','download'))+
      spotlight({...focal,aside})+`<div class="ix-staff-inbox" id="overview-inbox" aria-label="方案与通知"></div>`+
      tabs('work',[['todo','待跟进',todo+jump('ledger','完整帮扶台账')],['alerts',`有效预警（${active.length}）`,riskFilters()],['mix','预警分布',distribution]],'辅导员工作清单');
  }

  function courseList() {
    return `<div class="offering-filters"><label class="search">${ico('search')}<input id="profile-course-query" class="field" placeholder="课程名称或代码" aria-label="搜索课程"></label>
      <select id="profile-course-filter" aria-label="修读状态"><option value="">全部状态</option><option value="failed">未通过</option><option value="enrolled">待出分</option><option value="passed">已通过</option><option value="remaining">尚未修读</option></select></div>
      <div class="table-scroll"><table><thead><tr><th>课程</th><th>学分</th><th>成绩</th><th>修读状态</th></tr></thead><tbody id="profile-course-list"></tbody></table></div><div id="course-pager" class="table-bottom"></div>`;
  }
  async function credits() {
    const ticket=S.ticket,id=S.user.id;
    const [p,a]=await Promise.all([request(apiStudent(id)),request(apiStudent(id)+'/curriculum-audit')]);
    if(ticket!==S.ticket)return '';
    S.profile=p;S.ws.audit=a;
    const c=p.credits,selected=(a.moduleAudits||[]).filter(m=>m.selected);
    const route=section('培养路线',preferencesForm(a))+section('专业进阶模块',selected.length?selected.map(auditModule).join(''):'<p class="ix-empty">请先选择进阶模块，再核对限选和任选要求。</p>')+
      section(a.pathAudit?.name||'个性化路径',auditCheckList(a.pathAudit?.checks)+(a.pathAudit?.notes||[]).map(n=>`<p class="source">${html(n)}</p>`).join(''));
    const sources=(a.sources||[]).map(x=>`<p>${typeof x==='string'?html(x):html(x.title)+(x.page?' · 第 '+html(x.page)+' 页':'')}</p>`).join('');
    return title('学分核对',p.student.majorName,jump('riskcheck','检查选课风险','btn'))+
      `<dl class="ix-metrics">${metric('毕业要求',q(c.total),'学分')}${metric('已计入培养要求',q(c.credited??c.earned),'学分')}${metric('分类缺口',q(c.remaining),'学分')}</dl>`+
      tabs('credits',[['progress','各类学分',jump('reconcile','核对已获与计入学分的差异')+creditBars({categories:a.categories||[]})+fold('专项要求',auditCheckList(a.checks))],['path','培养路线',route],['records','课程明细',courseList()+jump('grades','查看原始成绩记录')]],'学分核对方式')+
      (sources||p.metrics?.dataNotes?.length?fold('数据与培养方案出处',dataNotes(p)+sources):'');
  }

  function planning(p,student,readOnly) {
    const options=[['unfinished','未完成课程'],['recommended','推荐课程'],['selected','已选组合'],['required','必修课程'],['all','全部开课']];
    const offering=`<div class="ix-planner-tools">${p.recommended?.courseIds?.length&&!readOnly?`<button class="btn" data-action="use-recommendation">采用推荐组合 · ${q(p.recommended.courseIds.length)} 门</button>`:''}
      <button class="btn primary" data-ix-stage="review">查看我的组合 ${ico('next')}</button></div>
      <div class="offering-filters"><label class="search">${ico('search')}<input class="field" id="offering-query" placeholder="课程名称或代码" aria-label="搜索开课课程"></label>
      <select id="offering-filter" aria-label="筛选课程">${options.map(([v,k])=>`<option value="${v}" ${v===S.ws.offeringFilter?'selected':''}>${k}</option>`).join('')}</select></div><div id="offering-list"></div><div id="offering-pagination" class="table-bottom"></div>`;
    const review=`<div id="plan-comparison-evidence">${PlanEvidence.render(S.ws.planComparison,S.ws.selection)}</div><div class="ix-plan-review">${section('我的课程组合',`<div id="selection-summary">${selectionSummary()}</div>`)}
      ${section('组合检查',`<div id="plan-check-result">${checkMarkup(S.ws.planningCheck)}</div>`)}</div>${reviewForm(p.savedPlan,student.id,p.term)}`;
    const notes=(p.notes||[]).map(n=>`<p>${html(n)}</p>`).join('');
    return title('学期选课规划',student.majorName,`<button class="btn" data-action="planner-audit">查看培养要求</button>`)+
      `<div class="ix-plan-term"><label>规划学期 <select id="planning-term" aria-label="规划学期">${termChoices(p.term)}</select></label>${p.dataMode==='demo'?'<span>模拟开课与课表</span>':p.dataMode==='unavailable'?'<span>暂无开课数据</span>':''}</div>`+
      planReviewBanner(p.savedPlan)+tabs('planning',[['courses','选择课程',offering],['review','检查与提交',review]],'选课规划步骤')+
      (notes?fold('开课数据与推荐依据',notes):'');
  }

  function riskPicker(selector) {
    return title('选课风险检查','选择一名负责的学生，核对其下学期课程安排。')+selector;
  }
  function grades(d,gradeList) {
    const terms=[...new Set(d.items.map(r=>r.term))].sort().reverse();
    const term=terms[0]||'';
    const bands=d.gpaBands.map(([low,points],i,all)=>`${low===0?'低于 60':low+'–'+(i?all[i-1][0]-1:100)} 分 · ${Number(points).toFixed(1)}`);
    const policy=`<p>${html(d.gpaMethod)}</p><p>${bands.map(html).join('　')}</p><a class="ix-link" href="${html(d.gpaSource)}" rel="noopener noreferrer" target="_blank">校规第十二条 ↗</a>`;
    return title('成绩明细',S.user.name,jump('credits','返回学分核对','btn'))+
      `<div class="business-filter"><label>学期 <select id="grade-term"><option value="">全部学期</option>${terms.map(t=>`<option ${t===term?'selected':''}>${html(t)}</option>`).join('')}</select></label>
      <label>成绩状态 <select id="grade-state"><option value="all">全部状态</option><option value="pending">待出分</option><option value="failed">未通过</option></select></label></div>`+
      fold('绩点换算与成绩口径',`<p>${html(d.note)}</p>${policy}`)+`<div id="grade-list">${gradeList(d,term)}</div>`;
  }
  function reconciliation(r,detailRows) {
    const {table,row,cell}=CampusViews.ui,t=r.totals;
    const pending=(r.pendingAllocation||[]).map(c=>row(cell(c.name),cell(q(c.credits)),cell('有多个可归属模块，请核对修读路径'))).join('');
    const diff=Math.round((t.recordedPassed-t.credited)*100)/100;
    const details=`<p class="ix-caption">${diff?`当前成绩记录中通过的学分，有 ${q(diff)} 分未计入分类要求。`:'已通过、符合路线与计入分类要求三项学分目前一致。'}${r.historyComplete?'':'历史记录仍待核对。'}</p>`+
      (detailRows?table(['课程或类别','差异原因','学分差额','核对方向'],detailRows):'')+
      (pending?fold('待确认的模块归属',table(['课程','学分','归属'],pending)):'');
    const options=(r.languageTrials||[]).filter(l=>l.id!==r.currentLanguage);
    const trial=options.length?`<label>试算路线 <select id="language-trial"><option value="">选择另一条外语路线</option>${options.map(l=>`<option value="${html(l.id)}">${html(l.name)}</option>`).join('')}</select></label>
      <p class="ix-caption">按同一批已通过课程试算，当前修读选择仅在培养路线页保存。</p><div id="trial-result" aria-live="polite"></div>`:'<p class="ix-empty">培养方案中没有可供比较的其他外语路线。</p>';
    return title('学分差异核对',S.user.name,jump('credits','返回学分核对','btn'))+
      `<dl class="ix-metrics">${metric('成绩记录已通过',q(t.recordedPassed),'学分')}${metric('符合当前路线',q(t.routeEarned),'学分')}${metric('计入分类要求',q(t.credited),'学分')}</dl>`+
      tabs('reconcile',[['detail','差异明细',details],['trial','外语路线试算',trial]],'学分差异与试算');
  }
  function risk(data,parts) {
    const priority=data.priority.length?parts.courseRows(data.priority):'<p class="ix-empty">当前记录中没有需优先核对的课程。</p>';
    const upcoming=data.upcoming.length?parts.courseRows(data.upcoming):'<p class="ix-empty">培养方案中未找到建议该学期修读的课程。</p>';
    const body=`<p class="ix-caption">${html(parts.compareNote)}</p>${priority}${fold(`建议下学期修读的必修或限选课（${data.upcoming.length} 门）`,upcoming)}
      <div id="risk-comparison" aria-live="polite" tabindex="-1"></div>`;
    return title('选课风险检查',[data.student.name,data.term+' 学期',parts.source].filter(Boolean).join(' · '),`<button class="btn" data-action="open-planner" data-student="${html(data.student.id)}" data-term="${html(data.term)}">打开下学期方案 ${ico('next')}</button>`)+
      parts.selector+(parts.quality.length?`<p class="tip warn">${html(parts.quality.join('，'))}，试算仅采用已导入记录。</p>`:'')+
      `<dl class="ix-metrics">${metric('当前分类缺口',q(data.credits.remaining),'学分')}${metric('符合路线的在读课程',q(data.credits.studying),'学分')}${metric('若在读均通过，仍需',q(data.credits.ifPassedRemaining),'学分')}</dl>`+
      tabs('risk',[['courses','选与暂不选',body],['basis','学分依据',parts.studyFacts(data)],['warnings','关联预警',parts.alertRows(data)]],'选课风险检查详情');
  }

  function conversation() {
    const history=fold('最近对话',threadRail());
    const context=S.ws.chatContext?'当前学生 '+S.ws.chatContext:S.user.role==='student'?S.user.name+'的学业咨询':'当前账号可见的学生';
    return title('知学助手',context,`<button class="btn" data-action="new-thread">${ico('assistant')} 新对话</button>`)+
      `<div class="ix-chat-meta"><span>${S.status.ai?.configured&&S.status.ai.mode==='remote'?'大模型已接入':'本地工作流'}</span>${history}</div>
      <section class="ix-chat"><div id="conversation-body">${chatBody()}</div></section>`;
  }
  function register(kind,scope,action,filters,rows) {
    return title(kind==='ledger'?'帮扶台账':'学生画像',scope,action)+
      `<section data-register="${kind}" class="ix-register">${filters}<div data-sheet-result>${rows}</div></section>`;
  }
  function registerFilters(search,options,applied) {
    return `<div class="ix-register-filters">${search}<details class="ix-fold" ${applied?'open':''}><summary>筛选条件</summary><div>${options}</div></details></div>`;
  }
  async function actions() {
    const ticket=S.ticket,d=await request('/api/my/plan');
    if(ticket!==S.ticket)return '';
    S.ws.tasks=d.tasks||[];
    const pending=S.ws.tasks.filter(t=>!t.completed).length;
    const create=`<form id="task-create"><div class="form-grid"><label class="form-item full">行动名称<input class="field" name="title" required maxlength="120"></label>
      <label class="form-item full">具体安排（可选）<textarea name="description" maxlength="1500"></textarea></label>
      <label class="form-item">计划完成日期（可选）<input class="field" name="dueDate" type="date"></label></div><div class="form-actions"><button class="btn primary" type="submit">添加行动</button></div><div class="form-error"></div></form>`;
    const filters=[['active','进行中'],['done','已完成'],['all','全部']].map(([id,n])=>`<button data-action="task-filter" data-id="${id}" class="${S.ws.taskFilter===id?'active':''}">${n}</button>`).join('');
    return title('学习行动',`${pending} 项进行中 · ${S.ws.tasks.length-pending} 项已完成`,`<button class="btn" data-action="ask" data-question="请结合我的学情，生成一份可以采纳的学习行动计划。" data-student="${html(S.user.id)}">${ico('assistant')} 请知学拟计划</button>`)+
      fold('添加学习行动',create)+`<div class="segmented space-b">${filters}</div><div id="task-list" class="task-list">${taskRows()}</div>`;
  }
  async function myAlerts() {
    const ticket=S.ticket,d=await request('/api/alerts');
    if(ticket!==S.ticket)return '';
    S.alerts=d.items||[];
    const list=rows=>rows.length?rows.map(a=>`<article class="ix-alert-line"><div>${badge(a.level,a.levelName)}<span>${html(a.statusName||statuses[a.status])}</span></div><h2>${html(a.title)}</h2><p>${html([a.kindName,a.ownerName?`${a.ownerName}负责跟进`:''].filter(Boolean).join(' · '))}</p>${detail(a.id,'原因与跟进')}</article>`).join(''):'<p class="ix-empty">暂无对应的预警记录。</p>';
    const active=S.alerts.filter(a=>a.active),previous=S.alerts.filter(a=>!a.active);
    return title('我的预警')+tabs('alerts',[['active',`当前预警（${active.length}）`,list(active)],['past','历史记录',list(previous)]],'预警记录');
  }

  function drawerTabs(key,groups,initial) {
    const body=$('.drawer-body');
    if(!body||groups.some(group=>!group[2].length))return;
    tabChoices.set(key,initial||groups[0][0]);
    const fragment=document.createElement('template');
    fragment.innerHTML=tabs(key,groups.map(([id,label])=>[id,label,'']),'详情分栏');
    const result=fragment.content.firstElementChild;
    body.append(result);
    for(const [id,,nodes] of groups)result.querySelector(`#ix-${key}-${id}`).append(...nodes);
  }
  function alertDrawer(initial) {
    const body=$('.drawer-body');
    if(!body)return;
    const evidence=$('.evidence',body)?.closest('.card');
    const cards=$$(':scope > .card',body);
    if(!evidence||cards.length<2)return;
    const extra=$(':scope > .button-row',body);
    const source=$(':scope > .source',body);
    const reason=[evidence,extra,source].filter(Boolean);
    drawerTabs('alert-detail',[['reason','预警依据',reason],['follow','跟进与反馈',cards.filter(c=>c!==evidence)]],initial);
  }
  function profileDrawer() {
    const body=$('.drawer-body');
    if(!body)return;
    const cards=$$(':scope > .card',body);
    const courses=cards.filter(c=>c.querySelector('#profile-course-list,.credit-row'));
    const others=cards.filter(c=>!courses.includes(c));
    drawerTabs('profile-detail',[['state','学情与行动',others],['courses','学分与课程',courses]]);
  }
  async function openCourseRecords(code,state) {
    const loading=go('credits'),ticket=S.ticket;
    await loading;
    if(ticket!==S.ticket||S.page!=='credits')return;
    const query=$('#profile-course-query'),filter=$('#profile-course-filter');
    if(!query||!filter)return;
    selectTab('credits','records');
    query.value=code||'';filter.value=state||'';
    S.coursePage=1;drawCourses();
    query.focus();
  }

  return {login,frame,onView,afterView,planning,conversation,register,registerFilters,risk,riskPicker,grades,reconciliation,alertDrawer,profileDrawer,panels:tabs,openCourseRecords,
    showDraftOnOpen:()=>tabChoices.set('planning','review'),riskButton:(id)=>CampusRisk.entryButton(id),
    views:{mine,overview,credits,plan:actions,myalerts:myAlerts,riskcheck:()=>CampusRisk.view(),reconcile:()=>CampusViews.reconcile(),grades:()=>CampusViews.grades(),
      students:()=>CampusRegisters.students(),ledger:()=>CampusRegisters.ledger()}};
})();
