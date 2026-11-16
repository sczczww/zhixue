'use strict';
(() => {
  const el = id => document.getElementById(id);
  const frame = el('business');
  const home = CampusRoutes.home;
  const roles = {student:'学生', counselor:'辅导员', admin:'管理员'};
  const requested = () => new URL(location.href).searchParams.get('view') || home;
  let role=null, previewRole=null, current=null, openTabs=[], ready=false;

  function item(tag, text, className) {
    const element=document.createElement(tag);
    if(text!=null)element.textContent=text;
    if(className)element.className=className;
    return element;
  }

  function moduleUrl(view) {
    const url=new URL('/module',location.origin);
    url.searchParams.set('view',view);
    url.searchParams.set('shell','campus');
    return url;
  }

  function send(type, extra={}) {
    frame.contentWindow?.postMessage({channel:CampusRoutes.channel,type,...extra},location.origin);
  }

  function address(view, replace) {
    const url=new URL(location.href);
    if(view===home)url.searchParams.delete('view');
    else url.searchParams.set('view',view);
    if(url.href!==location.href)history[replace?'replaceState':'pushState'](null,'',url);
  }

  function renderTabs() {
    const isHome=current===home;
    el('directory-tab').classList.toggle('selected',isHome);
    if(isHome)el('home-tab').setAttribute('aria-current','page');
    else el('home-tab').removeAttribute('aria-current');
    const strip=el('business-tabs');
    strip.replaceChildren();
    for(const key of openTabs) {
      const entry=CampusRoutes.find(role,key);
      if(!entry)continue;
      const active=key===current;
      const tab=item('div',null,active?'work-tab selected':'work-tab');
      const button=item('button',entry[1]);
      button.onclick=()=>navigate(key);
      if(active)button.setAttribute('aria-current','page');
      const close=item('button','×','tab-close');
      close.setAttribute('aria-label','关闭'+entry[1]);
      close.onclick=()=>{
        const index=openTabs.indexOf(key);
        openTabs=openTabs.filter(view=>view!==key);
        if(active)navigate(openTabs[Math.min(index,openTabs.length-1)] || home);
        else renderTabs();
      };
      tab.append(button,close);
      strip.append(tab);
    }
    el('work-tabs').querySelector('[aria-current="page"]')?.scrollIntoView({block:'nearest',inline:'nearest'});
  }

  function showView(view, replace=false) {
    const entry=view===home?CampusRoutes.homeEntry:CampusRoutes.find(role,view);
    if(!entry)return;
    const initial=current===null;
    current=view;
    if(view!==home&&!openTabs.includes(view))openTabs.push(view);
    document.body.classList.toggle('at-directory',view===home);
    el('crumb-group').textContent=entry[2]===CampusRoutes.projectGroup?'知学':entry[2];
    el('crumb-group').title=entry[2];
    el('crumb-title').textContent=entry[1];
    document.title=entry[1]+' · 知学校园工作台';
    renderTabs();
    address(view,initial||replace);
  }

  function closeSearch() {
    el('service-menu').hidden=true;
    el('menu-shade').hidden=true;
    el('service-search').setAttribute('aria-expanded','false');
  }

  function navigate(view) {
    closeSearch();
    el('service-search').value='';
    if(view!==home&&!CampusRoutes.find(role || previewRole,view))view=home;
    if(!ready) {
      if(view===home) {
        address(home,current===null);
        frame.src=moduleUrl(home).href;
      }
      return;
    }
    send('navigate',{view});
  }

  function showSearch() {
    const list=el('menu-list');
    list.replaceChildren();
    const groups=CampusRoutes.groups(role || previewRole,el('service-search').value);
    for(const [label,entries] of groups) {
      const section=item('section');
      section.append(item('h2',label));
      for(const [id,name,,,url] of entries) {
        if(url) {
          const link=item('a',name+'（教务平台）');
          link.href=url;link.target='_blank';link.rel='noopener noreferrer';
          section.append(link);continue;
        }
        const button=item('button',name,id===current?'selected':null);
        button.onclick=()=>navigate(id);
        section.append(button);
      }
      list.append(section);
    }
    if(!groups.length)list.append(item('p',role||previewRole?'没有找到匹配的服务':'请从全部服务进入。','menu-hint'));
    el('service-menu').hidden=false;
    el('menu-shade').hidden=false;
    el('service-search').setAttribute('aria-expanded','true');
  }

  window.addEventListener('message',event=>{
    const data=event.data;
    if(event.origin!==location.origin||event.source!==frame.contentWindow||data?.channel!==CampusRoutes.channel||data.type!=='state')return;
    const previous=role;
    role=Object.hasOwn(roles,data.role)?data.role:null;
    previewRole=!role&&data.demo&&['student','counselor'].includes(data.previewRole)?data.previewRole:null;
    ready=true;
    if(previous!==role)openTabs=[];
    el('host-mode').textContent=data.demo?'模拟数据':'知学模块';
    el('host-account').textContent=role?roles[role]:'未登录';
    el('host-account').disabled=!role;
    el('host-notices').disabled=!role;
    el('crumb-menu').textContent=role?roles[role]+'全部服务':'全部服务';
    if(data.view===home||(role&&CampusRoutes.find(role,data.view))) {
      showView(data.view,Boolean(previous&&previous!==role));
    } else if(!role) {
      current=null;
      document.body.classList.remove('at-directory');
      el('crumb-group').textContent='学业支持';
      el('crumb-title').textContent='服务入口';
      document.title='校园工作台 · 知学';
      renderTabs();
    }
  });

  for(const id of ['menu-toggle','home-tab','finder-home']) {
    el(id).addEventListener('click',event=>{
      if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
      event.preventDefault();navigate(home);
    });
  }
  el('crumb-menu').onclick=()=>navigate(home);
  el('refresh-view').onclick=()=>{if(role)send('refresh');else frame.src=moduleUrl(requested()).href;};
  el('host-account').onclick=()=>send('account');
  el('host-notices').onclick=()=>send('notifications');
  el('service-search').onfocus=showSearch;
  el('service-search').oninput=showSearch;
  el('service-search').onkeydown=event=>{
    if(event.key==='Enter')el('menu-list').querySelector('button,a')?.click();
    if(event.key==='ArrowDown') {
      event.preventDefault();el('menu-list').querySelector('button,a')?.focus();
    }
  };
  function dismissSearch() {el('service-search').focus();closeSearch();}
  el('menu-close').onclick=dismissSearch;
  el('menu-shade').onclick=closeSearch;
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&!el('service-menu').hidden)dismissSearch();
  });
  window.addEventListener('popstate',()=>navigate(requested()));
  frame.addEventListener('load',()=>send('hello'));
  frame.src=moduleUrl(requested()).href;
})();
