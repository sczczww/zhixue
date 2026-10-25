"""Independent curriculum-based academic analysis for the Zhixue prototype.

Academic facts are calculated directly from enrollment and assessment records.
The published policies below are demonstration policies, not university sanctions.
"""
from __future__ import annotations

import json
import math
import uuid
from collections import defaultdict

from . import core, planning, data_quality


LEVEL_NAMES = {1: "轻度预警", 2: "一般预警", 3: "危急预警"}
KIND_NAMES = {"performance": "成绩变化", "completion": "课程通过", "progress": "学分进度", "selection": "选课规划"}
STATUS_NAMES = {"new": "待联系", "contacted": "已联系", "supporting": "帮扶中", "review": "待复查", "closed": "已结案"}
RULES = [
    {"name": "近期成绩偏低", "description": "最近有成绩的学期加权均分低于60分为危急预警，60至不足70分为一般预警；未出分不计零分。", "level": "2 / 3"},
    {"name": "成绩连续下降", "description": "连续三个有成绩的学期绩点均下降，首末差达到0.6，提示轻度关注。", "level": 1},
    {"name": "未通过课程积累", "description": "尚未通过1门课程为轻度预警，2至4门为一般预警，5门及以上为危急预警；重修通过后移出清单。", "level": "1 / 2 / 3"},
    {"name": "必修课漏修漏选", "description": "已到培养方案建议学期，尚未通过且当前未选的必修课：1门轻度关注，2门及以上一般预警。未来课程不提前判漏选。", "level": "1 / 2"},
    {"name": "计划学分滞后", "description": "以前学期应完成的必修课程缺口至少6学分且占比达到15%时一般预警；至少12学分且达到25%时危急预警。", "level": "2 / 3"},
    {"name": "选课负荷偏高", "description": "当前选课超过max(30, (当期必修学分+6)×1.25)，提示一般预警。负荷阈值为项目可讨论的演示策略。", "level": 2},
    {"name": "大三后续负荷评估", "description": "第5学期起，按各模块学分缺口计算剩余每学期需求；超过28学分一般预警，超过34学分危急预警。", "level": "2 / 3"},
    {"name": "毕业阶段模块核对", "description": "第7学期起，核心通识模块数、艺术类和创新创业要求尚有缺口，提示逐项核对；不自动认定毕业资格。", "level": 1},
]


def catalog():
    return json.loads((core.ROOT / "data" / "curriculum.json").read_text(encoding="utf-8"))


def grade_point(score):
    """Continuous 0–4 demonstration GPA; official transcript conversion may differ."""
    return 0.0 if score < 60 else min(4.0, 1.0 + (score - 60) * 3.0 / 40.0)


def semester_of(cohort):
    start, _, half = core.TERM.split("-")
    return max(1, min(8, 2 * (int(start) - int(cohort)) + int(half)))


