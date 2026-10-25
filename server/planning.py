"""Source-aware curriculum accounting and a separate, reviewable course planner.

Plans never mutate teaching-system registrations. Timetables and dependencies carry
their own provenance because the supplied PDFs do not establish either of them.
"""
from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict

from . import core, data_quality

LANGUAGES = {"en": "英语", "ja": "日语", "ru": "俄语", "de": "德语"}
PATHS = [
    {"id": "advanced_cross", "name": "进阶 + 专业交叉", "description": "1个专业进阶模块、1个专业交叉模块及至少2学分创新创业实践", "moduleCount": 1},
    {"id": "advanced_free", "name": "进阶 + 自选模块", "description": "1个专业进阶模块、自选模块及至少2学分创新创业实践", "moduleCount": 1},
    {"id": "dual_advanced", "name": "双进阶模块", "description": "2个专业进阶模块及至少2学分创新创业实践", "moduleCount": 2},
]


def initialize(conn):
    # execute rather than executescript: callers may already be in a transaction.
    statements = [
        "CREATE TABLE IF NOT EXISTS curriculum_preferences(student_id TEXT PRIMARY KEY REFERENCES students(id),language TEXT NOT NULL,path TEXT NOT NULL,advanced_modules TEXT NOT NULL,allocations TEXT NOT NULL,updated_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS course_offerings(course_id TEXT NOT NULL REFERENCES courses(id),term TEXT NOT NULL,slots TEXT NOT NULL DEFAULT '[]',capacity INTEGER NOT NULL,enrolled INTEGER NOT NULL DEFAULT 0,available INTEGER NOT NULL DEFAULT 1,is_demo INTEGER NOT NULL DEFAULT 0,source TEXT NOT NULL,PRIMARY KEY(course_id,term))",
        "CREATE TABLE IF NOT EXISTS course_dependencies(course_id TEXT NOT NULL REFERENCES courses(id),prerequisite_id TEXT NOT NULL REFERENCES courses(id),is_demo INTEGER NOT NULL DEFAULT 0,source TEXT NOT NULL,PRIMARY KEY(course_id,prerequisite_id))",
        "CREATE TABLE IF NOT EXISTS course_plans(id TEXT PRIMARY KEY,student_id TEXT NOT NULL REFERENCES students(id),term TEXT NOT NULL,title TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',course_ids TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',review_comment TEXT NOT NULL DEFAULT '',reviewer_id TEXT,submitted_at TEXT,reviewed_at TEXT,updated_at TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,UNIQUE(student_id,term))",
        "CREATE TABLE IF NOT EXISTS plan_events(id INTEGER PRIMARY KEY,plan_id TEXT NOT NULL REFERENCES course_plans(id),actor_id TEXT NOT NULL,action TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL)",
    ]
    for statement in statements:
        conn.execute(statement)
    if "submitted_owner_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(course_plans)")}:
        conn.execute("ALTER TABLE course_plans ADD COLUMN submitted_owner_id TEXT")
    if "preference_snapshot" not in {r["name"] for r in conn.execute("PRAGMA table_info(course_plans)")}:
        conn.execute("ALTER TABLE course_plans ADD COLUMN preference_snapshot TEXT NOT NULL DEFAULT '{}'")


def _json(text, fallback):
    try:
        return json.loads(text) if text else fallback
    except (ValueError, TypeError):
        return fallback


def _program(major):
    return next(p for p in core.curriculum()["majors"] if p["id"] == major)


def _student(conn, student_id):
    row = conn.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    if not row:
        raise ValueError("未找到学生")
    return dict(row)


def validate_term(term):
    match = re.fullmatch(r"(20\d{2})-(20\d{2})-([12])", str(term))
    if not match or int(match[2]) != int(match[1]) + 1:
        raise ValueError("学期格式应为2026-2027-1")
    return str(term)


def semester_for(cohort, term):
    validate_term(term)
    return 2 * (int(term[:4]) - int(cohort)) + int(term[-1])


def next_term(term):
    year = int(term[:4])
    return f"{year}-{year + 1}-2" if term.endswith("1") else f"{year + 1}-{year + 2}-1"


def preferences(conn, student_id):
    row = conn.execute("SELECT * FROM curriculum_preferences WHERE student_id=?", (student_id,)).fetchone()
    if row:
        return {"language": row["language"], "path": row["path"], "advancedModules": _json(row["advanced_modules"], []), "allocations": _json(row["allocations"], {}), "isDefault": False, "updatedAt": row["updated_at"]}
    return {"language": "en", "path": "advanced_free", "advancedModules": [], "allocations": {}, "isDefault": True, "updatedAt": None}


def course_catalog(conn, major):
    reference = {c["code"]: c for c in _program(major)["courses"]}
    result = {}
    for row in conn.execute("SELECT * FROM courses WHERE major=?", (major,)):
        c = dict(row)
        c["meta"] = {**reference.get(c["code"], {}), **_json(c["metadata"], {})}
        result[c["id"]] = c
    return result


