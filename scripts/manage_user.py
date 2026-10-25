"""Provision/reset local accounts with an interactive password, never CLI secrets."""
import argparse
import getpass
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.core import initialize,connection,hash_password,audit

parser=argparse.ArgumentParser()
parser.add_argument('id');parser.add_argument('--name',required=True);parser.add_argument('--role',choices=['student','counselor','admin'],required=True)
args=parser.parse_args()
password=getpass.getpass('设置密码（至少8位）：')
if len(password)<8:raise SystemExit('密码至少8位')
if getpass.getpass('再次输入：')!=password:raise SystemExit('两次密码不一致')
initialize()
with connection() as db:
    old=db.execute('SELECT role FROM users WHERE id=?',(args.id,)).fetchone()
    if old and old['role']!=args.role:raise SystemExit('已有账号角色不同，请勿直接覆盖')
    db.execute('INSERT INTO users VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,password_hash=excluded.password_hash',(args.id,args.name,args.role,hash_password(password)))
    db.execute('DELETE FROM sessions WHERE user_id=?',(args.id,))
    audit(db,'local-admin','设置账号',{'id':args.id,'role':args.role})
print('账号已保存，已有登录会话已失效。')
