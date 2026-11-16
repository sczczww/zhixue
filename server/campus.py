"""School-style module boundary. Trust identities only from our session or an opted-in server handoff."""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from . import academic, core, planning, grading
from .credit_accounting import credit_report

router = APIRouter()
TICKET_LIFETIME = 90


def allowed_parents():
    """Optional exact HTTPS origins, controlled on the server, never by URL parameters."""
    parents = []
    for raw in os.getenv('ZHIXUE_EMBED_ORIGINS', '').split(','):
        raw = raw.strip()
        if not raw:
            continue
        if not re.fullmatch(r'https://[a-zA-Z0-9.-]+(?::[0-9]{1,5})?/?', raw):
            raise ValueError('ZHIXUE_EMBED_ORIGINS 只能填写逗号分隔的完整 HTTPS 来源，不支持路径、通配符或凭据。')
        parsed = urlsplit(raw)
        port = parsed.port  # also rejects invalid port ranges
        if not parsed.hostname or port == 0:
            raise ValueError('不正确的嵌入来源')
        origin = 'https://' + parsed.hostname + (f':{port}' if port and port != 443 else '')
        if origin not in parents:
            parents.append(origin)
    return parents


def frame_headers(path):
    if path != '/module':
        return {'X-Frame-Options':'DENY', 'Content-Security-Policy':"frame-ancestors 'none'"}
    parents = allowed_parents()
    headers = {'Content-Security-Policy':"frame-ancestors 'self'" + ((' ' + ' '.join(parents)) if parents else '')}
    if not parents:
        headers['X-Frame-Options'] = 'SAMEORIGIN'
    return headers


@router.get('/campus', include_in_schema=False)
def host_page():
    return FileResponse(core.ROOT / 'web/campus.html')


@router.get('/module', include_in_schema=False)
def module_page():
    return FileResponse(core.ROOT / 'web/campus-module.html')


@router.get('/api/campus/config')
def module_config():
    return {'protocol':'zhixue.campus.v1', 'features':['services','nextTermRisk','planEvidence','courseAlternatives'], 'gpaPolicy':grading.POLICY_ID, 'parentOrigins':allowed_parents(), 'demo':core.is_demo()}


def install_ticket_schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS campus_launch_tickets (ticket_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires REAL NOT NULL)')


def handoff_key():
    if core.is_public_demo():
        raise HTTPException(404, '共享体验不启用门户换票')
    key = os.getenv('ZHIXUE_CAMPUS_LAUNCH_KEY', '')
    if len(key.encode('utf-8')) < 32:
        raise HTTPException(404, '门户换票未启用')
    return key


class TicketRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    userId: str = Field(min_length=1, max_length=80)


class TicketExchange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    ticket: str = Field(min_length=32, max_length=160)


@router.post('/api/campus/tickets')
def issue_ticket(body:TicketRequest, request:Request):
    key = handoff_key()
    if request.headers.get('origin') or not secrets.compare_digest(request.headers.get('authorization','').encode(), ('Bearer ' + key).encode()):
        raise HTTPException(403, '需要受信任宿主服务端的认证')
    with core.connection() as db:
        user = db.execute('SELECT id,role FROM users WHERE id=?',(body.userId,)).fetchone()
        if not user or user['role'] not in ('student','counselor'):
            raise HTTPException(403, '校园身份未映射到可用的师生账号')
        ticket = secrets.token_urlsafe(40)
        db.execute('DELETE FROM campus_launch_tickets WHERE expires<=?',(time.time(),))
        db.execute('INSERT INTO campus_launch_tickets VALUES (?,?,?)',(hashlib.sha256(ticket.encode()).hexdigest(),user['id'],time.time()+TICKET_LIFETIME))
    return {'ticket':ticket,'expiresIn':TICKET_LIFETIME,'entry':'/module'}


@router.post('/api/campus/session')
def exchange_ticket(body:TicketExchange, request:Request, response:Response):
    handoff_key()
    digest = hashlib.sha256(body.ticket.encode()).hexdigest()
    with core.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            user = db.execute('SELECT u.id,u.name,u.role FROM campus_launch_tickets t JOIN users u ON u.id=t.user_id WHERE t.ticket_hash=? AND t.expires>?',(digest,time.time())).fetchone()
            if not user or user['role'] not in ('student','counselor'):
                raise HTTPException(401, '入口凭据已失效，请重新从门户进入')
            db.execute('DELETE FROM campus_launch_tickets WHERE ticket_hash=?',(digest,))
            core.issue_session(db,request,response,user,'校园门户登录')
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {'user':dict(user),'demo':core.is_demo()}


@router.get('/api/students/{student_id}/transcript')
def transcript(student_id:str, user=Depends(core.current_user)):
    with core.connection() as db:
        db.execute('BEGIN')
        student = core.visible_student(db,user,student_id)
        courses = planning.course_catalog(db, student["major"])
        language = planning.preferences(db,student_id)["language"]
        rows = db.execute('''SELECT r.course_id,r.term,r.score,r.state,c.code,c.name,c.credits,c.category FROM records r JOIN courses c ON c.id=r.course_id
            WHERE r.student_id=? AND r.term<=? AND r.state!='withdrawn' ORDER BY r.term DESC,c.code''',(student_id,core.TERM)).fetchall()
    return {'items':[{**dict(r),'gradePoint':grading.grade_point(r['score']),
                      'gpaScope':grading.gpa_scope(courses.get(r['course_id']), language)} for r in rows],
            'note':'按修读学期展示各次记载成绩，单门绩点按校规分档换算。', 'gpaMethod':grading.METHOD,
            'gpaBands':grading.BANDS, 'gpaSource':grading.SOURCE_URL}




@router.get('/api/students/{student_id}/campus-audit')
def campus_audit(student_id:str,user=Depends(core.current_user)):
    with core.connection() as db:
        core.visible_student(db,user,student_id)
        db.execute('BEGIN')
        p = academic.profile(db,student_id)
        catalog = planning.course_catalog(db,p['student']['major'])
        current = {r[0] for r in db.execute("SELECT course_id FROM records WHERE student_id=? AND term=? AND state='enrolled' AND score IS NULL",(student_id,core.TERM))}
        return {'student':p['student'],'categories':p['credits']['categories'],'checks':p['credits']['checks'], 'pathAudit':p['credits']['pathAudit'],
                'courses':[{**c,'submodule':catalog[c['id']]['meta'].get('submodule') or '其他课程',
                            'appliesToLanguage':catalog[c['id']]['meta'].get('language') in (None,p['credits']['preferences']['language']),
                            'enrolledNow':c['id'] in current} for c in p['courses']],
                'notes':p['metrics']['dataNotes'],'quality':p['metrics']['dataQuality'],'report':credit_report(db,student_id,p,include_trials=True)}
