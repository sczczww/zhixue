'use strict';

// Both entrances display the same server-recorded comparison and saved plan.
const PlanEvidence = (() => {
  const quantities = value => value == null ? '待核对' : number(value,1);
  const selectedIds = evidence => evidence?.[evidence?.choice]?.courseIds || [];
  const sameCourses = (left,right) => left.length===right.length && left.every(id=>right.includes(id));
  function render(evidence,courseIds=[],preferences=S.ws.planning?.preferences||S.ws.audit?.preferences) {
    if(!evidence?.course || !evidence?.id) {
      return '<p class="plan-evidence-empty">本方案尚未附选课比较，可以结合学生说明与课程检查核对。</p>';
    }
    const matched=sameCourses(selectedIds(evidence),courseIds);
    const pref=preferences||{},before=evidence.preferences||{};
    const samePath=['language','path'].every(k=>pref[k]===before[k]) &&
      sameCourses(pref.advancedModules||[],before.advancedModules||[]) &&
      JSON.stringify(Object.entries(pref.allocations||{}).sort())===JSON.stringify(Object.entries(before.allocations||{}).sort());
    const pathChanged=Boolean(preferences&&evidence.preferences&&!samePath);
    const modes={demo:'模拟开课与课表',mixed:'导入与模拟开课混合',configured:'已导入开课记录',unavailable:'暂无开课记录'};
    const option=(key,label)=>{
      const data=evidence[key],chosen=evidence.choice===key;
      return `<div class="plan-compare-option ${chosen?'is-chosen':''}"><h3>${label}${chosen?'<span>已采纳</span>':''}</h3>
        <p>${data.courseIds.length} 门 · ${quantities(data.credits)} 学分</p>
        <strong>${data.eligible?`预计分类缺口 ${quantities(data.remaining)} 学分`:'有选课约束待处理'}</strong></div>`;
    };
    const issues=[['with','选这门'],['without','暂不选']].map(([key,label])=>{
      const rows=evidence[key].issues||[];
      return `<p><b>${label}</b> · ${rows.length?rows.map(r=>html(r.message)).join('；'):'当时的时段、先修与容量检查通过。'}</p>`;
    }).join('');
    const complete=evidence.coverage?.historyComplete&&evidence.coverage?.enrollmentComplete;
    return `<section class="plan-evidence"><div class="plan-evidence-head"><h2>采纳时的选课比较</h2><span>${html(date(evidence.comparedAt))}</span></div>
      <p class="plan-evidence-course">${html(evidence.course.name)} <span>${html(evidence.course.code)} · ${html(evidence.term)}</span></p>
      <div class="plan-compare-options">${option('with','选这门')}${option('without','暂不选')}</div>
      <p class="plan-match ${matched&&!pathChanged?'':'is-adjusted'}">${pathChanged?'培养路线已调整。这里保留原路线下的比较，请重新核对学分与课程要求。':matched?'当前课程与当时采纳的组合一致。':'当前课程组合已调整。这里保留采纳时的比较，请结合最新组合检查核对。'}</p>
      <details class="plan-evidence-details"><summary>比较依据与计算条件</summary><div>
        <p>${html(evidence.assumption)}</p><p>${evidence.baseKind==='saved'?'以当时已保存的方案':'以当时参考组合'}为基础，其他课程相同。${html(modes[evidence.dataMode]||'按比较时的开课记录')}。</p>
        ${complete?'':'<p>当时的成绩或选课覆盖范围待核对，试算仅采用已导入记录。</p>'}${issues}
        <p>比较时间 ${html(evidence.comparedAt?new Date(evidence.comparedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'未记录')}。最新开课情况和学分认定应继续核对。</p>
      </div></details></section>`;
  }
  function update() {
    const target=document.getElementById('plan-comparison-evidence');
    if(target)target.innerHTML=render(S.ws.planComparison,S.ws.selection);
  }
  function ref(evidence) {
    return evidence?.id?{id:evidence.id,choice:evidence.choice}:null;
  }
  function help(alert,style='btn') {
    const question=`请结合当前预警《${alert.title}》，检查下学期选课风险，说明应优先核实哪些课程，并拟一份待我确认的学习行动计划。`;
    return `<button type="button" class="${style}" data-action="ask" data-student="${html(alert.studentId||S.user.id)}" data-question="${html(question)}">${ico('assistant')}帮我分析处理办法</button>`;
  }
  function history(saved) {
    const events=saved?.events||[];
    return events.slice().reverse().map(e=>{
      const labels={saved:'保存方案',submitted:'提交辅导员',approved:'认可规划',revision:'建议调整',reassigned:'更换负责辅导员'};
      const evidence=e.payload?.comparison;
      return `<div class="event"><small>${html(date(e.createdAt))} · ${html(e.actor)}</small><strong>${html(labels[e.action]||e.action)}</strong>
        ${e.payload?.note?`<p>${html(e.payload.note)}</p>`:''}${e.payload?.comment?`<p>${html(e.payload.comment)}</p>`:''}
        ${e.payload?.courseIds?`<p>本次保存 ${e.payload.courseIds.length} 门课程</p>`:''}
        ${evidence?.id?`<details class="plan-evidence-details"><summary>查看此版本的选课比较</summary>${render(evidence,e.payload.courseIds||[],e.payload.preferences)}</details>`:''}</div>`;
    }).join('')||empty('保存或提交后，会在这里记录方案变化。');
  }
  function courses(saved) {
    const rows=saved.check?.courses||[];
    return `<div class="table-scroll"><table><thead><tr><th>课程</th><th>学分</th><th>上课安排</th></tr></thead><tbody>
      ${rows.map(c=>`<tr><td>${html(c.name)}<small class="table-sub">${html(c.category)} · ${c.required?'必修':'选修'}</small></td><td>${quantities(c.credits)}</td><td>${html(c.scheduleText||'待确认')}</td></tr>`).join('')}
      </tbody></table></div>`;
  }
  function reviewPage(p,student) {
    const saved=p.savedPlan;
    const actions=`<label class="form-item"><span class="a11y-only">规划学期</span><select id="planning-term" aria-label="规划学期">${termChoices(p.term)}</select></label><button class="btn" data-page="submissions">返回方案列表</button><button class="btn" data-action="planner-audit">核对培养要求</button>`;
    const header=heading('学生选课方案',`${student.name} · ${p.term} 学期`,actions);
    if(!saved)return header+'<p class="tip">学生保存选课方案后，会在这里显示课程与说明。</p>';
    const rationale=`<section class="plan-reason"><h2>学生的考虑</h2><p>${html(saved.note||'暂未填写具体说明，可在审核意见中请学生补充。')}</p></section>`+
      render(saved.comparison,saved.courseIds);
    const catalogue=`<details class="plan-review-disclosure"><summary>参考开课目录（${p.offerings.length} 门）</summary>
      <div class="offering-filters"><label class="search">${ico('search')}<input class="field" id="offering-query" placeholder="课程名称或代码" aria-label="搜索开课课程"></label>
      <select id="offering-filter" aria-label="参考课程筛选">${[['selected','本次组合'],['unfinished','未完成课程'],['recommended','推荐课程'],['all','全部开课']].map(([value,label])=>`<option value="${value}" ${value===S.ws.offeringFilter?'selected':''}>${label}</option>`).join('')}</select></div>
      <div id="offering-list"></div><div id="offering-pagination" class="table-bottom"></div></details>`;
    const checks=courses(saved)+`<div class="plan-current-check"><h2>最新组合检查</h2><div id="plan-check-result">${checkMarkup(saved.check)}</div></div>`+catalogue;
    const record=history(saved);
    const sections=window.IndependentUI?
      IndependentUI.panels('review',[['reason','方案与理由',rationale],['courses','课程与检查',checks],['history','审核记录',record]],'方案审核内容'):
      rationale+`<details class="plan-review-disclosure"><summary>课程与最新检查（${saved.courseIds.length} 门）</summary>${checks}</details>
        <details class="plan-review-disclosure"><summary>方案与审核记录</summary>${record}</details>`;
    const feedback=reviewForm(saved,student.id,p.term)||`<section class="plan-review-status"><h2>当前进度</h2><p>${html(planStatus[saved.status]||saved.status)}</p>
      ${saved.reviewComment?`<p>${html(saved.reviewComment)}</p>`:''}</section>`;
    return header+`<div class="plan-review-meta"><strong>${html(saved.title)}</strong><span>第 ${saved.version} 版 · ${html(planStatus[saved.status])} · ${saved.courseIds.length} 门 / ${quantities(saved.check?.totalCredits)} 学分</span></div>`+
      `<div class="plan-review-layout"><div>${sections}</div><aside class="plan-review-feedback">${feedback}</aside></div>`;
  }
  return {render,update,ref,help,history,reviewPage};
})();
