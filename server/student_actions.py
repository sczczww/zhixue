"""Student-owned action plans and feedback shared with their counselor."""
from datetime import date
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from .core import current_user,connection,visible_student,audit,now,notify

router=APIRouter()

def student_only(user):
    if user['role']!='student':raise HTTPException(403,'请使用学生身份操作个人行动计划')

def tasks(db,sid):
    rows=db.execute("SELECT t.*,u.name AS assigned_name FROM study_tasks t LEFT JOIN users u ON u.id=t.assigned_by WHERE t.student_id=? AND t.archived=0 ORDER BY completed,CASE WHEN due_date='' THEN 1 ELSE 0 END,due_date,id DESC",(sid,)).fetchall()
    return {'tasks':[{'id':r['id'],'title':r['title'],'description':r['description'],'dueDate':r['due_date'],'completed':bool(r['completed']),'alertId':r['alert_id'],'source':r['source'],'assignedBy':r['assigned_by'],'assignedName':r['assigned_name'],'updatedAt':r['updated_at']} for r in rows]}

@router.get('/api/my/plan')
def my_plan(user=Depends(current_user)):
    student_only(user)
    with connection() as db:return tasks(db,user['id'])

@router.get('/api/students/{student_id}/plan')
def student_plan(student_id:str,user=Depends(current_user)):
    with connection() as db:
        visible_student(db,user,student_id)
        return tasks(db,student_id)

class Task(BaseModel):
    title:str=Field(min_length=1,max_length=120)
    dueDate:str=''
    alertId:str|None=None
    description:str=Field(default='',max_length=1500)

@router.post('/api/my/plan')
def create_task(body:Task,user=Depends(current_user)):
    student_only(user)
    if not body.title.strip():raise HTTPException(422,'请填写行动内容')
    if body.dueDate:
        try:date.fromisoformat(body.dueDate)
        except ValueError:raise HTTPException(422,'日期格式应为YYYY-MM-DD')
    with connection() as db:
        if body.alertId and not db.execute('SELECT id FROM alerts WHERE id=? AND student_id=?',(body.alertId,user['id'])).fetchone():raise HTTPException(403,'不能关联他人的预警')
        db.execute('INSERT INTO study_tasks(student_id,alert_id,title,due_date,description,assigned_by,updated_at) VALUES (?,?,?,?,?,?,?)',(user['id'],body.alertId,body.title.strip(),body.dueDate,body.description.strip(),user['id'],now()))
        audit(db,user['id'],'新建学习行动',{'title':body.title})
        return tasks(db,user['id'])

class Completion(BaseModel):
    completed:bool|None=None
    title:str|None=Field(default=None,min_length=1,max_length=120)
    dueDate:str|None=None
    description:str|None=Field(default=None,max_length=1500)

@router.patch('/api/my/plan/{task_id}')
def complete(task_id:int,body:Completion,user=Depends(current_user)):
    student_only(user)
    with connection() as db:
        row=db.execute('SELECT * FROM study_tasks WHERE id=?',(task_id,)).fetchone()
        if not row or row['student_id']!=user['id'] or row['archived']:raise HTTPException(404,'未找到该行动')
        if body.title is not None and not body.title.strip():raise HTTPException(422,'请填写行动内容')
        if body.dueDate:
            try:date.fromisoformat(body.dueDate)
            except ValueError:raise HTTPException(422,'日期格式应为YYYY-MM-DD')
        if row['assigned_by'] not in ('',user['id']) and any(getattr(body,key) is not None for key in ('title','dueDate','description')):
            raise HTTPException(403,'老师安排的内容可反馈进展，调整要求请联系负责老师')
        completed=int(body.completed) if body.completed is not None else row['completed']
        db.execute('UPDATE study_tasks SET completed=?,title=?,due_date=?,description=?,updated_at=? WHERE id=?',(completed,body.title.strip() if body.title is not None else row['title'],body.dueDate if body.dueDate is not None else row['due_date'],body.description.strip() if body.description is not None else row['description'],now(),task_id))
        audit(db,user['id'],'更新学习行动',{'taskId':task_id,'completed':bool(completed)})
        if completed and not row['completed'] and row['assigned_by'] not in ('',user['id']):
            notify(db,row['assigned_by'],'学生已完成：'+row['title'],'study_task',task_id,user['id'])
        return tasks(db,user['id'])