_courses = course_catalog  # Compatibility for existing callers; one metadata merger.


def category_totals(program, courses, counted):
    categories = []
    for requirement in program["categoryRequirements"]:
        selected = [courses[cid] for cid in counted if courses[cid]["category"] == requirement["name"]]
        earned = sum(c["credits"] for c in selected)
        subcategories = []
        for sub in requirement.get("subcategories", []):
            subtotal = sum(c["credits"] for c in selected if c["meta"].get("submodule") == sub["name"])
            subcategories.append({"name": sub["name"], "earned": round(subtotal, 2), "required": sub["credits"], "remaining": round(max(0, sub["credits"] - subtotal), 2), "credited": min(subtotal, sub["credits"]), "sourcePage": requirement.get("sourcePage", 3)})
        remaining = sum(s["remaining"] for s in subcategories) if subcategories else max(0, requirement["credits"] - earned)
        credited = sum(s["credited"] for s in subcategories) if subcategories else min(earned, requirement["credits"])
        categories.append({"name": requirement["name"], "earned": round(earned, 2), "required": requirement["credits"], "remaining": round(remaining, 2), "credited": round(credited, 2), "subcategories": subcategories,
                           "unclassifiedCredits": round(max(0, earned - sum(s["earned"] for s in subcategories)), 2) if subcategories else 0})
    return categories


def _passed(conn, student_id, cutoff=core.TERM, strictly_before=False):
    operator = "<" if strictly_before else "<="
    return {r[0] for r in conn.execute(f"SELECT DISTINCT course_id FROM records WHERE student_id=? AND term {operator} ? AND term<=? AND score>=60 AND state!='withdrawn'", (student_id, cutoff, core.TERM))}


def _module_options(course, program):
    names = [course["meta"].get("electiveModule"), *course["meta"].get("sharedModules", [])]
    return [m["id"] for m in program["advancedModules"] if m["name"] in names]


def applicable_required(course, pref, program=None):
    language = course["meta"].get("language")
    if language:
        return language == pref["language"]
    if course["required"]:
        return True
    if course["meta"].get("requiredInModule") and program:
        return bool(set(_module_options(course, program)) & set(pref["advancedModules"]))
    return False


def _eligible_buckets(course, program):
    choices = _module_options(course, program)
    if course["meta"].get("innovation"):
        choices.append("innovation")
    return [*choices, "cross", "free"]


def save_preferences(conn, student_id, language, path, advanced_modules, allocations=None):
    student = _student(conn, student_id)
    program = _program(student["major"])
    if language not in LANGUAGES:
        raise ValueError("请选择英语、日语、俄语或德语路线")
    route = next((p for p in PATHS if p["id"] == path), None)
    modules = {m["id"] for m in program["advancedModules"]}
    if not route or not isinstance(advanced_modules, list) or len(advanced_modules) != len(set(advanced_modules)) or not set(advanced_modules) <= modules:
        raise ValueError("路径或进阶模块无效")
    if len(advanced_modules) != route["moduleCount"]:
        raise ValueError(f"此路径应选择{route['moduleCount']}个进阶模块")
    allocations = allocations or {}
    if not isinstance(allocations, dict):
        raise ValueError("课程分配应为课程ID到单一模块的映射")
    courses = _courses(conn, student["major"])
    for cid, bucket in allocations.items():
        course = courses.get(cid)
        if not course or course["category"] != "个性化" or not isinstance(bucket, str) or bucket not in _eligible_buckets(course, program):
            raise ValueError("课程分配无效，同一课程只能分配到一个可选模块")
        if bucket in modules and bucket not in advanced_modules:
            raise ValueError("课程不能分配到未选择的进阶模块")
    before = preferences(conn, student_id)
    before_value = {"language": before["language"], "path": before["path"], "advancedModules": sorted(before["advancedModules"]), "allocations": before["allocations"]}
    after_value = {"language": language, "path": path, "advancedModules": sorted(advanced_modules), "allocations": allocations}
    changed = before_value != after_value
    conn.execute("INSERT INTO curriculum_preferences VALUES (?,?,?,?,?,?) ON CONFLICT(student_id) DO UPDATE SET language=excluded.language,path=excluded.path,advanced_modules=excluded.advanced_modules,allocations=excluded.allocations,updated_at=excluded.updated_at",
                 (student_id, language, path, json.dumps(advanced_modules), json.dumps(allocations), core.now()))
    if changed:
        for plan in conn.execute("SELECT * FROM course_plans WHERE student_id=? AND term>=? AND status IN ('submitted','approved')", (student_id, core.TERM)).fetchall():
            explanation = "外语或个性化修读偏好已改变，原方案需要重新检查、保存并提交审核。"
            conn.execute("UPDATE course_plans SET status='revision',review_comment=?,reviewer_id=NULL,reviewed_at=NULL,submitted_owner_id=NULL,updated_at=? WHERE id=?", (explanation, core.now(), plan["id"]))
            _event(conn, plan["id"], "system", "preferences_changed", {"fromStatus": plan["status"], "before": before_value, "after": after_value, "previousReview": plan["review_comment"], "note": explanation})
            if hasattr(core, "notify"):
                core.notify(conn, student["counselor_id"], student["name"] + "更改了修读偏好，学期方案已退回重查", "semester_plan", plan["id"], student_id)
    return audit_curriculum(conn, student_id)


