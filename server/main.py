"""HTTP application assembled for Zhixue's independent implementation."""
import hashlib
import hmac
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi import FastAPI,Depends,HTTPException,Request,Response
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .core import ROOT,TERM,initialize,connection,is_demo,current_user,hash_password,require_admin,audit

@asynccontextmanager
async def lifespan(app):
    initialize()
    if is_demo():
        from .seed import ensure_demo
        ensure_demo()
        from .planning import seed_demo_support
        with connection() as db:
            seed_demo_support(db)
    yield

app=FastAPI(title='知学 · 学业支持智能体',version='2.1.0',lifespan=lifespan)
app.mount('/assets',StaticFiles(directory=ROOT/'web'),name='assets')

@app.middleware('http')
async def security(request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('origin'):
        if urlsplit(request.headers['origin']).netloc!=request.headers.get('host'):
            return JSONResponse({'detail':'跨站写入请求已拒绝'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    return response

@app.exception_handler(Exception)
async def unexpected(request,exc):
    logging.exception('Request failed: %s',request.url.path,exc_info=exc)
    return JSONResponse({'detail':'处理失败，请查看服务日志后重试'},status_code=500)

@app.get('/')
def index(): return FileResponse(ROOT/'web/index.html')

@app.get('/favicon.ico')
def favicon(): return Response(status_code=204)

class Login(BaseModel):
    username:str=Field(min_length=1,max_length=80)
    password:str=Field(min_length=1,max_length=200)

login_failures={}

@app.post('/api/login')
def login(body:Login,request:Request,response:Response):
    host=request.client.host if request.client else 'local'
    entries=[t for t in login_failures.get(host,[]) if time.time()-t<300]
    if len(entries)>=30: raise HTTPException(429,'尝试较多，请五分钟后再试')
    with connection() as db:
        row=db.execute('SELECT * FROM users WHERE id=?',(body.username,)).fetchone()
        valid=row and hmac.compare_digest(hash_password(body.password,row['password_hash'].split(':')[0]),row['password_hash'])
        if not valid:
            login_failures[host]=entries+[time.time()]
            raise HTTPException(401,'账号或密码不正确')
        login_failures.pop(host,None)
        token=secrets.token_urlsafe(40)
        db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
        db.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],time.time()+28800))
        audit(db,row['id'],'登录',{'role':row['role']})
    response.set_cookie('zhixue',token,max_age=28800,httponly=True,samesite='strict',secure=request.url.scheme=='https')
    return {'user':{'id':row['id'],'name':row['name'],'role':row['role']},'demo':is_demo()}

@app.get('/api/session')
def session(user=Depends(current_user)): return {'user':user,'demo':is_demo()}

@app.post('/api/logout')
def logout(request:Request,response:Response):
    with connection() as db:
        db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(request.cookies.get('zhixue','').encode()).hexdigest(),))
    response.delete_cookie('zhixue');return {'ok':True}

@app.get('/api/demo-accounts')
def accounts():
    if not is_demo(): raise HTTPException(404)
    with connection() as db:
        rows=db.execute("SELECT id,name,role FROM users WHERE role!='student' OR id IN (SELECT id FROM students ORDER BY id LIMIT 1) OR id IN (SELECT DISTINCT student_id FROM alerts ORDER BY student_id LIMIT 3) ORDER BY CASE role WHEN 'counselor' THEN 0 WHEN 'student' THEN 1 ELSE 2 END,id").fetchall()
    return {'accounts':[dict(r) for r in rows],'password':'demo123'}

@app.get('/api/status')
def status():
    from .assistant import ai_public
    with connection() as db:
        n=db.execute('SELECT COUNT(*) FROM students').fetchone()[0]
    cfg=ai_public()
    return {'service':'zhixue','version':'2.1.0','term':TERM,'students':n,'demo':is_demo(),'ai':{'mode':cfg['mode'],'configured':cfg['hasKey'],'model':cfg['model']}}

@app.get('/api/curriculum')
def curriculum_api(user=Depends(current_user)):
    from .core import curriculum
    return curriculum()

@app.get('/api/sources/{major}')
def source_pdf(major:str,user=Depends(current_user)):
    filenames={'CS':'计算机科学与技术专业人才培养方案.pdf','SE':'软件工程专业（计算机类）人才培养方案.pdf'}
    if major not in filenames: raise HTTPException(404)
    return FileResponse(ROOT/'data/sources'/filenames[major],media_type='application/pdf')

@app.get('/api/admin/audit')
def audits(user=Depends(current_user)):
    require_admin(user)
    with connection() as db:
        rows=db.execute('SELECT a.*,COALESCE(u.name,a.actor_id) AS actor FROM audit a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 100').fetchall()
    return {'items':[{'actor':r['actor'],'action':r['action'],'detail':json.loads(r['detail']),'createdAt':r['created_at']} for r in rows]}

from .api import router as academic_router
from .assistant import router as assistant_router
from .imports import router as imports_router
from .student_actions import router as student_actions_router
from .planning_api import router as planning_router
app.include_router(academic_router)
app.include_router(assistant_router)
app.include_router(imports_router)
app.include_router(student_actions_router)
app.include_router(planning_router)
