"""Fresh role-scoped HTTP workflows for academic support and follow-up."""
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import academic, core

router = APIRouter()
User = Annotated[dict, Depends(core.current_user)]
TRANSITIONS = {"new": ["contacted"], "contacted": ["supporting"], "supporting": ["review"], "review": ["supporting", "closed"], "closed": []}


def _scope(user, alias="s"):
    if user["role"] == "student":
        return f"{alias}.id=?", [user["id"]]
    if user["role"] == "counselor":
        return f"{alias}.counselor_id=?", [user["id"]]
    return "1=1", []


def _students(conn, user):
    where, values = _scope(user)
    return conn.execute(f"SELECT s.* FROM students s WHERE {where} ORDER BY s.id", values).fetchall()


def _alerts(conn, user):
    where, values = _scope(user)
    rows = conn.execute(f"SELECT a.* FROM alerts a JOIN students s ON s.id=a.student_id WHERE a.term=? AND {where} ORDER BY a.severity DESC,a.updated_at DESC", [core.TERM, *values]).fetchall()
    return [academic.alert_object(conn, row) for row in rows]


def _alert(conn, user, alert_id):
    row = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if not row:
        raise HTTPException(404, "未找到预警记录")
    core.visible_student(conn, user, row["student_id"])
    return row


def _detail(conn, user, alert_id):
    row = _alert(conn, user, alert_id)
    events = conn.execute("SELECT e.*,u.name AS actor_name FROM case_events e LEFT JOIN users u ON u.id=e.actor_id WHERE e.alert_id=? ORDER BY e.id", (alert_id,)).fetchall()
    return {"alert": academic.alert_object(conn, row),
            "events": [{"id": e["id"], "actor": e["actor_name"] or "知学系统", "action": academic.STATUS_NAMES.get(e["action"], {"created": "建立跟进记录", "reopened": "重新关注", "risk_cleared": "风险条件已解除", "coverage_unconfirmed": "覆盖待核对，暂停推断", "student_feedback": "学生反馈"}.get(e["action"], e["action"])),
                        "note": e["note"], "plan": e["plan"], "reviewOn": e["review_on"], "createdAt": e["created_at"]} for e in events],
            "allowedTransitions": [{"value": state, "label": academic.STATUS_NAMES[state]} for state in TRANSITIONS.get(row["status"], [])] if user["role"] != "student" else []}


@router.get("/api/overview")
def overview(user: User):
    with core.connection() as conn:
        students = _students(conn, user)
        alerts = _alerts(conn, user)
        profiles = [academic.profile(conn, s["id"])["student"] for s in students]
        where,params=_scope(user)
        unread_feedback=conn.execute(f"SELECT COUNT(*) FROM notifications n JOIN alerts a ON a.id=n.alert_id JOIN students s ON s.id=a.student_id WHERE n.owner_id=? AND n.kind='student_feedback' AND n.read_at IS NULL AND {where}",[user['id'],*params]).fetchone()[0]
        pending_plans=conn.execute(f"SELECT COUNT(*) FROM course_plans p JOIN students s ON s.id=p.student_id WHERE p.status='submitted' AND {where}",params).fetchone()[0]
    active = [a for a in alerts if a["active"]]
    levels = Counter(a["level"] for a in active)
    distribution = Counter(p["portrait"] for p in profiles)
    today = datetime.now(timezone(timedelta(hours=8))).date()
    weekly = []
    for days_back in reversed(range(7)):
        day = today - timedelta(days=days_back)
        count = 0
        for alert in alerts:
            try:
                created = datetime.fromisoformat(alert["createdAt"]).astimezone(timezone(timedelta(hours=8))).date()
                count += int(created == day)
            except ValueError:
                pass
        weekly.append({"label": day.strftime("%m/%d"), "value": count})
    open_cases=[a for a in alerts if a['status']!='closed']
    due=[a for a in open_cases if a.get('nextReview') and a['nextReview']<=today.isoformat()]
    todo_order=sorted(open_cases,key=lambda a:(0 if a.get('nextReview') and a['nextReview']<=today.isoformat() else 1,-a['level'],a.get('nextReview') or '9999'))
    return {"students": len(students), "activeStudents": len({a["studentId"] for a in active}),
            "alerts": {"urgent": levels[3], "attention": levels[2], "notice": levels[1]},
            "pending": sum(a["status"] == "new" for a in active), "closed": sum(a["status"] == "closed" for a in alerts),
            "distribution": [{"label": label, "value": value} for label, value in distribution.items()], "weekly": weekly,
            "recent": sorted(alerts, key=lambda a: a["updatedAt"], reverse=True)[:6], "todos": todo_order[:8], "term": core.TERM,
            "dueReviews":len(due),"unreadFeedback":unread_feedback,"pendingPlans":pending_plans}