def audit_curriculum(conn, student_id):
    student = _student(conn, student_id)
    program = _program(student["major"])
    pref = preferences(conn, student_id)
    courses = _courses(conn, student["major"])
    passed = _passed(conn, student_id)
    # Other language credits remain visible in records but do not silently satisfy
    # the selected language route or inflate this curriculum's awarded total.
    counted = {cid for cid in passed if cid in courses and courses[cid]["meta"].get("language") in (None, pref["language"])}
    categories = category_totals(program, courses, counted)
    core_general = [courses[cid] for cid in counted if courses[cid]["meta"].get("submodule") == "核心通识"]
    rule_pages = {r["id"]: r.get("sourcePage") for r in program["rules"]}
    values = [
        ("核心通识学分", sum(c["credits"] for c in core_general), 8, "general_elective"),
        ("核心通识模块", len({c["meta"].get("generalModule") for c in core_general if c["meta"].get("generalModule")}), 4, "general_elective"),
        ("艺术类学分", sum(c["credits"] for c in core_general if c["meta"].get("art")), 2, "art"),
        (LANGUAGES[pref["language"]] + "路线学分", sum(courses[cid]["credits"] for cid in counted if courses[cid]["meta"].get("language") == pref["language"]), 8, "language"),
    ]
    checks = [{"name": n, "value": round(v, 2), "target": t, "met": v >= t, "sourcePage": rule_pages[key]} for n, v, t, key in values]
    personal = [c for c in courses.values() if c["category"] == "个性化"]
    assigned = {}
    innovation_assigned = 0
    for course in sorted(personal, key=lambda c: (c["semester"], c["id"])):
        cid = course["id"]
        chosen = pref["allocations"].get(cid)
        eligible_modules = [m for m in _module_options(course, program) if m in pref["advancedModules"]]
        if chosen:
            assigned[cid] = chosen
        elif course["meta"].get("innovation") and innovation_assigned < 2:
            assigned[cid] = "innovation"
        elif len(eligible_modules) == 1:
            assigned[cid] = eligible_modules[0]
        elif not eligible_modules:
            assigned[cid] = "cross" if course["meta"].get("crossModule") else "free"
        if cid in counted and assigned.get(cid) == "innovation":
            innovation_assigned += course["credits"]
    module_audits = []
    # Include reference rows even when a course is not in the local teaching catalog.
    imported_ids = {c["code"]: cid for cid, c in courses.items()}
    references = {imported_ids.get(c["code"], student["major"] + ":" + c["code"]): {"id": imported_ids.get(c["code"], student["major"] + ":" + c["code"]), "name": c["name"], "credits": c["credits"], "meta": c} for c in program["courses"]}
    merged = {**references, **courses}
    for module in program["advancedModules"]:
        options = [c for c in merged.values() if module["id"] in _module_options(c, program)]
        mandatory = [c for c in options if c["meta"].get("requiredInModule")]
        obtained = [c for c in options if c["id"] in counted and assigned.get(c["id"]) == module["id"]]
        earned = sum(c["credits"] for c in obtained)
        optional = sum(c["credits"] for c in obtained if not c["meta"].get("requiredInModule"))
        required_allocated = sum(c["credits"] for c in obtained if c["meta"].get("requiredInModule"))
        required_earned = sum(c["credits"] for c in mandatory if c["id"] in counted)
        # Completing a shared prerequisite/mandatory course and allocating its
        # credits are distinct: completion can be recognized without double credit.
        missing = [{"id": c["id"], "name": c["name"], "credits": c["credits"]} for c in mandatory if c["id"] not in counted]
        module_audits.append({"id": module["id"], "name": module["name"], "selected": module["id"] in pref["advancedModules"], "totalRequired": module["credits"], "earned": earned, "remaining": max(0, module["credits"] - earned),
                              "requiredCredits": sum(c["credits"] for c in mandatory), "requiredEarned": required_earned, "requiredAllocatedCredits": required_allocated, "requiredMissing": missing, "optionalRequired": module["optionalCredits"], "optionalEarned": optional,
                              "met": earned >= module["credits"] and optional >= module["optionalCredits"] and not missing, "sourcePages": module["sourcePages"],
                              "courses": [{"id": c["id"], "name": c["name"], "credits": c["credits"], "passed": c["id"] in counted, "requiredInModule": bool(c["meta"].get("requiredInModule")), "allocatedTo": assigned.get(c["id"]), "eligibleModules": _eligible_buckets(c, program)} for c in options]})
    checks.append({"name": "创新创业独立分配学分", "value": innovation_assigned, "target": 2, "met": innovation_assigned >= 2, "sourcePage": rule_pages["innovation"]})
    route = next(p for p in PATHS if p["id"] == pref["path"])
    personal_category = next(c for c in categories if c["name"] == "个性化")
    selected_modules = [m for m in module_audits if m["selected"]]
    known_path_met = len(selected_modules) == route["moduleCount"] and all(m["met"] for m in selected_modules) and innovation_assigned >= 2 and personal_category["remaining"] == 0
    needs_confirmation = route["id"] != "dual_advanced"
    recognition = None
    if needs_confirmation:
        bucket = "cross" if route["id"] == "advanced_cross" else "free"
        prefix = "crossModule" if bucket == "cross" else "freeModule"
        recognised_groups = defaultdict(list)
        for cid in counted:
            course = courses[cid]
            meta = course["meta"]
            if assigned.get(cid) == bucket and meta.get(prefix) and meta.get(prefix + "Verified") is True and meta.get("recognitionSource"):
                recognised_groups[meta[prefix]].append(course)
        for name, group in recognised_groups.items():
            requirements = {float(c["meta"].get(prefix + "RequiredCredits", 0)) for c in group}
            if len(requirements) != 1 or min(requirements) <= 0:
                continue
            requirement = requirements.pop()
            amount = sum(c["credits"] for c in group)
            if amount >= requirement:
                recognition = {"name": name, "earned": amount, "required": requirement, "sources": list({c["meta"]["recognitionSource"] for c in group})}
                needs_confirmation = False
                break
    path_checks = [
        {"name": "已选进阶模块", "value": len(selected_modules), "target": route["moduleCount"], "met": len(selected_modules) == route["moduleCount"], "note": "各模块还须分别满足限选和任选要求"},
        {"name": "已满足进阶模块", "value": sum(m["met"] for m in selected_modules), "target": route["moduleCount"], "met": len(selected_modules) == route["moduleCount"] and all(m["met"] for m in selected_modules), "note": "共享课程只分配一次"},
        {"name": "创新创业实践", "value": innovation_assigned, "target": 2, "met": innovation_assigned >= 2, "note": "分配到创新创业的课程不再重复占用进阶模块学分"},
        {"name": "个性化总学分", "value": personal_category["earned"], "target": personal_category["required"], "met": personal_category["remaining"] == 0, "note": "每门通过课程只计一次"},
    ]
    notes = ["共享课程可手动分配；本系统采用独立学分归属，不把同一课程同时计入两个模块。", "达到此处检查不等于学校正式认定毕业资格。"]
    quality = data_quality.coverage(conn, student_id)
    if not quality["historyComplete"]:
        notes.append("历史成绩尚未确认完整覆盖；以下剩余学分及未完成项目只根据已导入记录列出，不能直接认定为实际缺修。")
    if route["id"] != "dual_advanced":
        path_checks.append({"name": "交叉/自选模块认定", "value": recognition["earned"] if recognition else 0, "target": recognition["required"] if recognition else None, "met": recognition is not None, "note": "；".join(recognition["sources"]) if recognition else "需要年度模块标准与教务认可的课程归属，不能仅按课程名称推定"})
    if needs_confirmation:
        notes.append("专业交叉或自选模块的年度目录、模块完成标准未在所给PDF中完整列出，路径须由教务确认，不自动判定完成。")
    if pref["isDefault"]:
        notes.append("当前暂按英语路线展示，尚未确认个人修读路径。")
    unassigned = [{"id": c["id"], "name": c["name"], "credits": c["credits"], "passed": c["id"] in counted, "eligibleModules": _eligible_buckets(c, program)} for c in personal if c["id"] in counted and c["id"] not in assigned]
    allocatable = [{"id": c["id"], "name": c["name"], "credits": c["credits"], "passed": c["id"] in counted, "eligibleModules": _eligible_buckets(c, program), "allocatedTo": assigned.get(c["id"]), "allocationSource": "manual" if c["id"] in pref["allocations"] else "automatic" if c["id"] in assigned else "unassigned"} for c in personal]
    return {"studentId": student_id, "major": student["major"], "preferences": pref, "languages": [{"id": k, "name": v, "credits": 8, "sourcePage": rule_pages["language"]} for k, v in LANGUAGES.items()], "paths": PATHS,
            "advancedModules": program["advancedModules"], "categories": categories, "checks": checks, "moduleAudits": module_audits,
            "pathAudit": {"id": route["id"], "name": route["name"], "met": known_path_met and not needs_confirmation, "status": "needs_confirmation" if known_path_met and needs_confirmation else "met" if known_path_met else "incomplete", "personalRequired": personal_category["required"], "personalEarned": personal_category["earned"], "innovationEarned": innovation_assigned, "innovationRequired": 2, "checks": path_checks, "recognition": recognition, "notes": notes},
            "unassignedCourses": unassigned, "allocatableCourses": allocatable, "dataQuality": quality, "sources": [{"title": program["source"]["title"], "page": rule_pages["individual_path"]}, {"title": program["source"]["title"], "page": rule_pages["innovation"]}], "countedCourseIds": sorted(counted), "notes": notes}


