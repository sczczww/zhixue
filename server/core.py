"""Storage and server-side identities for the independent Zhixue application."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from fastapi import HTTPException, Request

ROOT=Path(__file__).resolve().parents[1]
TERM=os.getenv('ZHIXUE_TERM','2026-2027-1')

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def db_path():
    return Path(os.getenv('ZHIXUE_DB',str(ROOT/'var/zhixue.sqlite3')))

def is_demo():
    return os.getenv('ZHIXUE_DEMO','1')=='1'

@contextmanager
def connection():
    path=db_path();path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path,timeout=20,isolation_level=None)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    try: yield conn
    finally: conn.close()

def initialize():
    with connection() as conn:
        conn.executescript('''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','counselor','student')),password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS students(id TEXT PRIMARY KEY,name TEXT NOT NULL,major TEXT NOT NULL,cohort INTEGER NOT NULL,class_name TEXT NOT NULL,counselor_id TEXT NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS courses(id TEXT PRIMARY KEY,code TEXT NOT NULL,name TEXT NOT NULL,major TEXT NOT NULL,credits REAL NOT NULL CHECK(credits>0),category TEXT NOT NULL,semester INTEGER NOT NULL,required INTEGER NOT NULL,metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY,student_id TEXT NOT NULL REFERENCES students(id),course_id TEXT NOT NULL REFERENCES courses(id),term TEXT NOT NULL,score REAL CHECK(score IS NULL OR (score>=0 AND score<=100)),state TEXT NOT NULL CHECK(state IN ('enrolled','completed','withdrawn')),UNIQUE(student_id,course_id,term));
CREATE TABLE IF NOT EXISTS alerts(id TEXT PRIMARY KEY,student_id TEXT NOT NULL REFERENCES students(id),term TEXT NOT NULL,kind TEXT NOT NULL,severity INTEGER NOT NULL CHECK(severity BETWEEN 1 AND 3),title TEXT NOT NULL,evidence TEXT NOT NULL,suggestions TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'new',active INTEGER NOT NULL DEFAULT 1,owner_id TEXT NOT NULL REFERENCES users(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(student_id,term,kind));
CREATE TABLE IF NOT EXISTS case_events(id INTEGER PRIMARY KEY,alert_id TEXT NOT NULL REFERENCES alerts(id),actor_id TEXT NOT NULL,action TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',plan TEXT NOT NULL DEFAULT '',review_on TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,alert_id TEXT NOT NULL REFERENCES alerts(id),owner_id TEXT NOT NULL REFERENCES users(id),read_at TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor_id TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS study_tasks(id INTEGER PRIMARY KEY,student_id TEXT NOT NULL REFERENCES students(id),alert_id TEXT REFERENCES alerts(id),title TEXT NOT NULL,due_date TEXT NOT NULL DEFAULT '',completed INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS inbox_messages(id INTEGER PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),student_id TEXT REFERENCES students(id),title TEXT NOT NULL,kind TEXT NOT NULL,entity_id TEXT NOT NULL,read_at TEXT,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS inbox_owner ON inbox_messages(user_id,read_at,created_at);
CREATE INDEX IF NOT EXISTS records_student ON records(student_id,term);
CREATE INDEX IF NOT EXISTS alerts_owner ON alerts(owner_id,active,status);
CREATE INDEX IF NOT EXISTS students_owner ON students(counselor_id);
CREATE UNIQUE INDEX IF NOT EXISTS courses_natural_key ON courses(major,code);
''')
        task_columns = {row['name'] for row in conn.execute('PRAGMA table_info(study_tasks)')}
        for name, definition in {'description': "TEXT NOT NULL DEFAULT ''", 'assigned_by': "TEXT NOT NULL DEFAULT ''", 'source': "TEXT NOT NULL DEFAULT 'self'", 'archived': 'INTEGER NOT NULL DEFAULT 0'}.items():
            if name not in task_columns:
                conn.execute(f'ALTER TABLE study_tasks ADD COLUMN {name} {definition}')
        if 'kind' not in {row['name'] for row in conn.execute('PRAGMA table_info(notifications)')}:
            conn.execute("ALTER TABLE notifications ADD COLUMN kind TEXT NOT NULL DEFAULT 'alert'")
        # Feature migrations are additive; no student records or prior events are replaced.
        from . import planning, assistant, data_quality
        data_quality.initialize(conn)
        planning.initialize(conn)
        assistant.ensure_schema(conn)

def hash_password(password,salt=None):
    salt=salt or secrets.token_hex(16)
    result=hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
    return salt+':'+result

def add_user(conn,user_id,name,role,password):
    conn.execute('INSERT INTO users VALUES (?,?,?,?)',(user_id,name,role,hash_password(password)))

def audit(conn,actor,action,detail):
    conn.execute('INSERT INTO audit(actor_id,action,detail,created_at) VALUES (?,?,?,?)',(actor,action,json.dumps(detail,ensure_ascii=False),now()))

def notify(conn,user_id,title,kind,entity_id,student_id=None):
    """Persist a user-visible message without sending email or external notifications."""
    return conn.execute('INSERT INTO inbox_messages(user_id,student_id,title,kind,entity_id,created_at) VALUES (?,?,?,?,?,?)',
                        (user_id,student_id,title,kind,str(entity_id),now())).lastrowid

def current_user(request:Request):
    token=request.cookies.get('zhixue','')
    with connection() as conn:
        row=conn.execute('SELECT u.id,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
    if not row: raise HTTPException(401,'请先登录')
    return dict(row)

def require_admin(user):
    if user['role']!='admin': raise HTTPException(403,'该操作需要管理员身份')

def visible_student(conn,user,student_id):
    row=conn.execute('SELECT * FROM students WHERE id=?',(student_id,)).fetchone()
    if not row: raise HTTPException(404,'未找到学生')
    if user['role']=='student' and user['id']!=student_id: raise HTTPException(403,'只能查看本人学情')
    if user['role']=='counselor' and row['counselor_id']!=user['id']: raise HTTPException(403,'该学生不在您的负责范围内')
    return dict(row)

def curriculum():
    return json.loads((ROOT/'data/curriculum.json').read_text(encoding='utf-8'))
