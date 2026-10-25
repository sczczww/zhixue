"""CSV ingestion with explicit row validation and transactional writes."""
import csv
import io
import json
import math
import re
import secrets
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File
from fastapi.responses import Response
from .core import connection,current_user,require_admin,audit,TERM,add_user,is_demo

router=APIRouter()
FIELDS={
 'records':['student_id','course_id','term','score','state'],
 'students':['id','name','major','cohort','class_name','counselor_id'],
 'courses':['id','code','name','major','credits','category','semester','required'],
 'offerings':['course_id','term','slots','capacity','enrolled','available','source'],
 'dependencies':['course_id','prerequisite_id','source'],
 'coverage':['student_id','kind','through_term','status','source'],
}

def number(value,name,lo,hi,integer=False):
    try: n=float(value)
    except (ValueError,TypeError): raise ValueError(name+'须为数字')
    if not math.isfinite(n) or not lo<=n<=hi: raise ValueError(f'{name}须在{lo}至{hi}之间')
    if integer and not n.is_integer(): raise ValueError(name+'须为整数')
    return int(n) if integer else n

def need(row,key):
    value=(row.get(key) or '').strip()
    if not value: raise ValueError('缺少字段 '+key)
    if len(value)>200: raise ValueError(key+'内容过长')
    return value

def valid_term(value):
    match=re.fullmatch(r'(20\d{2})-(20\d{2})-([12])',value)
    if not match or int(match[2])!=int(match[1])+1:raise ValueError('学期格式应为2026-2027-1')
    return value

def parse_slots(value):
    try:slots=json.loads(value or '[]')
    except (TypeError,ValueError):raise ValueError('slots须为JSON数组')
    if not isinstance(slots,list) or len(slots)>30:raise ValueError('slots须为不超过30项的时段数组')
    cleaned=[]
    for slot in slots:
        if not isinstance(slot,dict):raise ValueError('每个课表时段须为对象')
        day=number(slot.get('day'),'星期',1,7,True)
        start=number(slot.get('start'),'起始节次',1,14,True)
        end=number(slot.get('end'),'结束节次',start,14,True)
        weeks=slot.get('weeks',list(range(1,19)))
        if not isinstance(weeks,list) or not weeks:raise ValueError('上课周次须为非空数组，未知课表请将slots设为[]')
        weeks=sorted(set(number(w,'周次',1,30,True) for w in weeks))
        cleaned.append({'day':day,'start':start,'end':end,'weeks':weeks})
    return cleaned