@router.delete('/api/my/plan/{task_id}')
def archive_task(task_id:int,user=Depends(current_user)):
    student_only(user)
    with connection() as db:
        row=db.execute('SELECT * FROM study_tasks WHERE id=? AND student_id=?',(task_id,user['id'])).fetchone()
        if not row or row['archived']:raise HTTPException(404,'未找到该行动')
        if row['assigned_by'] not in ('',user['id']):raise HTTPException(403,'老师安排的行动不能自行移除')
        db.execute('UPDATE study_tasks SET archived=1,updated_at=? WHERE id=?',(now(),task_id))
        audit(db,user['id'],'归档学习行动',{'taskId':task_id})
    return {'ok':True}

@router.post('/api/students/{student_id}/plan')
def assign_task(student_id:str,body:Task,user=Depends(current_user)):
    if user['role'] not in ('counselor','admin'):raise HTTPException(403,'请使用老师身份安排帮扶行动')
    if not body.title.strip():raise HTTPException(422,'请填写行动内容')
    if body.dueDate:
        try:date.fromisoformat(body.dueDate)
        except ValueError:raise HTTPException(422,'日期格式应为YYYY-MM-DD')
    with connection() as db:
        visible_student(db,user,student_id)
        if body.alertId and not db.execute('SELECT id FROM alerts WHERE id=? AND student_id=?',(body.alertId,student_id)).fetchone():raise HTTPException(422,'预警与学生不匹配')
        db.execute('BEGIN IMMEDIATE')
        try:
            task_id=db.execute("INSERT INTO study_tasks(student_id,alert_id,title,due_date,description,assigned_by,source,updated_at) VALUES (?,?,?,?,?,?,'counselor',?)",(student_id,body.alertId,body.title.strip(),body.dueDate,body.description.strip(),user['id'],now())).lastrowid
            notify(db,student_id,'新的帮扶行动：'+body.title.strip(),'study_task',task_id,student_id)
            audit(db,user['id'],'安排帮扶行动',{'studentId':student_id,'taskId':task_id})
            db.execute('COMMIT')
        except Exception:db.execute('ROLLBACK');raise
        return tasks(db,student_id)

class Feedback(BaseModel):
    note:str=Field(min_length=2,max_length=1500)

@router.post('/api/alerts/{alert_id}/feedback')
def feedback(alert_id:str,body:Feedback,user=Depends(current_user)):
    student_only(user)
    if len(body.note.strip())<2:raise HTTPException(422,'请填写具体进展')
    with connection() as db:
        row=db.execute('SELECT * FROM alerts WHERE id=?',(alert_id,)).fetchone()
        if not row or row['student_id']!=user['id']:raise HTTPException(404,'未找到该预警')
        db.execute('BEGIN IMMEDIATE')
        try:
            db.execute('INSERT INTO case_events(alert_id,actor_id,action,note,created_at) VALUES (?,?,?,?,?)',(alert_id,user['id'],'student_feedback',body.note.strip(),now()))
            db.execute("INSERT INTO notifications(alert_id,owner_id,created_at,kind) VALUES (?,?,?,'student_feedback')",(alert_id,row['owner_id'],now()))
            audit(db,user['id'],'提交学业进展',{'alertId':alert_id})
            db.execute('COMMIT')
        except Exception:db.execute('ROLLBACK');raise
    return {'ok':True,'message':'进展已写入帮扶记录，辅导员可在站内通知中查看。'}