@router.get("/api/students")
def students(user: User, q: str = Query("", max_length=100), major: str = "", risk: str = ""):
    with core.connection() as conn:
        items = [academic.profile(conn, s["id"])["student"] for s in _students(conn, user)]
    if q.strip():
        needle = q.strip().casefold()
        items = [x for x in items if needle in (x["id"] + x["name"] + x["className"]).casefold()]
    if major:
        items = [x for x in items if x["major"] == major]
    if risk:
        level = {"urgent": 3, "attention": 2, "notice": 1, "normal": 0, "none": 0}.get(risk, risk)
        try:
            level = int(level)
        except ValueError:
            raise HTTPException(422, "预警级别应为0、1、2或3")
        items = [x for x in items if x["riskLevel"] == level]
    items.sort(key=lambda x: (-x["riskLevel"], -x["alertCount"], x["id"]))
    return {"items": items, "total": len(items)}


@router.get("/api/students/{student_id}")
def student_detail(student_id: str, user: User):
    with core.connection() as conn:
        core.visible_student(conn, user, student_id)
        return academic.profile(conn, student_id)


@router.get("/api/alerts")
def alerts(user: User, level: str = "", status: str = "", kind: str = "", q: str = Query("", max_length=100)):
    with core.connection() as conn:
        items = _alerts(conn, user)
    if level:
        if level not in ("1", "2", "3"):
            raise HTTPException(422, "预警级别应为1、2或3")
        items = [a for a in items if a["level"] == int(level)]
    if status:
        items = [a for a in items if a["status"] == status]
    if kind:
        items = [a for a in items if a["kind"] == kind]
    if q.strip():
        needle = q.strip().casefold()
        items = [a for a in items if needle in (a["studentId"] + a["studentName"] + a["title"]).casefold()]
    return {"items": items, "total": len(items)}


@router.get("/api/alerts/{alert_id}")
def alert_detail(alert_id: str, user: User):
    with core.connection() as conn:
        return _detail(conn, user, alert_id)


class Followup(BaseModel):
    status: str
    note: str = Field(min_length=1, max_length=3000)
    plan: str = Field(default="", max_length=3000)
    reviewOn: str = Field(default="", max_length=10)


@router.post("/api/alerts/{alert_id}/followup")
def followup(alert_id: str, body: Followup, user: User):
    if user["role"] not in ("counselor", "admin"):
        raise HTTPException(403, "帮扶记录由辅导员填写")
    if not body.note.strip():
        raise HTTPException(422, "请填写本次跟进说明")
    if body.reviewOn:
        try:
            date.fromisoformat(body.reviewOn)
        except ValueError:
            raise HTTPException(422, "复查日期格式应为YYYY-MM-DD")
    with core.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = _alert(conn, user, alert_id)
            if body.status not in TRANSITIONS.get(row["status"], []) and not (body.status==row['status'] and row['status']!='closed'):
                raise HTTPException(409, "该状态变化不符合联系、帮扶、复查、结案的顺序，请刷新后操作")
            stamp = core.now()
            conn.execute("UPDATE alerts SET status=?,updated_at=? WHERE id=?", (body.status, stamp, alert_id))
            conn.execute("INSERT INTO case_events(alert_id,actor_id,action,note,plan,review_on,created_at) VALUES (?,?,?,?,?,?,?)",
                         (alert_id, user["id"], body.status, body.note.strip(), body.plan.strip(), body.reviewOn, stamp))
            core.audit(conn, user["id"], "followup.save", {"alert": alert_id, "from": row["status"], "to": body.status})
            conn.execute("INSERT INTO notifications(alert_id,owner_id,created_at,kind) VALUES (?,?,?,'followup')",(alert_id,row['student_id'],stamp))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return _detail(conn, user, alert_id)