def import_one(db,kind,row,actor='admin-import'):
    if kind=='records':
        sid,cid,term=[need(row,k) for k in ('student_id','course_id','term')]
        valid_term(term)
        student=db.execute('SELECT major FROM students WHERE id=?',(sid,)).fetchone()
        course=db.execute('SELECT major FROM courses WHERE id=?',(cid,)).fetchone()
        if not student or not course: raise ValueError('学生或课程不存在，请先导入基础数据')
        if student['major']!=course['major']: raise ValueError('课程专业与学生不一致，请使用该专业的课程代码')
        score=number(row['score'],'成绩',0,100) if row.get('score','').strip() else None
        state=row.get('state') or ('completed' if score is not None else 'enrolled')
        if state not in ('enrolled','completed','withdrawn'): raise ValueError('state应为enrolled/completed/withdrawn')
        if state=='completed' and score is None: raise ValueError('completed记录必须有成绩，尚未出分请用enrolled')
        exists=db.execute('SELECT id FROM records WHERE student_id=? AND course_id=? AND term=?',(sid,cid,term)).fetchone()
        db.execute('INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?) ON CONFLICT(student_id,course_id,term) DO UPDATE SET score=excluded.score,state=excluded.state',(sid,cid,term,score,state))
    elif kind=='students':
        sid,name,major,cl,owner=[need(row,k) for k in ('id','name','major','class_name','counselor_id')]
        if major not in ('CS','SE'): raise ValueError('major目前支持CS/SE')
        cohort=number(row.get('cohort'),'入学年',2000,2099,True)
        if not db.execute("SELECT id FROM users WHERE id=? AND role='counselor'",(owner,)).fetchone():raise ValueError('辅导员账号不存在')
        account=db.execute('SELECT role FROM users WHERE id=?',(sid,)).fetchone()
        if account and account['role']!='student':raise ValueError('该学号已被其他角色账号占用')
        exists=db.execute('SELECT id,major FROM students WHERE id=?',(sid,)).fetchone()
        if exists and exists['major']!=major and db.execute('SELECT 1 FROM records WHERE student_id=? LIMIT 1',(sid,)).fetchone():
            raise ValueError('该学生已有修读记录，变更专业需先完成课程认定，不能直接覆盖')
        if not account:
            add_user(db,sid,name,'student','demo123' if is_demo() else secrets.token_urlsafe(40))
        else:
            db.execute('UPDATE users SET name=? WHERE id=?',(name,sid))
        db.execute('INSERT INTO students VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,major=excluded.major,cohort=excluded.cohort,class_name=excluded.class_name,counselor_id=excluded.counselor_id',(sid,name,major,cohort,cl,owner))
    elif kind=='courses':
        cid,code,name,major,category=[need(row,k) for k in ('id','code','name','major','category')]
        if major not in ('CS','SE') or category not in ('通识','专业','个性化'):raise ValueError('专业或课程类别无效')
        credits=number(row.get('credits'),'学分',0.1,30)
        semester=number(row.get('semester'),'建议学期',0,8,True)
        required=number(row.get('required'),'必修标记',0,1,True)
        conflict=db.execute('SELECT id FROM courses WHERE major=? AND code=? AND id!=?',(major,code,cid)).fetchone()
        if conflict:raise ValueError('相同专业课程代码已经存在，请使用已有课程id')
        old=db.execute('SELECT metadata,major FROM courses WHERE id=?',(cid,)).fetchone()
        if old and old['major']!=major and db.execute('SELECT 1 FROM records WHERE course_id=? LIMIT 1',(cid,)).fetchone():
            raise ValueError('课程已有修读记录，不能直接变更所属专业')
        exists=bool(old)
        metadata=json.loads(old['metadata']) if old else {'source':'管理员导入，需核实方案适用届别'}
        if row.get('metadata','').strip():
            try:extra=json.loads(row['metadata'])
            except (TypeError,ValueError):raise ValueError('metadata须为JSON对象')
            if not isinstance(extra,dict):raise ValueError('metadata须为JSON对象')
            allowed={'language','submodule','generalModule','art','innovation','crossModule','crossModuleRequiredCredits','crossModuleVerified','freeModule','freeModuleRequiredCredits','freeModuleVerified','recognitionSource'}
            if set(extra)-allowed:raise ValueError('metadata包含不支持的字段')
            for key in ('art','innovation','crossModuleVerified','freeModuleVerified'):
                if key in extra and not isinstance(extra[key],bool):raise ValueError(key+'须为布尔值')
            for key in ('crossModuleRequiredCredits','freeModuleRequiredCredits'):
                if key in extra:extra[key]=number(extra[key],key,1,60)
            if 'language' in extra and extra['language'] not in ('en','ja','ru','de'):raise ValueError('language须为en/ja/ru/de')
            if any(extra.get(key) for key in ('crossModuleVerified','freeModuleVerified')) and not str(extra.get('recognitionSource','')).strip():raise ValueError('认定模块需填写recognitionSource依据')
            metadata.update(extra)
        metadata.update({'code':code,'name':name,'credits':credits,'semester':semester,'module':category,'required':bool(required)})
        db.execute('INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET code=excluded.code,name=excluded.name,major=excluded.major,credits=excluded.credits,category=excluded.category,semester=excluded.semester,required=excluded.required,metadata=excluded.metadata',(cid,code,name,major,credits,category,semester,required,json.dumps(metadata,ensure_ascii=False)))
    elif kind=='offerings':
        cid,term,source=[need(row,k) for k in ('course_id','term','source')]
        valid_term(term)
        if not db.execute('SELECT id FROM courses WHERE id=?',(cid,)).fetchone():raise ValueError('课程不存在，请先导入课程')
        slots=parse_slots(row.get('slots','[]'))
        capacity=number(row.get('capacity'),'容量',0,10000,True)
        enrolled=number(row.get('enrolled'),'已选人数',0,10000,True)
        if enrolled>capacity:raise ValueError('已选人数不能大于容量')
        available=number(row.get('available','1'),'开课标记',0,1,True)
        exists=db.execute('SELECT 1 FROM course_offerings WHERE course_id=? AND term=?',(cid,term)).fetchone()
        db.execute('INSERT INTO course_offerings(course_id,term,slots,capacity,enrolled,available,is_demo,source) VALUES (?,?,?,?,?,?,0,?) ON CONFLICT(course_id,term) DO UPDATE SET slots=excluded.slots,capacity=excluded.capacity,enrolled=excluded.enrolled,available=excluded.available,is_demo=0,source=excluded.source',(cid,term,json.dumps(slots),capacity,enrolled,available,source))
    elif kind=='dependencies':
        cid,prereq,source=[need(row,k) for k in ('course_id','prerequisite_id','source')]
        rows=db.execute('SELECT id,major FROM courses WHERE id IN (?,?)',(cid,prereq)).fetchall()
        if cid==prereq:raise ValueError('课程不能以自身为先修课')
        if len(rows)!=2:raise ValueError('课程或先修课程不存在')
        if len({r['major'] for r in rows})!=1:raise ValueError('请使用同专业的课程ID配置先修关系')
        graph={}
        for row_dep in db.execute('SELECT course_id,prerequisite_id FROM course_dependencies'):
            graph.setdefault(row_dep['course_id'],set()).add(row_dep['prerequisite_id'])
        seen=set();pending=[prereq]
        while pending:
            node=pending.pop()
            if node==cid:raise ValueError('该先修关系会形成循环')
            if node not in seen:seen.add(node);pending.extend(graph.get(node,set()))
        exists=db.execute('SELECT 1 FROM course_dependencies WHERE course_id=? AND prerequisite_id=?',(cid,prereq)).fetchone()
        db.execute('INSERT INTO course_dependencies(course_id,prerequisite_id,is_demo,source) VALUES (?,?,0,?) ON CONFLICT(course_id,prerequisite_id) DO UPDATE SET source=excluded.source,is_demo=0',(cid,prereq,source))
    elif kind=='coverage':
        from .data_quality import set_coverage
        sid,coverage_kind,term,status,source=[need(row,k) for k in FIELDS['coverage']]
        if not db.execute('SELECT 1 FROM students WHERE id=?',(sid,)).fetchone():raise ValueError('学生不存在，请先导入学生')
        if valid_term(term)>TERM:raise ValueError('不能声明未来学期数据已完整')
        exists=db.execute('SELECT 1 FROM data_coverage WHERE student_id=? AND kind=?',(sid,coverage_kind)).fetchone()
        set_coverage(db,sid,coverage_kind,term,status,source,actor)
    else:raise ValueError('未知数据类型')
    return 'updated' if exists else 'inserted'

