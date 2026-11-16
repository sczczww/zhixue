'use strict';
window.CampusModule = (() => {
  const params=new URL(location.href).searchParams;
  const embedded=window.parent!==window, initial=params.get('view');
  const inWorkspace=embedded&&params.get('shell')==='campus';
  let pending=initial, parentOrigin=null, trusted=new Set([location.origin]),demo=false, blocked=false;
  let guestAccounts={}, guestRole='student', guestHome=false, entering=false;
  function broadcast(){
    if(!embedded||!parentOrigin)return;
    parent.postMessage({channel:CampusRoutes.channel,type:'state',role:S.user?.role||null,
      view:S.user?S.page:(guestHome?CampusRoutes.home:null),demo,
      ...(guestHome&&!S.user?{previewRole:guestRole}:{})},parentOrigin);
  }
  function allowed(id){return Boolean(CampusRoutes.find(S.user?.role,id));}
  function entry(){
    const requested=pending;pending=null;
    if(allowed(requested))return requested;
    return inWorkspace?CampusRoutes.home:CampusRoutes.start(S.user?.role);
  }
  function onView(id){
    const title=CampusRoutes.find(S.user?.role,id)?.[1]||'学业支持';document.title=title+' · 知学';
    const nav=$('#standalone-view');if(nav)nav.value=id;
    const url=new URL(location.href);url.searchParams.set('view',id);history.replaceState(history.state,'',url);broadcast();
  }
  function clearViewData(){S.profile=null;S.alerts=[];S.ws.audit=null;CampusViews.audit=null;CampusViews.transcript=null;CampusViews.report=null;CampusRisk.reset();CampusRegisters.reset();}
  function showGuestHome() {
    const available=Object.keys(guestAccounts);
    if(!demo||!available.length||S.user||blocked)return;
    if(!guestAccounts[guestRole])guestRole=available[0];
    pending=CampusRoutes.home;guestHome=true;
    $('#app').innerHTML=`<main class="business-body">${CampusDirectory.render(guestRole,available)}</main>`;
    document.title='全部服务 · 知学';broadcast();
  }
  async function openGuestService(view) {
    const account=guestAccounts[guestRole];
    if(!guestHome||!account||!demo||S.user||entering||!CampusRoutes.find(guestRole,view))return;
    entering=true;pending=view;
    try{await login(account.id,S.demoPassword);}
    catch(error){pending=CampusRoutes.home;toast(error.message);}
    finally{entering=false;}
  }
  document.addEventListener('click',event=>{
    if(!guestHome||S.user||entering)return;
    const role=event.target.closest('[data-directory-role]')?.dataset.directoryRole;
    if(guestAccounts[role]){
      guestRole=role;showGuestHome();
      document.querySelector('[data-directory-role="'+role+'"]')?.focus();
    }
    const choice=event.target.closest('[data-try-service]');
    if(choice)openGuestService(choice.dataset.tryService);
  });
  async function loginUI(){
    S.user=null;guestHome=false;guestAccounts={};clearViewData();
    demo=Boolean(S.status.demo);
    let accounts=[];
    if(demo){try{const d=await request('/api/demo-accounts');accounts=d.accounts||[];S.demoPassword=d.password;}catch{}}
    const student=accounts.find(a=>a.id==='2024CS013')||accounts.find(a=>a.role==='student'),teacher=accounts.find(a=>a.role==='counselor');
    if(student)guestAccounts.student=student;
    if(teacher)guestAccounts.counselor=teacher;
    if((pending===CampusRoutes.home||(inWorkspace&&!pending))&&Object.keys(guestAccounts).length){
      showGuestHome();return;
    }
    broadcast();
    const pick=(a,name,hint,icon)=>a?`<button class="campus-choice" data-action="demo" data-id="${html(a.id)}"><span class="choice-icon">${ico(icon)}</span><span><strong>${name}</strong><small>${hint}</small></span><b aria-hidden="true">›</b></button>`:'';
    $('#app').innerHTML=`<main class="campus-entry"><div class="business-title"><h1>学业支持服务</h1></div><h2>${demo?'选择体验身份':'从教学服务门户进入'}</h2><p>${demo?'这里使用模拟学生与课程记录。选择一个身份，进入对应的业务页面。':'请从已获得接入授权的服务入口打开本模块。'}</p>
      <div class="entry-choices">${pick(student,'学生','查成绩、核对学分、规划选课','curriculum')}${pick(teacher,'辅导员','看预警、查证据、跟进帮扶','students')}</div>
      <a class="campus-link" href="/" target="_top">进入知学原版 ›</a></main>`;
  }
  function frame(){
    guestHome=false;guestAccounts={};clearViewData();
    demo=Boolean(S.demo);$('#app').innerHTML=`${embedded?'':`<header class="solo-bar"><strong>知学 · 学业支持</strong><select id="standalone-view" aria-label="选择业务服务">${[CampusRoutes.homeEntry,...CampusRoutes.list(S.user.role)].map(([key,name])=>`<option value="${key}">${html(name)}</option>`).join('')}</select><button data-action="account">当前身份</button><a href="/campus">校园工作台 ↗</a></header>`}
      <main class="business-body"><span id="crumb" hidden></span><div id="page" class="campus-page"></div></main>`;
    $('#standalone-view')?.addEventListener('change',e=>go(e.target.value));
  }
  async function account(){
    let options='';if(demo){const data=await request('/api/demo-accounts');options=`<div class="demo-choice"><p>切换演示身份</p><div>${demoChoices(data.accounts||[])}</div></div>`;}
    layer('当前身份',`<h2>${html(S.user.name)}</h2><p>${html(S.user.id)} · ${html(roles[S.user.role])}</p>${options}<div class="form-actions">${btn('退出知学','logout','logout')}</div>`,true);
  }
  window.addEventListener('message',e=>{
    if(!embedded||e.source!==window.parent||!trusted.has(e.origin)||e.data?.channel!==CampusRoutes.channel||blocked)return;
    parentOrigin=e.origin;const d=e.data;
    if(d.type==='hello'){broadcast();return;}
    if(!S.user&&inWorkspace&&demo&&d.type==='navigate'&&e.origin===location.origin){
      if(d.view===CampusRoutes.home)showGuestHome();
      else if(guestHome)openGuestService(d.view);
      return;
    }
    if(!S.user||!$('#page'))return;
    if(d.type==='navigate'&&allowed(d.view))go(d.view);
    else if(d.type==='refresh')go(S.page);
    else if(d.type==='notifications')notifications();
    else if(d.type==='account')account().catch(e=>toast(e.message));
  });
  async function start(){
    const ticket=new URLSearchParams(location.hash.slice(1)).get('ticket');
    if(ticket!==null){history.replaceState({launchPending:true},'',location.pathname+location.search);}
    try{
      const config=await request('/api/campus/config');trusted=new Set([location.origin,...config.parentOrigins]);demo=config.demo;
      if(embedded&&document.referrer){const origin=new URL(document.referrer).origin;if(trusted.has(origin))parentOrigin=origin;}
      if(ticket!==null){
        const launch=await request('/api/campus/session',{method:'POST',body:JSON.stringify({ticket})});
        const actual=await request('/api/session');
        if(!actual.user||actual.user.id!==launch.user?.id||actual.user.role!==launch.user?.role)throw new Error('没有建立与门户身份一致的会话，请重新进入。');
        history.replaceState(null,'',location.pathname+location.search);
      }
      else if(history.state?.launchPending)throw new Error('入口凭据未完成验证，请从门户重新进入。');
      await boot();
    }catch(e){blocked=true;S.user=null;$('#app').innerHTML=`<main class="campus-entry" role="alert"><h1>暂时无法进入学业支持服务</h1><p>${html(e.message)}</p><p>请从原服务入口重新打开。</p></main>`;broadcast();}
  }
  return {login:loginUI,frame,entry,onView,allowed,account,start,riskButton:CampusRisk.entryButton,profileBody:CampusPortrait.staff,
    views:{services:()=>CampusDirectory.render(S.user.role,[],demo&&inWorkspace),
      mine:CampusPortrait.mine,overview:CampusRegisters.overview,students:CampusRegisters.students,ledger:CampusRegisters.ledger,
      riskcheck:CampusRisk.view,credits:CampusViews.credits,reconcile:CampusViews.reconcile,grades:CampusViews.grades,path:CampusViews.path,myalerts:CampusViews.myalerts}};
})();
CampusModule.start();