@router.get("/api/notifications")
def notifications(user: User):
    with core.connection() as conn:
        clause, scope_values = _scope(user)
        rows = conn.execute(f"SELECT n.*,a.title,s.name AS student_name FROM notifications n JOIN alerts a ON a.id=n.alert_id JOIN students s ON s.id=a.student_id WHERE n.owner_id=? AND {clause} ORDER BY n.id DESC LIMIT 200", [user["id"], *scope_values]).fetchall()
        messages = conn.execute(f"SELECT m.*,s.name AS student_name FROM inbox_messages m LEFT JOIN students s ON s.id=m.student_id WHERE m.user_id=? AND ({clause}) ORDER BY m.id DESC LIMIT 200", [user['id'],*scope_values]).fetchall()
    items = [{"id": r["id"], "alertId": r["alert_id"], "studentName": r["student_name"], "title": ('学生进展反馈：' if r['kind']=='student_feedback' else '帮扶记录更新：' if r['kind']=='followup' else '')+r["title"], "read": bool(r["read_at"]), "createdAt": r["created_at"],"kind":r['kind'],"entityId":r['alert_id']} for r in rows]
    items.extend({'id':f"msg:{r['id']}",'alertId':None,'studentId':r['student_id'],'studentName':r['student_name'],'title':r['title'],'read':bool(r['read_at']),'createdAt':r['created_at'],'kind':r['kind'],'entityId':r['entity_id']} for r in messages)
    items.sort(key=lambda x:x['createdAt'],reverse=True)
    return {"items": items, "unread": sum(not r["read"] for r in items)}


@router.post("/api/notifications/{notification_id}/read")
def read_notification(notification_id: str, user: User):
    with core.connection() as conn:
        if notification_id.startswith('msg:'):
            numeric_id=notification_id[4:]
            if not numeric_id.isdigit():raise HTTPException(404,'未找到通知')
            message=conn.execute('SELECT * FROM inbox_messages WHERE id=?',(int(numeric_id),)).fetchone()
            if not message:raise HTTPException(404,'未找到通知')
            if message['user_id']!=user['id']:raise HTTPException(403,'这条通知不属于您')
            if message['student_id']:core.visible_student(conn,user,message['student_id'])
            conn.execute('UPDATE inbox_messages SET read_at=COALESCE(read_at,?) WHERE id=?',(core.now(),int(numeric_id)))
            return {'ok':True}
        if not notification_id.isdigit():raise HTTPException(404,'未找到通知')
        notification = conn.execute("SELECT * FROM notifications WHERE id=?", (notification_id,)).fetchone()
        if not notification:
            raise HTTPException(404, "未找到通知")
        if notification["owner_id"] != user["id"]:
            raise HTTPException(403, "这条通知不属于您")
        _alert(conn, user, notification["alert_id"])
        conn.execute("UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=?", (core.now(), notification_id))
    return {"ok": True}


@router.post('/api/notifications/read-all')
def read_all_notifications(user: User):
    items=notifications(user)['items']
    for item in items:
        if not item['read']:read_notification(str(item['id']),user)
    return {'ok':True,'updated':sum(not item['read'] for item in items)}


@router.get("/api/analytics")
def analytics(user: User):
    from .analytics import build_analytics
    with core.connection() as conn:
        profiles = [academic.profile(conn, s["id"]) for s in _students(conn, user)]
        return build_analytics(conn, profiles)


@router.get('/api/analytics/forecast')
def forecast(user: User):
    from .forecast import build_forecast
    with core.connection() as conn:
        return build_forecast(conn, {s['id'] for s in _students(conn,user)})


@router.get("/api/export")
def export(user: User):
    with core.connection() as conn:
        rows = _alerts(conn, user)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["学号", "姓名", "班级", "预警类型", "等级", "当前风险", "跟进状态", "最近说明", "帮扶计划", "复查日期"])
        for row in rows:
            event = conn.execute("SELECT note,plan,review_on FROM case_events WHERE alert_id=? ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            values = [row["studentId"], row["studentName"], row["className"], row["kindName"], row["levelName"], row["signalStateName"], row["statusName"], event["note"] if event else "", event["plan"] if event else "", event["review_on"] if event else ""]
            writer.writerow(["'" + str(x) if str(x).lstrip().startswith(("=", "+", "-", "@")) else x for x in values])
    return Response("\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="zhixue-followup.csv"'})


@router.get("/api/rules")
def rules(user: User):
    return {"rules": academic.RULES, "note": "以上为本项目演示预警政策，不是郑州大学正式学业处分或毕业认定标准。预警用于提供支持。"}


@router.post("/api/recompute")
def recompute(user: User):
    core.require_admin(user)
    with core.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = academic.recompute(conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return result