def seed_demo_support(conn):
    """Insert clearly synthetic scheduling support; never overwrite saved data."""
    if not core.is_demo():
        return
    initialize(conn)
    for program in core.curriculum()["majors"]:
        major = program["id"]
        if not conn.execute("SELECT 1 FROM courses WHERE major=?", (major,)).fetchone():
            continue
        for c in program["courses"]:
            if c.get("language"):
                conn.execute("INSERT OR IGNORE INTO courses VALUES (?,?,?,?,?,?,?,?,?)", (major + ":" + c["code"], c["code"], c["name"], major, c["credits"], c["module"], c["semester"], 0, json.dumps(c, ensure_ascii=False)))
        courses = list(conn.execute("SELECT * FROM courses WHERE major=? ORDER BY semester,required DESC,code", (major,)))
        for term in (core.TERM, next_term(core.TERM)):
            eligible = [c for c in courses if c["semester"] % 2 == int(term[-1]) % 2 or _json(c["metadata"], {}).get("isSimulated")]
            for i, c in enumerate(eligible):
                slots = [{"day": i % 5 + 1, "start": (i // 5) % 6 * 2 + 1, "end": (i // 5) % 6 * 2 + 2, "weeks": list(range(1, 17))}]
                enrolled = conn.execute("SELECT COUNT(*) FROM records WHERE course_id=? AND term=? AND state!='withdrawn'", (c["id"], term)).fetchone()[0]
                conn.execute("INSERT OR IGNORE INTO course_offerings VALUES (?,?,?,?,?,?,?,?)", (c["id"], term, json.dumps(slots), max(80, enrolled + 20), enrolled, 1, 1, "项目模拟开课、容量及课表；不是学校正式教学安排"))
        by_name = {c["name"]: c["id"] for c in courses}
        for later, earlier in [("深度学习", "机器学习导论" if major == "CS" else "机器学习"), ("操作系统", "数据结构")]:
            if later in by_name and earlier in by_name:
                conn.execute("INSERT OR IGNORE INTO course_dependencies VALUES (?,?,?,?)", (by_name[later], by_name[earlier], 1, "演示建议先修关系，仅用于验证规划流程，非校方先修规定"))


def _slots_overlap(a, b):
    for left in a:
        for right in b:
            if left.get("day") == right.get("day") and max(left.get("start", 0), right.get("start", 0)) <= min(left.get("end", 0), right.get("end", 0)) and set(left.get("weeks", range(1, 19))) & set(right.get("weeks", range(1, 19))):
                return True
    return False


def _offerings(conn, student, term):
    pref = preferences(conn, student["id"])
    program = _program(student["major"])
    courses = _courses(conn, student["major"])
    passed = _passed(conn, student["id"])
    prereq_passed = _passed(conn, student["id"], term, strictly_before=True)
    selected = {r[0] for r in conn.execute("SELECT course_id FROM records WHERE student_id=? AND term=? AND state!='withdrawn'", (student["id"], term))}
    rows = {r["course_id"]: dict(r) for r in conn.execute("SELECT o.* FROM course_offerings o JOIN courses c ON c.id=o.course_id WHERE c.major=? AND o.term=?", (student["major"], term))}
    result = []
    for cid, course in courses.items():
        if course["meta"].get("language") not in (None, pref["language"]):
            continue
        row = rows.get(cid)
        if not row:
            continue
        slots = _json(row["slots"], [])
        prereqs = [{"courseId": r["prerequisite_id"], "name": r["name"], "met": r["prerequisite_id"] in prereq_passed, "isDemo": bool(r["is_demo"]), "source": r["source"]} for r in conn.execute("SELECT d.*,c.name FROM course_dependencies d JOIN courses c ON c.id=d.prerequisite_id WHERE d.course_id=?", (cid,))]
        modules = _module_options(course, program)
        required = applicable_required(course, pref, program)
        result.append({"id": cid, "courseId": cid, "code": course["code"], "name": course["name"], "credits": course["credits"], "category": course["category"], "semester": course["semester"], "required": required, "language": course["meta"].get("language"), "moduleId": modules[0] if modules else None,
                       "slots": slots, "scheduleText": "；".join(f"周{'一二三四五六日'[max(1,min(7,int(s.get('day',1))))-1]} 第{s.get('start')}-{s.get('end')}节" for s in slots) or "时段待确认",
                       "capacity": row["capacity"], "enrolled": row["enrolled"], "seats": max(0, row["capacity"] - row["enrolled"]), "available": bool(row["available"]), "isDemo": bool(row["is_demo"]), "source": row["source"], "passed": cid in passed, "selected": cid in selected, "prerequisites": prereqs,
                       "reasons": (["培养方案必修"] if required else []) + (["所选进阶模块"] if set(modules) & set(pref["advancedModules"]) else []) + (["创新创业课程"] if course["meta"].get("innovation") else [])})
    return result


def check_plan(conn, student_id, term, course_ids):
    term = validate_term(term)
    student = _student(conn, student_id)
    if not isinstance(course_ids, list) or any(not isinstance(cid, str) for cid in course_ids) or len(course_ids) > 60:
        raise ValueError("课程ID应为最多60项的列表")
    own_catalog = _courses(conn, student["major"])
    pref = preferences(conn, student_id)
    offers = {o["courseId"]: o for o in _offerings(conn, student, term)}
    conflicts = []
    def add(kind, level, message, ids, source):
        conflicts.append({"kind": kind, "level": level, "message": message, "courseIds": ids, "source": source})
    if term < core.TERM:
        add("past_term", "error", "不能提交已过去学期的选课计划", [], "当前系统学期")
    if len(course_ids) != len(set(course_ids)):
        add("duplicate", "error", "同一课程不能重复加入计划", [], "课程去重规则")
    chosen = []
    excluded = False
    semester = semester_for(student["cohort"], term)
    for cid in dict.fromkeys(course_ids):
        course = offers.get(cid)
        if not course or not course["available"]:
            excluded = True
            known = own_catalog.get(cid)
            if not known:
                message = f"课程标识 {cid} 不在当前专业目录中，请核对课程标识"
                source = "当前专业课程目录"
            elif known["meta"].get("language") not in (None, pref["language"]):
                message = f"{known['name']}（{known['credits']:g}学分）不符合当前{LANGUAGES[pref['language']]}修读路线，请先核对修读偏好"
                source = "当前选定外语路线"
            elif not course:
                message = f"{known['name']}（{known['credits']:g}学分）在{term}尚无已确认开课记录"
                source = "已导入开课记录"
            else:
                message = f"{known['name']}（{known['credits']:g}学分）在{term}标记为暂不开课"
                source = course["source"]
            add("unavailable", "error", message, [cid], source)
            continue
        chosen.append(course)
        if course["seats"] <= 0 and not course["selected"]:
            add("capacity", "error", f"{course['name']} 暂无可用名额", [cid], course["source"])
        for p in course["prerequisites"]:
            if not p["met"]:
                add("prerequisite", "error", f"{course['name']} 的先修课程 {p['name']} 尚无通过记录", [cid, p["courseId"]], p["source"])
        if course["passed"]:
            add("already_passed", "warning", f"{course['name']} 已通过，再次修读不会重复增加学分", [cid], "已通过成绩记录")
        if course["semester"] > semester:
            add("early", "warning", f"{course['name']} 建议第{course['semester']}学期修读，当前为第{semester}学期", [cid], "培养方案建议学期，不是强制开课限制")
        if not course["slots"]:
            add("unknown_schedule", "error", f"{course['name']} 课表待确认，完善时段后才能提交", [cid], course["source"])
    for i, a in enumerate(chosen):
        for b in chosen[i + 1:]:
            if _slots_overlap(a["slots"], b["slots"]):
                add("time", "error", f"{a['name']} 与 {b['name']} 上课时段重叠", [a["courseId"], b["courseId"]], a["source"] + "；" + b["source"])
    total = sum(c["credits"] for c in chosen)
    planned = sum(o["credits"] for o in offers.values() if o["required"] and o["semester"] == semester)
    if total > max(30, (planned + 6) * 1.25):
        add("load", "warning", f"本计划共{total:g}学分，建议与辅导员复核负荷", list(dict.fromkeys(course_ids)), "项目演示负荷策略")
    program = _program(student["major"])
    passed = _passed(conn, student_id)
    quality = data_quality.coverage(conn, student_id)
    missing_required = [{"id": c["id"], "name": c["name"], "credits": c["credits"], "available": c["id"] in offers and offers[c["id"]]["available"]} for c in own_catalog.values() if applicable_required(c, pref, program) and 0 < c["semester"] <= semester and c["id"] not in passed and c["id"] not in course_ids]
    if not quality["historyComplete"]:
        missing_required = []
    if missing_required:
        add("incomplete_plan", "warning", f"还有{len(missing_required)}门到建议学期的必修/限选课未纳入本方案，请与辅导员核对", [c["id"] for c in missing_required], "培养方案与本方案比较；缺少完整历史成绩时仅作为待核对提示")
    eligible = not any(c["level"] == "error" for c in conflicts)
    notes = ["可提交只表示所选组合没有已知阻断，不等于完整学期方案或毕业资格。", "本检查基于当前记录；模拟先修、课表与容量已注明来源。", "保存或获批只代表学业规划意见，不会写入学校教务选课。"]
    if not quality["historyComplete"]:
        notes.insert(0, "历史成绩覆盖未确认，无法判断整份方案是否补齐所有必修；当前只检查所选组合的已知约束。")
    if excluded:
        notes.insert(0, "未确认开课、路线不符或目录中不存在的项未纳入合计；合计为0不表示该课程本身为0学分。")
    return {"totalCredits": round(total, 2), "conflicts": conflicts, "courses": chosen, "eligible": eligible, "complete": eligible and bool(course_ids) and quality["historyComplete"] and not missing_required, "missingRequired": missing_required, "dataQuality": quality, "notes": notes}


def plan_object(conn, row):
    if not row:
        return None
    row = dict(row)
    reviewer = conn.execute("SELECT name FROM users WHERE id=?", (row["reviewer_id"],)).fetchone() if row["reviewer_id"] else None
    ids = _json(row["course_ids"], [])
    events = [{"action": e["action"], "actor": e["actor_name"] or e["actor_id"], "payload": _json(e["payload"], {}), "createdAt": e["created_at"]} for e in conn.execute("SELECT e.*,u.name AS actor_name FROM plan_events e LEFT JOIN users u ON u.id=e.actor_id WHERE e.plan_id=? ORDER BY e.id", (row["id"],))]
    return {"id": row["id"], "studentId": row["student_id"], "term": row["term"], "title": row["title"], "note": row["note"], "courseIds": ids, "status": row["status"], "reviewComment": row["review_comment"], "reviewerName": reviewer["name"] if reviewer else None, "submittedAt": row["submitted_at"], "reviewedAt": row["reviewed_at"], "updatedAt": row["updated_at"], "version": row["version"], "preferences": _json(row.get("preference_snapshot"), {}), "check": check_plan(conn, row["student_id"], row["term"], ids), "events": events}


def get_planning(conn, student_id, term=None):
    term = validate_term(term or core.TERM)
    student = _student(conn, student_id)
    pref = preferences(conn, student_id)
    offerings = _offerings(conn, student, term)
    semester = semester_for(student["cohort"], term)
    candidates = [o for o in offerings if o["available"] and not o["passed"] and o["semester"] <= semester]
    candidates.sort(key=lambda o: (not (o["required"] and o["semester"] <= semester), o["moduleId"] not in pref["advancedModules"], not o["selected"], o["semester"], o["code"]))
    target = max(24, sum(o["credits"] for o in candidates if o["required"] and o["semester"] == semester))
    selected = []
    rejected = []
    total = 0
    for c in candidates:
        if total + c["credits"] > target:
            continue
        checked = check_plan(conn, student_id, term, selected + [c["courseId"]])
        if checked["eligible"]:
            selected.append(c["courseId"])
            total += c["credits"]
        elif c["required"]:
            rejected.append(c["name"])
    recommended = check_plan(conn, student_id, term, selected)
    recommended.update({"courseIds": selected, "reasons": ["优先安排到期未完成必修，再考虑所选进阶模块，避开已知时段、名额和先修冲突。", "这是可行组合建议，不声称全局最优；可手动调整并重新检查。"] + (["以下必修暂未进入组合，请核实开课或先修安排：" + "、".join(rejected)] if rejected else [])})
    modes = {o["isDemo"] for o in offerings}
    mode = "mixed" if len(modes) == 2 else "demo" if True in modes else "configured" if offerings else "unavailable"
    saved = conn.execute("SELECT * FROM course_plans WHERE student_id=? AND term=?", (student_id, term)).fetchone()
    return {"studentId": student_id, "term": term, "preferences": pref, "offerings": offerings, "recommended": recommended, "savedPlan": plan_object(conn, saved), "dataMode": mode, "notes": ["培养方案建议学期和实际开课安排不同；无开课记录的课程不视为可选。", "演示课表、名额和先修由项目配置；真实使用需替换成经核实的教务数据。"]}


def _event(conn, plan_id, actor, action, payload):
    conn.execute("INSERT INTO plan_events(plan_id,actor_id,action,payload,created_at) VALUES (?,?,?,?,?)", (plan_id, actor, action, json.dumps(payload, ensure_ascii=False), core.now()))
    core.audit(conn, actor, "planning." + action, {"planId": plan_id, **payload})


def save_plan(conn, student_id, term, course_ids, title, note, actor):
    check_plan(conn, student_id, term, course_ids)
    old = conn.execute("SELECT * FROM course_plans WHERE student_id=? AND term=?", (student_id, term)).fetchone()
    if old and old["status"] == "submitted":
        raise ValueError("方案已提交，请等待审核意见后再修改")
    plan_id = old["id"] if old else "PLAN-" + uuid.uuid4().hex[:12].upper()
    conn.execute("INSERT INTO course_plans(id,student_id,term,title,note,course_ids,updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(student_id,term) DO UPDATE SET title=excluded.title,note=excluded.note,course_ids=excluded.course_ids,status='draft',review_comment='',reviewer_id=NULL,submitted_at=NULL,reviewed_at=NULL,submitted_owner_id=NULL,updated_at=excluded.updated_at,version=course_plans.version+1", (plan_id, student_id, term, title or term + "学期规划", note or "", json.dumps(course_ids), core.now()))
    snapshot = preferences(conn, student_id)
    conn.execute("UPDATE course_plans SET preference_snapshot=? WHERE id=?", (json.dumps(snapshot, ensure_ascii=False), plan_id))
    _event(conn, plan_id, actor, "saved", {"courseIds": course_ids, "title": title, "note": note, "preferences": snapshot})
    return plan_object(conn, conn.execute("SELECT * FROM course_plans WHERE id=?", (plan_id,)).fetchone())


def submit_plan(conn, student_id, term, actor):
    row = conn.execute("SELECT * FROM course_plans WHERE student_id=? AND term=?", (student_id, validate_term(term))).fetchone()
    if not row:
        raise ValueError("请先保存选课规划")
    if row["status"] == "submitted":
        return plan_object(conn, row)
    if row["status"] == "approved":
        raise ValueError("方案已审核；如需调整请先保存新版本")
    ids = _json(row["course_ids"], [])
    checked = check_plan(conn, student_id, term, ids)
    if not ids or not checked["eligible"]:
        raise ValueError("方案为空或仍有阻断冲突，请检查后再提交")
    student = _student(conn, student_id)
    conn.execute("UPDATE course_plans SET status='submitted',submitted_at=?,updated_at=?,submitted_owner_id=? WHERE id=?", (core.now(), core.now(), student["counselor_id"], row["id"]))
    snapshot = preferences(conn, student_id)
    conn.execute("UPDATE course_plans SET preference_snapshot=? WHERE id=?", (json.dumps(snapshot, ensure_ascii=False), row["id"]))
    _event(conn, row["id"], actor, "submitted", {"courseIds": ids, "preferences": snapshot})
    if hasattr(core, "notify"):
        core.notify(conn, student["counselor_id"], student["name"] + "提交了学期选课规划", "semester_plan", row["id"], student_id)
    return plan_object(conn, conn.execute("SELECT * FROM course_plans WHERE id=?", (row["id"],)).fetchone())


def sync_plan_owner(conn, student_id):
    student = _student(conn, student_id)
    pending = conn.execute("SELECT * FROM course_plans WHERE student_id=? AND status='submitted' AND (submitted_owner_id IS NULL OR submitted_owner_id!=?)", (student_id, student["counselor_id"])).fetchall()
    for row in pending:
        conn.execute("UPDATE course_plans SET submitted_owner_id=?,updated_at=? WHERE id=?", (student["counselor_id"], core.now(), row["id"]))
        _event(conn, row["id"], "system", "reassigned", {"from": row["submitted_owner_id"], "to": student["counselor_id"]})
        if hasattr(core, "notify"):
            core.notify(conn, student["counselor_id"], student["name"] + "的待审选课方案已转交给您", "semester_plan", row["id"], student_id)


def review_plan(conn, student_id, term, status, comment, actor):
    row = conn.execute("SELECT * FROM course_plans WHERE student_id=? AND term=?", (student_id, validate_term(term))).fetchone()
    if not row or row["status"] != "submitted":
        raise ValueError("仅能审核已提交的方案")
    if status not in ("approved", "revision") or len(comment.strip()) < 2:
        raise ValueError("请选择通过或修改，并填写具体审核意见")
    if status == "approved" and not check_plan(conn, student_id, term, _json(row["course_ids"], []))["eligible"]:
        raise ValueError("开课或容量等条件已变化，请退回学生重新检查")
    conn.execute("UPDATE course_plans SET status=?,review_comment=?,reviewer_id=?,reviewed_at=?,updated_at=? WHERE id=?", (status, comment.strip(), actor, core.now(), core.now(), row["id"]))
    _event(conn, row["id"], actor, status, {"comment": comment.strip()})
    if hasattr(core, "notify"):
        core.notify(conn, student_id, "辅导员已反馈学期选课规划", "semester_plan", row["id"], student_id)
    return plan_object(conn, conn.execute("SELECT * FROM course_plans WHERE id=?", (row["id"],)).fetchone())