@router.get('/api/import/template')
def template(type:str='records',user=Depends(current_user)):
    require_admin(user)
    if type not in FIELDS: raise HTTPException(422,'未知数据类型')
    stream=io.StringIO();w=csv.writer(stream);w.writerow(FIELDS[type])
    with connection() as db:
        if type=='records':
            row=db.execute('SELECT student_id,course_id,term,score,state FROM records ORDER BY id LIMIT 1').fetchone()
        elif type=='students':row=db.execute('SELECT id,name,major,cohort,class_name,counselor_id FROM students LIMIT 1').fetchone()
        elif type=='courses':row=db.execute('SELECT id,code,name,major,credits,category,semester,required FROM courses LIMIT 1').fetchone()
        elif type=='offerings':row=db.execute('SELECT course_id,term,slots,capacity,enrolled,available,source FROM course_offerings LIMIT 1').fetchone()
        elif type=='coverage':row=db.execute('SELECT student_id,kind,through_term,status,source FROM data_coverage LIMIT 1').fetchone()
        else:row=db.execute('SELECT course_id,prerequisite_id,source FROM course_dependencies LIMIT 1').fetchone()
    if row:w.writerow(list(row))
    return Response('\ufeff'+stream.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="{type}-template.csv"'})

@router.post('/api/import')
async def upload(type:str='records',file:UploadFile=File(...),user=Depends(current_user)):
    require_admin(user)
    if type not in FIELDS:raise HTTPException(422,'未知数据类型')
    raw=await file.read(5*1024*1024+1)
    if len(raw)>5*1024*1024:raise HTTPException(413,'文件上限5MB')
    try:text=raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:text=raw.decode('gb18030')
        except UnicodeDecodeError:raise HTTPException(422,'请使用UTF-8或GB18030编码CSV')
    rows=list(csv.DictReader(io.StringIO(text)))
    if not rows or len(rows)>10000:raise HTTPException(422,'请上传1至10000行数据')
    report={'inserted':0,'updated':0,'errors':[],'recomputed':False}
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            for index,row in enumerate(rows,2):
                db.execute('SAVEPOINT import_row')
                try:
                    result=import_one(db,type,row,user['id']);report[result]+=1
                    db.execute('RELEASE import_row')
                except (ValueError,KeyError) as exc:
                    db.execute('ROLLBACK TO import_row');db.execute('RELEASE import_row')
                    report['errors'].append({'row':index,'message':str(exc)})
            if report['inserted'] or report['updated']:
                from .academic import recompute
                recompute(db);report['recomputed']=True
            audit(db,user['id'],'导入'+type,{k:v for k,v in report.items() if k!='errors'})
            db.execute('COMMIT')
        except Exception:db.execute('ROLLBACK');raise
    if type=='students':
        report['accountNote']='演示新增学生可用学号和demo123登录。' if is_demo() else '新增学生账号需通过scripts/manage_user.py设置初始密码。'
    return report