def _decode(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def alert_object(conn, row):
    row = dict(row)
    student = conn.execute("SELECT s.*, u.name AS owner_name FROM students s LEFT JOIN users u ON u.id=s.counselor_id WHERE s.id=?", (row["student_id"],)).fetchone()
    event = conn.execute("SELECT review_on FROM case_events WHERE alert_id=? AND review_on IS NOT NULL AND review_on!='' ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
    signal_event = conn.execute("SELECT action FROM case_events WHERE alert_id=? AND action IN ('coverage_unconfirmed','risk_cleared','created','reopened') ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
    signal_state = "active" if row["active"] else "unconfirmed" if signal_event and signal_event["action"] == "coverage_unconfirmed" else "cleared"
    return {
        "id": row["id"], "studentId": row["student_id"], "studentName": student["name"],
        "className": student["class_name"], "major": student["major"], "kind": row["kind"],
        "kindName": KIND_NAMES.get(row["kind"], row["kind"]), "level": row["severity"],
        "levelName": LEVEL_NAMES[row["severity"]], "title": row["title"],
        "evidence": _decode(row["evidence"], []), "suggestions": _decode(row["suggestions"], []),
        "status": row["status"], "statusName": STATUS_NAMES.get(row["status"], row["status"]),
        "active": bool(row["active"]), "ownerName": student["owner_name"] or "待分配",
        "signalState": signal_state, "signalStateName": {"active": "当前关注", "unconfirmed": "数据待确认", "cleared": "当前条件未触发"}[signal_state],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        "nextReview": event["review_on"] if event else None,
    }


def _analyze(conn, student):
    """Return independently computed facts and policy signals for one student."""
    student = dict(student)
    program = next((x for x in catalog()["majors"] if x["id"] == student["major"]), None)
    if not program:
        raise ValueError("该专业尚未导入培养方案")
    semester = semester_of(student["cohort"])
    preference = planning.preferences(conn, student["id"])
    offerings = planning.course_catalog(conn, student["major"])
    declared_coverage = data_quality.coverage(conn, student["id"])
    history_complete = declared_coverage["historyComplete"]
    enrollment_complete = declared_coverage["enrollmentComplete"]

    records = [dict(row) for row in conn.execute("SELECT * FROM records WHERE student_id=? AND term<=? ORDER BY term,id", (student["id"], core.TERM))]
    assessments = [r for r in records if r["state"] != "withdrawn" and r["score"] is not None and math.isfinite(float(r["score"]))]
    historical_records = any(r["term"] < core.TERM for r in records)
    historical_grades = any(r["term"] < core.TERM for r in assessments)
    passed_ids = {r["course_id"] for r in assessments if float(r["score"]) >= 60}
    latest = {r["course_id"]: r for r in assessments}
    recognized = dict(latest)
    for assessment in assessments:
        if float(assessment["score"]) >= 60:
            recognized[assessment["course_id"]] = assessment
    pending_failures = {cid: r for cid, r in latest.items() if cid not in passed_ids and float(r["score"]) < 60}
    selected = {r["course_id"] for r in records if r["term"] == core.TERM and r["state"] != "withdrawn"}
    have_selection_data = any(r["term"] == core.TERM for r in records)
    # For credits, one passed course is worth its catalog credits exactly once.
    counted_passed = {cid for cid in passed_ids if cid in offerings and offerings[cid]["meta"].get("language") in (None, preference["language"])}
    earned = sum(offerings[cid]["credits"] for cid in counted_passed)
    total = float(program["totalCredits"])
    categories = planning.category_totals(program, offerings, counted_passed)
    remaining = sum(c["remaining"] for c in categories)
    credited = sum(c["credited"] for c in categories)

    completed = [c for cid, c in offerings.items() if cid in counted_passed]
    curriculum_audit = planning.audit_curriculum(conn, student["id"])
    checks = curriculum_audit["checks"]

    term_records = defaultdict(dict)
    for record in assessments:
        term_records[record["term"]][record["course_id"]] = record
    trend = []
    precise_trend = []
    for term in sorted(term_records):
        rows = [r for cid, r in term_records[term].items() if cid in offerings]
        weight = sum(offerings[r["course_id"]]["credits"] for r in rows)
        if weight:
            mean = sum(float(r["score"]) * offerings[r["course_id"]]["credits"] for r in rows) / weight
            gpa = sum(grade_point(float(r["score"])) * offerings[r["course_id"]]["credits"] for r in rows) / weight
            precise_trend.append({"term": term, "gpa": gpa, "score": mean})
            trend.append({"term": term, "gpa": round(gpa, 2), "score": round(mean, 1)})
    graded_weight = sum(offerings[cid]["credits"] for cid in latest if cid in offerings)
    cumulative_gpa = (sum(grade_point(float(r["score"])) * offerings[cid]["credits"] for cid, r in recognized.items() if cid in offerings) / graded_weight) if graded_weight else None
    selected_credits = sum(offerings[cid]["credits"] for cid in selected if cid in offerings)
    mandatory = [c for c in offerings.values() if planning.applicable_required(c, preference, program)]
    due_before = [c for c in mandatory if 0 < c["semester"] < semester]
    due_now = [c for c in mandatory if 0 < c["semester"] <= semester]
    # Absence of imported history is not proof that every earlier course was missed.
    checkable_due = due_now if history_complete and enrollment_complete else []
    missing = [c for c in checkable_due if c["id"] not in passed_ids and c["id"] not in selected]
    due_credits = sum(c["credits"] for c in due_before)
    due_gap = sum(c["credits"] for c in due_before if c["id"] not in passed_ids)
    planned_load = sum(c["credits"] for c in mandatory if c["semester"] == semester)
    load_limit = max(30.0, (planned_load + 6) * 1.25)
    remaining_terms = max(1, 9 - semester)
    per_term = remaining / remaining_terms
    signals = {}

    def signal(kind, severity, title, label, value, rule, source, advice):
        entry = signals.setdefault(kind, {"severity": 0, "title": title, "evidence": [], "suggestions": []})
        if severity > entry["severity"]:
            entry["severity"], entry["title"] = severity, title
        entry["evidence"].append({"label": label, "value": value, "rule": rule, "source": source})
        if advice not in entry["suggestions"]:
            entry["suggestions"].append(advice)

    graded_term_complete = bool(precise_trend and data_quality.grades_complete_through(conn, student["id"], precise_trend[-1]["term"]))
    if graded_term_complete and precise_trend[-1]["score"] < 70:
        value = precise_trend[-1]["score"]
        signal("performance", 3 if value < 60 else 2, "近期成绩需要关注", "最近学期加权均分", value,
               "低于60分危急预警；60至不足70分一般预警", f"成绩记录 · {trend[-1]['term']}", "先核实成绩完整性，再为薄弱课程安排答疑与学习计划。")
    if graded_term_complete and len(precise_trend) >= 3 and precise_trend[-3]["gpa"] > precise_trend[-2]["gpa"] > precise_trend[-1]["gpa"] and precise_trend[-3]["gpa"] - precise_trend[-1]["gpa"] >= .6 - 1e-10:
        signal("performance", 1, "学习表现连续回落", "三个学期绩点变化", [x["gpa"] for x in precise_trend[-3:]],
               "连续下降且首末差至少0.6", "最近三个有成绩的学期", "和学生一起回顾课程负担与学习方法，约定两周后复查。")
    if pending_failures:
        n = len(pending_failures)
        signal("completion", 3 if n >= 5 else 2 if n >= 2 else 1, "安排未通过课程补修", "尚未通过课程", n,
               "1门轻度；2至4门一般；5门及以上重点", "历史成绩去重，已排除重修通过的课程", "逐门确认补考或重修机会，把课程、时间和负责人写进帮扶计划。")
    if missing and history_complete and enrollment_complete:
        signal("selection", 2 if len(missing) >= 2 else 1, "核对必修课修读安排", "到期未通过且未选课程", [c["name"] for c in missing],
               "达到建议学期才检查；1门轻度，2门及以上一般", f"培养方案课程表 · 当前第{semester}学期", "核实课程是否已替代、缓修或漏选，经教务确认后安排补修。")
    if history_complete and due_credits and due_gap >= 6 and due_gap / due_credits >= .15:
        severity = 3 if due_gap >= 12 and due_gap / due_credits >= .25 else 2
        signal("progress", severity, "必修学分落后课程计划", "往期应修必修学分缺口", round(due_gap, 2),
               f"往期计划{due_credits:g}学分，当前缺口占比{due_gap / due_credits:.0%}", "培养方案建议学期与已通过成绩", "优先保障必修课，核对跨学期重修开课安排。")
    if have_selection_data and selected_credits > load_limit:
        signal("selection", 2, "当前选课负荷偏高", "当前选课学分", round(selected_credits, 2),
               f"超过本学期演示阈值{load_limit:g}学分", "本学期选课记录与培养方案建议负荷", "结合已有薄弱课程，和导师讨论是否调整选课组合。")
    if semester >= 5 and history_complete and per_term > 28:
        signal("progress", 3 if per_term > 34 else 2, "提前规划后续学期学分", "剩余每学期平均需修", round(per_term, 1),
               "超过28学分一般预警；超过34学分危急预警", "各培养模块缺口之和除以剩余学期数", "从大三开始分解剩余模块，优先安排开课机会较少的课程。")
    if semester >= 7 and history_complete:
        unmet = [c["name"] for c in checks if not c["met"]]
        if unmet:
            signal("progress", 1, "逐项核对毕业模块", "尚待补齐项目", unmet,
                   "进入第7学期后逐项提醒", "培养方案毕业学分与模块要求", "请教务确认模块归属和替代关系，不能仅凭总学分判断毕业资格。")

    alerts = [alert_object(conn, r) for r in conn.execute("SELECT * FROM alerts WHERE student_id=? AND term=? ORDER BY severity DESC,created_at DESC", (student["id"], core.TERM))]
    active_alerts = [a for a in alerts if a["active"]]
    risk = max((a["level"] for a in active_alerts), default=0)
    portraits = []
    if pending_failures:
        portraits.append("课程补修")
    if history_complete and due_credits and due_gap / due_credits >= .15:
        portraits.append("学分待追赶")
    if graded_term_complete and len(trend) >= 2 and trend[-1]["gpa"] < trend[-2]["gpa"] - .3:
        portraits.append("成绩回落")
    portrait = " · ".join(portraits[:2]) or ("历史数据待确认" if not history_complete else "学习稳步推进" if assessments else "等待成绩完善")
    counselor = conn.execute("SELECT name FROM users WHERE id=?", (student["counselor_id"],)).fetchone()
    summary = {"id": student["id"], "name": student["name"], "major": student["major"], "majorName": program["name"],
               "cohort": student["cohort"], "className": student["class_name"], "counselorName": counselor["name"] if counselor else "待分配",
               "gpa": round(cumulative_gpa, 2) if cumulative_gpa is not None else None, "earnedCredits": round(earned, 2),
               "totalCredits": total, "riskLevel": risk, "alertCount": len(active_alerts), "portrait": portrait}
    courses = []
    for cid, c in offerings.items():
        record = recognized.get(cid)
        state = "passed" if cid in passed_ids else "failed" if cid in pending_failures else "enrolled" if cid in selected else "remaining"
        courses.append({"id": cid, "code": c["code"], "name": c["name"], "credits": c["credits"], "category": c["category"], "semester": c["semester"],
                        "score": record["score"] if record else None, "state": state, "required": planning.applicable_required(c, preference, program), "sourcePage": c["meta"].get("sourcePage")})
    suggestions = list(dict.fromkeys(a for item in signals.values() for a in item["suggestions"])) or ["保持当前学习节奏，选课前核对培养方案和课程开设学期。"]
    data_notes = []
    if not history_complete:
        data_notes.append("历史成绩尚未声明完整覆盖；即使已有部分成绩，也不能把缺记录当作漏修或真实学分缺口。已获学分为当前记录合计，模块缺口和后续负荷仅作待核对估算。")
        suggestions.insert(0, "先导入并核对历史成绩，再判断往期课程完成情况。")
    if not enrollment_complete:
        data_notes.append("本学期选课未确认完整覆盖，暂不依据未出现的课程判定漏选；已记录的明确超负荷仍可提示。")
    if precise_trend and not graded_term_complete:
        data_notes.append("最近有成绩学期尚未声明完整覆盖，均分和绩点仅描述已导入记录，不作为整学期低分或下降预警。")
    return {"student": summary, "metrics": {"gpa": summary["gpa"], "earnedCredits": round(earned, 2), "failedCourses": len(pending_failures),
            "failedCredits": round(sum(offerings[cid]["credits"] for cid in pending_failures if cid in offerings), 2), "selectedCredits": round(selected_credits, 2),
            "creditProgress": round(credited / total * 100, 1) if total else 0, "plannedCredits": round(due_credits, 2), "creditGap": round(due_gap, 2) if history_complete else None,
            "loadLimit": round(load_limit, 2), "latestScore": trend[-1]["score"] if trend else None, "latestGradedTerm": trend[-1]["term"] if trend else None,
            "currentGradesPending": not any(r["term"] == core.TERM for r in assessments),
            "dataQuality": {"hasAssessments": bool(assessments), "hasHistoricalRecords": historical_records, "hasHistoricalGrades": historical_grades, "hasCurrentEnrollment": have_selection_data, "historyNeedsVerification": not history_complete, "latestGradedTermComplete": graded_term_complete, **declared_coverage},
            "dataNotes": data_notes, "gpaMethod": "演示连续绩点：60分为1.0，100分为4.0；真实接入时使用教务换算规则。"},
            "trend": trend, "credits": {"earned": round(earned, 2), "credited": round(credited, 2), "total": total, "remaining": round(remaining, 2), "categories": categories, "checks": checks, "semester": semester, "preferences": preference, "moduleAudits": curriculum_audit["moduleAudits"], "pathAudit": curriculum_audit["pathAudit"]},
            "courses": courses, "alerts": alerts, "suggestions": suggestions,
            "junior": {"enabled": semester >= 5, "remainingTerms": remaining_terms, "creditsPerTerm": round(per_term, 1) if history_complete else None, "estimatedCreditsPerTerm": round(per_term, 1), "missingCourses": [c["name"] for c in missing],
                       "message": "历史成绩覆盖尚待确认，当前缺口和后续负荷不能作为已确认的学业风险。" if not history_complete else "按模块缺口规划后续学期；个性化路径、课程替代及毕业资格须由教务确认。" if semester >= 5 else "大三起启用后续学期负荷评估，目前可先核对课程计划。"},
            "sources": [f"{program['name']}培养方案 · 学分结构与课程安排", f"学生选课及成绩记录 · 截至{core.TERM}", "项目演示预警政策，非学校处分标准"], "_signals": signals}


def profile(conn, student_id):
    student = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    if student is None:
        return None
    result = _analyze(conn, student)
    result.pop("_signals")
    return result


def _reconcile(conn):
    """Reconcile current academic signals; always preserve human follow-up history."""
    count = created = updated = 0
    students = conn.execute("SELECT * FROM students ORDER BY id").fetchall()
    for student in students:
        count += 1
        planning.sync_plan_owner(conn, student["id"])
        analysis = _analyze(conn, student)
        signals = analysis["_signals"]
        old = {row["kind"]: dict(row) for row in conn.execute("SELECT * FROM alerts WHERE student_id=? AND term=?", (student["id"], core.TERM))}
        for kind, facts in signals.items():
            timestamp = core.now()
            evidence = json.dumps(facts["evidence"], ensure_ascii=False)
            suggestions = json.dumps(facts["suggestions"], ensure_ascii=False)
            previous = old.get(kind)
            notify = False
            if previous:
                alert_id = previous["id"]
                reopened = not previous["active"] or (previous["status"] == "closed" and facts["severity"] > previous["severity"])
                status = "new" if reopened else previous["status"]
                conn.execute("UPDATE alerts SET severity=?,title=?,evidence=?,suggestions=?,status=?,active=1,owner_id=?,updated_at=? WHERE id=?",
                             (facts["severity"], facts["title"], evidence, suggestions, status, student["counselor_id"], timestamp, alert_id))
                updated += 1
                owner_changed = previous["owner_id"] != student["counselor_id"]
                if owner_changed:
                    conn.execute("INSERT INTO notifications(alert_id,owner_id,read_at,created_at) VALUES (?,?,NULL,?)", (alert_id, student["counselor_id"], timestamp))
                    core.audit(conn, "system", "alert.reassign", {"alert": alert_id, "from": previous["owner_id"], "to": student["counselor_id"]})
                if reopened:
                    conn.execute("INSERT INTO case_events(alert_id,actor_id,action,note,plan,review_on,created_at) VALUES (?,?,?,?,?,?,?)",
                                 (alert_id, "system", "reopened", "当前证据显示风险再次出现或等级升高，重新进入联系流程。", "", "", timestamp))
                    notify = True
            else:
                alert_id = "ZX-" + uuid.uuid4().hex[:12].upper()
                conn.execute("INSERT INTO alerts(id,student_id,term,kind,severity,title,evidence,suggestions,status,active,owner_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (alert_id, student["id"], core.TERM, kind, facts["severity"], facts["title"], evidence, suggestions, "new", 1, student["counselor_id"], timestamp, timestamp))
                conn.execute("INSERT INTO case_events(alert_id,actor_id,action,note,plan,review_on,created_at) VALUES (?,?,?,?,?,?,?)",
                             (alert_id, "system", "created", "依据课程与成绩生成预警，已自动分配辅导员并建立跟进记录。", "", "", timestamp))
                created += 1
                notify = True
            if notify:
                for owner in {student["counselor_id"], student["id"]}:
                    if owner:
                        conn.execute("INSERT INTO notifications(alert_id,owner_id,read_at,created_at) VALUES (?,?,NULL,?)", (alert_id, owner, timestamp))
        for kind, previous in old.items():
            if kind not in signals and previous["active"]:
                quality = analysis["metrics"]["dataQuality"]
                confirmed_input = quality["enrollmentComplete"] and quality["historyComplete"] if kind == "selection" else quality["historyComplete"] if kind == "progress" else quality["latestGradedTermComplete"] if kind == "performance" else quality["hasAssessments"]
                if not confirmed_input:
                    conn.execute("UPDATE alerts SET active=0,updated_at=? WHERE id=?", (core.now(), previous["id"]))
                    conn.execute("INSERT INTO case_events(alert_id,actor_id,action,note,plan,review_on,created_at) VALUES (?,?,?,?,?,?,?)", (previous["id"], "system", "coverage_unconfirmed", "数据完整覆盖尚未确认，暂停此项推断；这不代表风险已经恢复，原帮扶记录保留。", "", "", core.now()))
                    updated += 1
                    continue
                timestamp = core.now()
                conn.execute("UPDATE alerts SET active=0,updated_at=? WHERE id=?", (timestamp, previous["id"]))
                conn.execute("INSERT INTO case_events(alert_id,actor_id,action,note,plan,review_on,created_at) VALUES (?,?,?,?,?,?,?)",
                             (previous["id"], "system", "risk_cleared", "当前数据不再命中预警条件；跟进台账保留，是否结案由辅导员复查确认。", "", "", timestamp))
                updated += 1
    active = conn.execute("SELECT COUNT(*) FROM alerts WHERE term=? AND active=1", (core.TERM,)).fetchone()[0]
    result = {"students": count, "activeAlerts": active, "created": created, "updated": updated}
    conn.execute("INSERT INTO audit(actor_id,action,detail,created_at) VALUES (?,?,?,?)", ("system", "academic.recompute", json.dumps(result), core.now()))
    return result


def recompute(conn):
    """Make one complete reconciliation atomic, including initial demo setup."""
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        result = _reconcile(conn)
        if owns_transaction:
            conn.execute("COMMIT")
        return result
    except Exception:
        if owns_transaction:
            conn.execute("ROLLBACK")
        raise
