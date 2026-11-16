'use strict';
const CampusRegisters=(()=>{
  const {q,title,table,cell,row,note}=CampusViews.ui;
  const defaults=()=>({items:[],query:'',level:'',status:'',due:false,page:1});
  const state={ledger:defaults(),students:defaults(),active:defaults()};
  const levels=[['3','危急预警'],['2','一般预警'],['1','轻度预警']];
  const dayFormat=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'});
  function reset(){state.ledger=defaults();state.students=defaults();state.active=defaults();}
  function due(a,today){return a.status!=='closed'&&Boolean(a.nextReview)&&a.nextReview<=today;}
  function badgeForStudent(s){
    const level=levels.find(([id])=>id===String(s.riskLevel));
    return level?badge(s.riskLevel,level[1]):'<span class="course-flag quiet">无当前预警</span>';
  }
  function small(value){return `<small class="table-sub">${html(value)}</small>`;}
  function matches(query,fields) {
    const haystack=fields.filter(Boolean).join(' ').toLocaleLowerCase();
    return query.trim().toLocaleLowerCase().split(/\s+/).every(word=>haystack.includes(word));
  }
  function optionList(pairs,selected) {
    return pairs.map(([id,name])=>`<option value="${html(id)}"${id===selected?' selected':''}>${html(name)}</option>`).join('');
  }
  function filters(kind) {
    const s=state[kind], isLedger=kind!=='students';
    const levelOptions=isLedger?levels:[...levels,['0','无当前预警']];
    const hint=isLedger?'姓名、学号、班级或预警事项':'姓名、学号、班级或专业';
    const search=`<label>查询 <input type="search" data-sheet-filter="query" value="${html(s.query)}" placeholder="${hint}" aria-label="${hint}"></label>`;
    const options=`<label>预警级别 <select aria-label="预警级别" data-sheet-filter="level"><option value="">全部级别</option>${optionList(levelOptions,s.level)}</select></label>
      ${isLedger?`<label>处理进度 <select aria-label="处理进度" data-sheet-filter="status"><option value="">全部进度</option>${optionList(Object.entries(statuses),s.status)}</select></label>
      <label><input type="checkbox" data-sheet-filter="due"${s.due?' checked':''}> 仅看复查到期</label>`:''}
      <button class="campus-link" type="button" data-sheet-reset>清除筛选</button>`;
    if(window.IndependentUI)return IndependentUI.registerFilters(search,options,Boolean(s.level||s.status||s.due));
    return `<div class="business-filter record-filters">${search}${options}</div>`;
  }
  function rosterRow(s) {
    return row(`<td><strong>${html(s.name)}</strong>${small(s.id)}</td>`,
      `<td>${html(s.majorName)}${small(s.className)}</td>`,cell(q(s.earnedCredits)+' / '+q(s.totalCredits)),
      `<td>${badgeForStudent(s)}${s.alertCount?small(s.alertCount+' 条当前预警'):''}</td>`,cell(s.portrait||'待核对'),
      `<td><button class="campus-link" data-action="profile" data-id="${html(s.id)}" aria-label="查看${html(s.name)}的学情画像">查看画像</button></td>`);
  }
  function ledgerRow(a,today) {
    const review=a.nextReview?html(a.nextReview)+(due(a,today)?small('复查已到期'):''):'—';
    return row(`<td><button class="campus-link" data-action="profile" data-id="${html(a.studentId)}" aria-label="查看${html(a.studentName)}的学情画像">${html(a.studentName)}</button>${small(a.studentId)}</td>`,
      `<td><strong>${html(a.title)}</strong>${small(CampusPortrait.shortEvidence(a))}</td>`,
      `<td>${badge(a.level,a.levelName)}${!a.active?small(a.signalStateName):''}</td>`,
      `<td>${html(a.statusName)}${small(a.ownerName+'负责')}</td>`,
      `<td class="${due(a,today)?'review-due':''}">${review}</td>`,
      `<td><button class="campus-link" data-action="alert" data-ix-follow="true" data-id="${html(a.id)}" aria-label="${html(a.studentName+'，'+a.title+'，跟进记录')}">跟进记录</button></td>`);
  }
  function filtered(kind,today) {
    const s=state[kind];
    if(kind==='students')return s.items.filter(x=>
      (!s.level||String(x.riskLevel||0)===s.level)&&matches(s.query,[x.name,x.id,x.className,x.majorName,x.portrait]));
    const list=s.items.filter(x=>(!s.level||String(x.level)===s.level)&&(!s.status||x.status===s.status)&&
      (!s.due||due(x,today))&&matches(s.query,[x.studentName,x.studentId,x.className,x.title,x.kindName,x.ownerName]));
    return list.sort((a,b)=>Number(a.status==='closed')-Number(b.status==='closed')||
      Number(due(b,today))-Number(due(a,today))||b.level-a.level||
      (a.nextReview||'9999').localeCompare(b.nextReview||'9999')||b.updatedAt.localeCompare(a.updatedAt)||a.id.localeCompare(b.id));
  }
  function result(kind) {
    const pageSize=window.IndependentUI?8:20;
    const s=state[kind],today=dayFormat.format(new Date()),list=filtered(kind,today),pages=Math.max(1,Math.ceil(list.length/pageSize));
    s.page=Math.min(Math.max(s.page,1),pages);
    const section=list.slice((s.page-1)*pageSize,s.page*pageSize);
    const isLedger=kind!=='students';
    const headers=isLedger?['学生','预警事项及依据','预警级别','处理进度','复查日期','操作']:['学生','专业 / 班级','已获 / 要求学分','预警级别','画像特征','操作'];
    const content=section.length?table(headers,section.map(x=>isLedger?ledgerRow(x,today):rosterRow(x)).join(''),true):
      note(s.items.length?'当前筛选没有匹配记录，可调整条件或清除筛选。':(isLedger?'本学期暂无可查看的台账记录。':'暂无可查看的学生。'));
    const summary=isLedger?`${list.length} 条记录 · ${new Set(list.map(a=>a.studentId)).size} 名学生`:`${list.length} 名学生`;
    const dueCount=isLedger?list.filter(a=>due(a,today)).length:0;
    const pageControls=list.length>pageSize?`<div class="register-pages"><button type="button" data-sheet-page="-1" ${s.page===1?'disabled':''}>上一页</button>
      <span>第 ${s.page} / ${pages} 页</span><button type="button" data-sheet-page="1" ${s.page===pages?'disabled':''}>下一页</button></div>`:'';
    return `<div class="register-caption"><strong role="status">${summary}</strong>${dueCount?`<span>其中 ${dueCount} 条复查已到期</span>`:''}</div>
      ${content}<div class="register-bottom">${pageControls}</div>`;
  }
  async function view(kind) {
    const ticket=S.ticket;
    const isLedger=kind==='ledger';
    const data=await request(isLedger?'/api/alerts':'/api/students');
    if(ticket!==S.ticket)return '';
    state[kind].items=data.items||[];
    if(isLedger)S.alerts=state[kind].items;else S.students=state[kind].items;
    const caption=isLedger?'预警帮扶台账':'学生画像';
    const exportAll=isLedger?'<button class="campus-button" data-action="export">导出本学期完整台账</button>':'';
    const scope=S.user.role==='admin'?'全部学生':'我负责的学生';
    if(window.IndependentUI)return IndependentUI.register(kind,scope,exportAll,filters(kind),result(kind));
    return `<section class="school-register" data-register="${kind}">${title(caption,exportAll)}
      <div class="business-meta"><strong>${html(S.status.term||'当前学期')}</strong><span>${scope}</span></div>
      ${filters(kind)}<div data-sheet-result>${result(kind)}</div></section>`;
  }
  async function overview() {
    const ticket=S.ticket;
    const [d,cases]=await Promise.all([request('/api/overview'),request('/api/alerts')]);
    if(ticket!==S.ticket)return '';
    const active=(cases.items||[]).filter(a=>a.active);
    state.active.items=active;S.overview=d;S.alerts=cases.items||[];
    const counts=new Map();
    for(const a of active)counts.set(a.kindName,(counts.get(a.kindName)||0)+1);
    const figures=[['在管学生',d.students,'人'],['需关注学生',d.activeStudents,'人'],['待联系预警',d.pending,'条'],['到期复查',d.dueReviews,'条']];
    const facts=`<dl class="profile-facts">${figures.map(([name,value,unit])=>`<div><dt>${html(name)}</dt><dd>${q(value)} ${unit}</dd></div>`).join('')}</dl>`;
    const distribution=[...counts].map(([name,n])=>row(cell(name),cell(n),cell(Math.round(n*100/active.length)+'%'))).join('');
    const ledgerLink='<button class="campus-button" data-page="ledger">完整帮扶台账</button>';
    const todos=(d.todos||[]).slice(0,3).map(a=>row(cell(a.studentName),cell(a.title),
      cell(a.nextReview||'待约定'),`<td><button class="campus-link" data-action="alert" data-id="${html(a.id)}">查看跟进</button></td>`)).join('');
    return title('学情总览',ledgerLink+'<button class="campus-button" data-action="export">导出本学期完整台账</button>')+
      `<div class="business-meta"><strong>${html(d.term)}</strong><span>${S.user.role==='admin'?'全部学生':'我负责的学生'}</span>
      <button class="campus-link" data-page="students">查看学生画像</button><button class="campus-link" data-action="refresh">刷新学情</button></div>${facts}
      <div class="overview-services"><div id="overview-inbox" aria-label="选课方案与通知"></div>
      <button class="campus-link" data-action="ask" data-question="今天应该优先关注哪些学生？">让知学整理跟进顺序</button></div>
      <section class="school-register" data-register="active"><div class="section-line"><h2 class="business-subtitle">当前分级预警</h2>
      <span class="overview-levels">危急 ${q(d.alerts.urgent)} · 一般 ${q(d.alerts.attention)} · 轻度 ${q(d.alerts.notice)}</span></div>
      ${filters('active')}<div data-sheet-result>${result('active')}</div></section>
      <details class="sheet-detail"><summary>分类型统计与优先跟进事项</summary>
      <div class="sheet-pair sheet-compact">${distribution?table(['预警类型','条数','占当前预警'],distribution):note('暂无当前预警。')}
      ${todos?table(['学生','跟进事项','复查日期','操作'],todos,true):note('暂无待跟进事项。')}</div>
      ${note('本学期已结案 '+q(d.closed)+' 条。')}</details>`;
  }
  function refresh(section){section.querySelector('[data-sheet-result]').innerHTML=result(section.dataset.register);}
  function changeFilter(event) {
    const input=event.target.closest('[data-sheet-filter]'),section=input?.closest('[data-register]');
    if(!section)return;
    const s=state[section.dataset.register];
    s[input.dataset.sheetFilter]=input.type==='checkbox'?input.checked:input.value;
    s.page=1;refresh(section);
  }
  document.addEventListener('input',e=>{if(e.target.type==='search')changeFilter(e);});
  document.addEventListener('change',e=>{if(e.target.type!=='search')changeFilter(e);});
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-sheet-reset],[data-sheet-page]'),section=button?.closest('[data-register]');
    if(!section)return;
    const kind=section.dataset.register,s=state[kind];
    if(button.hasAttribute('data-sheet-reset')) {
      state[kind]={...defaults(),items:s.items};
      section.querySelectorAll('[data-sheet-filter]').forEach(input=>{if(input.type==='checkbox')input.checked=false;else input.value='';});
      refresh(section);section.querySelector('input[type=search]').focus();
    } else {
      s.page+=Number(button.dataset.sheetPage);refresh(section);
      const target=section.querySelector('[data-sheet-page="'+button.dataset.sheetPage+'"]:not(:disabled)')||section.querySelector('[data-sheet-page]:not(:disabled)');
      target?.focus();
    }
  });
  return {overview,students:()=>view('students'),ledger:()=>view('ledger'),reset};
})();
