/* Host and content share names; the server alone supplies the signed-in role. */
const CampusRoutes = (() => {
  const projectGroup='知学 · 学业预警与学情画像';
  const schoolHome='https://jwxt.zzu.edu.cn/student/home';
  const schoolCompletion=['school-completion','培养方案完成情况','培养方案','s',schoolHome];
  const entries = [
    ['mine','我的学情画像',projectGroup,'s'],['myalerts','我的学业预警',projectGroup,'s'],
    ['riskcheck','下学期选课风险检查',projectGroup,'sca'],
    ['overview','学情总览',projectGroup,'ca'],['students','学生画像',projectGroup,'ca'],
    ['ledger','预警帮扶台账',projectGroup,'ca'],
    ['credits','学分核对明细','培养方案','s'],['reconcile','学分差异核对','培养方案','s'],
    ['path','个人修读路径','培养方案','s'],['curriculum','专业培养方案','培养方案','sca'],
    ['grades','我的成绩','成绩','s'],['planner','学期选课规划','选课','sca'],
    ['plan','我的行动计划','学业帮扶','s'],['assistant','知学助手','学业帮扶','sca'],
    ['submissions','学生选课方案','选课','ca'],['analytics','群体洞察','学业帮扶','ca'],
    ['settings','数据与设置','系统管理','a']
  ];
  const roles = {student:'s',counselor:'c',admin:'a'};
  const home = 'services';
  const homeEntry = [home, '全部服务', '校园工作台'];
  function list(role){
    if(!Object.hasOwn(roles,role))return [];
    return entries.filter(x=>x[3].includes(roles[role])).map(entry=>
      role!=='student'&&entry[0]==='riskcheck'?[entry[0],'学生选课风险检查','选课',entry[3]]:entry);
  }
  function find(role,id){return Object.hasOwn(roles,role)&&id===home?homeEntry:list(role).find(x=>x[0]===id);}
  function groups(role, query='') {
    const term=query.trim().toLocaleLowerCase();
    const order=[projectGroup,'培养方案','选课','成绩','学业帮扶','系统管理'];
    const grouped=new Map(order.map(group=>[group,[]]));
    const services=role==='student'?[schoolCompletion,...list(role)]:list(role);
    for(const entry of services) {
      const [,title,group]=entry;
      if(term&&!(group+title).toLocaleLowerCase().includes(term))continue;
      if(!grouped.has(group))grouped.set(group,[]);
      grouped.get(group).push(entry);
    }
    return [...grouped].filter(([,items])=>items.length);
  }
  function start(role){return role==='student'?'credits':'overview';}
  return {home,homeEntry,schoolHome,projectGroup,list,find,groups,start,channel:'zhixue.campus.v1'};
})();
