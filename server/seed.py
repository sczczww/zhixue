"""Synthetic cohorts built from the supplied curriculum, with no personal data."""
import json
import random
from .core import connection, initialize, curriculum, add_user, audit, now, TERM

def ensure_demo(count=144):
    initialize()
    with connection() as db:
        if db.execute('SELECT COUNT(*) FROM students').fetchone()[0]: return
        randomizer=random.Random(1022)
        db.execute('BEGIN IMMEDIATE')
        try:
            for uid,name in [('C01','林老师'),('C02','陈老师'),('C03','周老师'),('C04','许老师')]:
                add_user(db,uid,name,'counselor','demo123')
            add_user(db,'admin','管理员','admin','demo123')
            curriculum_by_major={p['id']:p for p in curriculum()['majors']}
            course_lists={}
            for mid,plan in curriculum_by_major.items():
                catalog=[]
                for original in plan['courses']:
                    if original.get('language') not in (None,'en'): continue
                    entry=dict(original)
                    entry['required']=bool(entry['required'] or entry.get('language')=='en')
                    entry['id']=mid+':'+entry['code']
                    catalog.append(entry)
                # The PDFs give module requirements, not an exhaustive university elective catalog.
                # These records are deliberately marked as synthetic course choices.
                for code,title,sem,category,flags in [
                    ('SIM-ART','审美鉴赏',1,'通识',{'generalModule':'艺术','art':True}),
                    ('SIM-SCI','科学探索',2,'通识',{'generalModule':'科学'}),
                    ('SIM-CUL','文化与传承',3,'通识',{'generalModule':'文化'}),
                    ('SIM-SOC','社会观察',4,'通识',{'generalModule':'社会'}),
                    ('SIM-CROSS','跨学科项目',3,'个性化',{}),
                ]:
                    catalog.append({'id':mid+':'+code,'code':code,'name':title+'（模拟）','credits':2,'semester':sem,'module':category,'submodule':'核心通识' if category=='通识' else '自选模块','required':False,'isSimulated':True,'source':'演示课程，并非培养方案原文',**flags})
                course_lists[mid]=catalog
                for c in catalog:
                    db.execute('INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?)',(c['id'],c['code'],c['name'],mid,c['credits'],c['module'],c['semester'],int(c['required']),json.dumps(c,ensure_ascii=False)))
            first_names=['林','陈','李','张','周','徐','王','刘','郑','宋','许','吴']
            last_names=['知远','书宁','雨桐','一诺','景明','若溪','清越','嘉禾','云舒','言蹊','予安','星野']
            for index in range(count):
                mid='CS' if index%2==0 else 'SE'
                cohort=2025 if index%6==5 else 2024
                sid=f'{cohort}{mid}{index+1:03d}'
                name=first_names[index//12%12]+last_names[index%12]
                owner=['C01','C02','C03','C04'][(index//16+index%4)%4]
                add_user(db,sid,name,'student','demo123')
                db.execute('INSERT INTO students VALUES (?,?,?,?,?,?)',(sid,name,mid,cohort,f'{"计科" if mid=="CS" else "软工"}{cohort%100:02d}-{index%3+1}班',owner))
                current_semester=(int(TERM[:4])-cohort)*2+int(TERM[-1])
                scenario=index//2%8
                catalog=course_lists[mid]
                included=[c for c in catalog if c['required'] or c.get('isSimulated') or c.get('innovation')]
                previous=[c for c in included if c['semester']<current_semester]
                failed_count={4:1,5:3,6:5}.get(scenario,0)
                failing={c['id'] for c in previous[-failed_count:]} if failed_count else set()
                for c in included:
                    semester=c['semester']
                    if semester>current_semester: continue
                    if scenario==7 and c['required'] and c['code'][-1] in '0123': continue
                    year=cohort+(semester-1)//2
                    term=f'{year}-{year+1}-{1 if semester%2 else 2}'
                    score=None
                    if semester<current_semester:
                        score=round(min(98,max(65,randomizer.gauss(82,5))),1)
                        if c['id'] in failing: score=round(randomizer.uniform(48,59),1)
                        if index%16 in (14,15): score=round(max(50,94-(semester-1)*10+randomizer.uniform(-2,2)),1)
                    db.execute('INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)',(sid,c['id'],term,score,'enrolled' if score is None else 'completed'))
                electives=[c for c in catalog if c['module']=='个性化' and c['semester']==current_semester and not c.get('innovation') and not c.get('isSimulated')][:2]
                for c in electives:
                    db.execute('INSERT OR IGNORE INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)',(sid,c['id'],TERM,None,'enrolled'))
                from .data_quality import set_coverage, previous_term
                set_coverage(db,sid,'grades',previous_term(TERM),'complete','固定种子生成的完整模拟历史成绩','demo-generator')
                set_coverage(db,sid,'enrollment',TERM,'complete','固定种子生成的完整模拟本期选课','demo-generator')
            audit(db,'system','初始化模拟数据',{'students':count,'seed':1022,'curriculum':'用户提供的两专业PDF','personalData':False})
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK');raise
    from .academic import recompute
    with connection() as db:
        recompute(db)
        # Representative synthetic case history is explicit, never a claimed real intervention.
        rows=db.execute("SELECT id FROM alerts WHERE owner_id='C01' ORDER BY severity DESC LIMIT 3").fetchall()
        for i,row in enumerate(rows):
            path=['contacted','supporting','review'][:i+1]
            for step in path:
                db.execute('INSERT INTO case_events(alert_id,actor_id,action,note,plan,review_on,created_at) VALUES (?,?,?,?,?,?,?)',(row['id'],'C01',step,'演示记录：已核对成绩与选课情况。','每周课程答疑，按清单安排补修。','2026-10-29',now()))
            db.execute('UPDATE alerts SET status=? WHERE id=?',(path[-1],row['id']))
