'use strict';
const CampusDirectory = (() => {
  const audiences={student:'学生服务',counselor:'辅导员服务'};
  const projectEntries={
    mine:['students','查看成绩、学分和修读趋势'],myalerts:['alert','查看预警依据和帮扶进展'],
    riskcheck:['curriculum','核对在读、课程归属和下学期开课'],
    overview:['overview','查看分级预警和待跟进事项'],students:['students','查看所负责学生的学情'],
    ledger:['ledger','记录联系、帮扶和复查结果']
  };

  function serviceButton(entry,preview,featured) {
    const [id,name,,,external]=entry;
    if(external)return `<a class="school-service" href="${html(external)}" target="_blank" rel="noopener noreferrer">${html(name)} <small>教务平台 ↗</small></a><small class="school-menu-path">平台内选择「学生全部服务 › 培养方案」</small>`;
    const attribute=preview?'data-try-service':'data-page';
    if(!featured)return `<button type="button" ${attribute}="${html(id)}">${html(name)}</button>`;
    const [icon,description]=projectEntries[id];
    return `<button type="button" ${attribute}="${html(id)}"><span class="service-symbol">${ico(icon)}</span>
      <span><strong>${html(name)}</strong><small>${html(description)}</small></span></button>`;
  }

  function sections(role, preview, query='') {
    const groups=CampusRoutes.groups(role,query);
    if(!groups.length){
      return `<div class="directory-empty" role="status"><p>没有找到匹配的服务</p><button type="button" data-clear-service-search>显示全部服务</button></div>`;
    }
    return groups.map(([group,items])=>{
      const featured=group===CampusRoutes.projectGroup;
      return `<section class="directory-group${featured?' project-services':''}"><h2>${html(group)}</h2>
        <ul>${items.map(entry=>`<li>${serviceButton(entry,preview,featured)}</li>`).join('')}</ul></section>`;
    }).join('');
  }

  function render(role, previewRoles=[], allowSwitch=false) {
    const preview=previewRoles.length>0;
    const switcher=preview?`<div class="directory-role" role="group" aria-label="选择服务目录">
      ${previewRoles.map(id=>`<button type="button" data-directory-role="${id}" aria-pressed="${id===role}">${audiences[id]}</button>`).join('')}
    </div>`:'';
    return `<section class="service-directory" data-role="${html(role)}" data-preview="${preview}">
      <header class="directory-head"><h1>全部服务</h1>
        <label class="directory-search">${ico('search')}<input type="search" id="directory-search" aria-label="搜索全部服务" placeholder="搜索服务名称" autocomplete="off"></label>
      </header>
      ${switcher}${preview?`<p class="directory-demo-note">选择服务后，将以对应的模拟身份进入。</p>`:''}
      ${allowSwitch?`<div class="directory-session"><span>${html(roles[role])}服务</span><button type="button" data-action="account">切换演示身份</button></div>`:''}
      <div class="directory-groups" id="directory-groups">${sections(role,preview)}</div>
      <footer class="directory-footer"><a href="https://jwxt.zzu.edu.cn/manager/secondary-portal" target="_blank" rel="noopener noreferrer">郑大教学服务平台 ↗</a><a href="/" target="_top">知学原版</a></footer>
    </section>`;
  }

  function filter() {
    const directory=document.querySelector('.service-directory');
    if(!directory)return;
    const query=directory.querySelector('#directory-search').value;
    directory.querySelector('#directory-groups').innerHTML=sections(directory.dataset.role,directory.dataset.preview==='true',query);
  }

  document.addEventListener('input',event=>{if(event.target.id==='directory-search')filter();});
  document.addEventListener('click',event=>{
    if(!event.target.closest('[data-clear-service-search]'))return;
    const search=document.getElementById('directory-search');
    search.value='';filter();search.focus();
  });
  return {render};
})();
