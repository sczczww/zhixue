"""Next-term screening based on the student's records, curriculum and available offerings."""
import hashlib
import json

from . import academic, core, planning
from .credit_accounting import credit_report


def _current_study(conn, student_id, catalog, language):
    rows = conn.execute("""SELECT c.id,c.code,c.name,c.category,c.credits FROM records r
        JOIN courses c ON c.id=r.course_id WHERE r.student_id=? AND r.term=?
        AND r.state='enrolled' AND r.score IS NULL ORDER BY c.code""", (student_id, core.TERM))
    pending = planning.current_ungraded(conn, student_id)
    result = []
    for record in rows:
        course = dict(record)
        if course["id"] not in pending:
            continue
        entry = catalog.get(course["id"])
        course["inRoute"] = bool(entry and entry["meta"].get("language") in (None, language))
        result.append(course)
    return result


def _assumed_passes(profile, catalog, language, studying):
    passed = {c["id"] for c in profile["courses"] if c["state"] == "passed"
              and catalog[c["id"]]["meta"].get("language") in (None, language)}
    return passed | {c["id"] for c in studying if c["inRoute"]}


def _credit_projection(profile, catalog, program, language, studying):
    applicable = [c for c in studying if c["inRoute"]]
    conditional_passes = _assumed_passes(profile, catalog, language, studying)
    projected = planning.category_totals(program, catalog, conditional_passes)
    by_category = {c["name"]: c for c in projected}
    categories = []
    for actual in profile["credits"]["categories"]:
        name = actual["name"]
        categories.append({
            "name": name, "required": actual["required"], "credited": actual["credited"],
            "remaining": actual["remaining"],
            "studying": round(sum(c["credits"] for c in applicable if c["category"] == name), 2),
            "ifPassedRemaining": by_category[name]["remaining"],
        })
    totals = {
        "required": profile["credits"]["total"], "credited": profile["credits"]["credited"],
        "remaining": profile["credits"]["remaining"],
        "studying": round(sum(c["credits"] for c in applicable), 2),
        "ifPassedRemaining": round(sum(c["ifPassedRemaining"] for c in categories), 2),
        "categories": categories,
    }
    return totals, conditional_passes


def _review_reason(course, current_semester, target_semester, coverage):
    if course["state"] == "failed":
        if not coverage["historyComplete"] or not coverage["enrollmentComplete"]:
            return "已有未通过成绩", "先核对后续通过记录和当前补修情况。"
        if course["required"]:
            return "必修或限选未通过", "优先核对补修机会与先修要求。"
        return "选修未通过", "先看该类缺口，再决定重修或选同类课程。"
    if not course["required"] or course["semester"] <= 0:
        return None
    if course["semester"] <= current_semester and coverage["historyComplete"] and coverage["enrollmentComplete"]:
        return "已到建议学期", "记录中未见通过或在读，先核实替代、缓修或补修安排。"
    if course["semester"] == target_semester:
        return "下学期建议修读", "核对下学期开课、时段及先修条件。"
    return None


def _recognition(accounting, path, studying):
    rows = [{**row, "state":"已通过"} for row in accounting["excluded"]]
    for course in accounting["pendingAllocation"]:
        rows.append({"id":course["id"],"name":course["name"],"credits":course["credits"],
                     "state":"已通过","reason":"共享课程的模块归属待确认"})
    for course in studying:
        if not course["inRoute"]:
            rows.append({**course, "state":"在读","reason":"课程与当前专业目录或外语路线不匹配"})
    check = next((c for c in path["checks"] if c["name"] == "交叉/自选模块认定" and not c["met"]), None)
    return {"courses": rows, "pathNote": check["note"] if check else None}


def next_term_report(conn, student_id, profile=None):
    p = profile or academic.profile(conn, student_id)
    student = p["student"]
    term = planning.next_term(core.TERM)
    semester = planning.semester_for(student["cohort"], core.TERM)
    target_semester = planning.semester_for(student["cohort"], term)
    quality = p["metrics"]["dataQuality"]
    coverage = {key:quality[key] for key in ("historyComplete","enrollmentComplete")}
    language = p["credits"]["preferences"]["language"]
    program = next(m for m in academic.catalog()["majors"] if m["id"] == student["major"])
    catalog = planning.course_catalog(conn, student["major"])
    studying = _current_study(conn, student_id, catalog, language)
    studying_ids = {c["id"] for c in studying}
    credits, conditional_passes = _credit_projection(p, catalog, program, language, studying)
    accounting = credit_report(conn, student_id, p)
    recognition = _recognition(accounting, p["credits"]["pathAudit"], studying)
    plan = planning.get_planning(conn, student_id, term)
    offers = {o["id"]:o for o in plan["offerings"]}
    saved = plan["savedPlan"]
    baseline = saved["check"] if saved else plan["recommended"]
    ids = saved["courseIds"] if saved else baseline["courseIds"]
    priority, upcoming = [], []
    for course in p["courses"]:
        cid = course["id"]
        if catalog[cid]["meta"].get("language") not in (None, language):
            continue
        if cid in studying_ids or course["state"] == "passed":
            continue
        reason = _review_reason(course, semester, target_semester, coverage)
        if not reason:
            continue
        offer = offers.get(cid)
        item = {key:course[key] for key in ("id","code","name","credits","category","required","semester","sourcePage","score")}
        single_trial = planning.category_totals(program, catalog, conditional_passes | {cid})
        remaining_after = sum(c["remaining"] for c in single_trial)
        item.update({"reason":reason[0], "action":reason[1], "inPlan":cid in ids,
                     "additionalIfPassed":round(credits["ifPassedRemaining"] - remaining_after, 2),
                     "offering":{key:offer[key] for key in ("available","seats","scheduleText","source","isDemo")} if offer else None})
        (upcoming if reason[0] == "下学期建议修读" else priority).append(item)
    for rows in (priority, upcoming):
        rows.sort(key=lambda c:(not c["required"], c["semester"], c["code"]))
    alerts = [{key:a[key] for key in ("id","title","level","levelName","status","statusName","ownerName")}
              for a in p["alerts"] if a["active"]]
    regular_terms = int(program["duration"]) * 2
    remaining_terms = regular_terms - semester
    later_load = None
    if 5 <= semester < regular_terms and all(coverage.values()):
        later_load = round(credits["ifPassedRemaining"] / remaining_terms, 1)
    return {
        "student":student, "asOfTerm":core.TERM, "term":term, "semester":semester, "targetSemester":target_semester,
        "coverage":coverage,"dataMode":plan["dataMode"], "credits":credits,"studying":studying,
        "recognition":recognition,"priority":priority,"upcoming":upcoming,"alerts":alerts,
        "junior":{"enabled":5 <= semester <= regular_terms, "remainingTerms":max(0,remaining_terms),"ifPassedAverage":later_load},
        "plan":{"kind":"saved" if saved else "reference","courseIds":ids,"credits":baseline["totalCredits"],
                "status":saved["status"] if saved else None,"version":saved["version"] if saved else 0},
    }


def compare_course(conn, student_id, course_key, report=None, profile=None):
    """Vary one course only. Reuse the ordinary planner for both constraint checks."""
    p = profile or academic.profile(conn, student_id)
    report = report or next_term_report(conn, student_id, p)
    candidates = [c for c in report["priority"] + report["upcoming"] if course_key in (c["id"], c["code"], c["name"])]
    if len(candidates) != 1:
        raise ValueError("请使用检查清单中唯一的课程代码或名称。")
    course = candidates[0]
    plan = report["plan"]
    other_ids = [cid for cid in plan["courseIds"] if cid != course["id"]]
    if len(other_ids) >= 60:
        raise ValueError("现有组合已达60门，请先在学期方案中调整课程。")
    major = p["student"]["major"]
    catalog = planning.course_catalog(conn, major)
    program = next(m for m in academic.catalog()["majors"] if m["id"] == major)
    language = p["credits"]["preferences"]["language"]
    assumed = _assumed_passes(p, catalog, language, report["studying"])

    def option(ids):
        checked = planning.check_plan(conn, student_id, report["term"], ids)
        remaining = None
        if checked["eligible"]:
            totals = planning.category_totals(program, catalog, assumed | {c["id"] for c in checked["courses"]})
            remaining = round(sum(c["remaining"] for c in totals), 2)
        return {"courseIds":ids,"credits":checked["totalCredits"],"eligible":checked["eligible"],
                "remaining":remaining,"missingRequired":len(checked["missingRequired"]),
                "issues":[issue for issue in checked["conflicts"] if issue["kind"] != "incomplete_plan"]}

    with_course = option(other_ids + [course["id"]])
    without_course = option(other_ids)
    gain = None
    if with_course["remaining"] is not None and without_course["remaining"] is not None:
        gain = round(without_course["remaining"] - with_course["remaining"], 2)
    comparison = {
        "course":course, "term":report["term"], "asOfTerm":report["asOfTerm"],
        "baseKind":plan["kind"], "baseVersion":plan["version"], "baseStatus":plan["status"],
        "with":with_course, "without":without_course, "gain":gain,
        "coverage":report["coverage"], "dataMode":report["dataMode"],
        "preferences":p["credits"]["preferences"],
        "assumption":"按比较时的记录，假设本学期在读课程与方案课程全部通过，按培养类别核算缺口。",
    }
    # Include the student's identity and calculation inputs, not client-supplied totals.
    inputs = {"studentId":student_id,"comparison":comparison,"courses":p["courses"],"studying":report["studying"]}
    comparison["fingerprint"] = hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return comparison


def remember_comparison(conn, student_id, course_key, fingerprint):
    comparison = compare_course(conn, student_id, course_key)
    if comparison["fingerprint"] != fingerprint:
        raise ValueError("课程或学情数据已变化，请重新比较后再采纳")
    if comparison["baseStatus"] in ("submitted", "approved"):
        raise ValueError("当前方案已提交或已认可，请先打开规划查看当前状态")
    identifier = "CMP-" + fingerprint
    conn.execute("""INSERT OR IGNORE INTO selection_comparisons(id,student_id,term,payload,created_at)
                    VALUES (?,?,?,?,?)""",
                 (identifier,student_id,comparison["term"],json.dumps(comparison,ensure_ascii=False),core.now()))
    row = conn.execute("SELECT created_at FROM selection_comparisons WHERE id=?", (identifier,)).fetchone()
    return {**comparison, "id":identifier, "comparedAt":row["created_at"]}


def alternative_courses(conn, student_id, course_key, term=None):
    """Read current offerings; an elective candidate must reduce the same category's gap."""
    p = academic.profile(conn, student_id)
    catalog = planning.course_catalog(conn, p["student"]["major"])
    matches = [c for c in catalog.values() if course_key in (c["id"], c["code"], c["name"])]
    if len(matches) != 1:
        raise ValueError("请先说明具体课程名称或代码，再核对停开时的安排")
    course = matches[0]
    term = planning.validate_term(term or planning.next_term(core.TERM))
    plan = planning.get_planning(conn, student_id, term)
    original_offer = next((o for o in plan["offerings"] if o["courseId"] == course["id"]), None)
    state = "有开课记录" if original_offer and original_offer["available"] else "暂不开课" if original_offer else "暂无开课记录"
    result = {"course":{k:course[k] for k in ("id","name","code","category","required")},
              "term":term,"offeringState":state,"dataMode":plan["dataMode"],"alternatives":[]}
    summary = [f"《{course['name']}》在 {term} 的当前记录为“{state}”。"]
    if course["required"]:
        summary.append("这门课程属于必修或限选要求，请向学院确认补开、重修或正式课程替代安排，并检查后续课程的先修条件。")
    else:
        base = plan["savedPlan"]["courseIds"] if plan["savedPlan"] else plan["recommended"]["courseIds"]
        base = [cid for cid in base if cid != course["id"]]
        language = p["credits"]["preferences"]["language"]
        studying = _current_study(conn, student_id, catalog, language)
        studied = {c["id"] for c in studying}
        assumed = _assumed_passes(p, catalog, language, studying)
        program = next(m for m in academic.catalog()["majors"] if m["id"] == p["student"]["major"])
        before = planning.category_totals(program, catalog, assumed | set(base))
        gap = next(c["remaining"] for c in before if c["name"] == course["category"])
        for candidate in plan["offerings"]:
            cid = candidate["courseId"]
            if cid == course["id"] or cid in base or cid in studied or candidate["passed"] or candidate["required"]:
                continue
            if not candidate["available"] or candidate["category"] != course["category"]:
                continue
            checked = planning.check_plan(conn, student_id, term, base + [cid])
            after = planning.category_totals(program, catalog, assumed | set(base) | {cid})
            gain = round(gap - next(c["remaining"] for c in after if c["name"] == course["category"]), 2)
            if checked["eligible"] and gain > 0:
                result["alternatives"].append({"id":cid,"name":candidate["name"],"code":candidate["code"],
                    "credits":candidate["credits"],"contribution":gain,"source":candidate["source"]})
        result["alternatives"].sort(key=lambda c:(-c["contribution"],c["code"]))
        result["alternatives"] = result["alternatives"][:3]
        if result["alternatives"]:
            summary.append("若该课停开，按当前其他课程组合试算，可进一步核对这些同类学分备选：" +
                "；".join(f"《{c['name']}》（{c['code']}），通过后预计减少{course['category']}类缺口 {c['contribution']:g} 学分" for c in result["alternatives"]) + "。")
            summary.append("以上候选已检查当前时段、先修与容量；限选范围及模块归属还需结合培养方案核对。")
        else:
            summary.append("当前记录中没有找到既满足已知选课约束、又能补足同类学分缺口的其他选修课。请先向学院核对开课与重修安排。")
    summary.append("学分试算假设在读课程与方案课程均通过。")
    if plan["dataMode"] in ("demo","mixed"):
        summary.append("当前开课与课表含模拟数据。")
    if p["metrics"]["dataQuality"]["historyNeedsVerification"] or not p["metrics"]["dataQuality"]["enrollmentComplete"]:
        summary.append("历史成绩或本学期选课范围待核实，备选仅基于已导入记录。")
    return result, "".join(summary)


def explain_choice(comparison):
    course = comparison["course"]
    lines = [f"《{course['name']}》在 {comparison['term']} 的两种方案使用相同的其余课程。"]
    for label, key in (("选这门","with"), ("暂不选","without")):
        choice = comparison[key]
        if choice["eligible"]:
            lines.append(f"{label}：组合 {choice['credits']:g} 学分，若在读与组合内课程均通过，预计分类缺口为 {choice['remaining']:g} 学分。")
        else:
            blockers = [i["message"] for i in choice["issues"] if i["level"] == "error"]
            lines.append(f"{label}：须先处理{'、'.join(blockers[:3])}。")
    if comparison["gain"] is not None:
        lines.append(f"在这组课程中，选修该课可多补{course['category']}类 {comparison['gain']:g} 学分。")
    return "".join(lines)


def explain(report):
    credits = report["credits"]
    paragraphs = [
        f"检查学期 {report['term']}。当前已计入 {credits['credited']:g} 学分，"
        f"本学期符合路线的在读课程有 {credits['studying']:g} 学分。"
        f"假设这些课全部通过，按类别重算的缺口为 {credits['ifPassedRemaining']:g} 学分。"
    ]
    if not all(report["coverage"].values()):
        paragraphs.append("成绩或选课的完整范围仍待确认，上述数值仅按已导入记录试算。")
    if report["priority"]:
        course = report["priority"][0]
        offer = course["offering"]
        offering = "该学期暂无已导入的开课记录"
        if offer:
            offering = offer["scheduleText"] if offer["available"] else "该学期的开课记录标记为暂不开课"
        paragraphs.append(f"优先核对《{course['name']}》：{course['reason']}。{course['action']}"
                          f"开课情况为{offering}。单独通过该课程，预计可再补{course['category']}类 {course['additionalIfPassed']:g} 学分。")
    elif report["upcoming"]:
        paragraphs.append(f"当前记录中没有列入优先核对的课程。培养方案建议下学期修读《{report['upcoming'][0]['name']}》等课程，可先检查对应时段。")
    else:
        paragraphs.append("当前记录未列出优先核对课程，请结合覆盖范围和下学期开课信息复查。")
    if report["recognition"]["courses"] or report["recognition"]["pathNote"]:
        paragraphs.append("存在课程归属或培养路径认定待核对事项，正式归属以学院认定为准。")
    if report["alerts"]:
        first = report["alerts"][0]
        paragraphs.append(f"已触发 {len(report['alerts'])} 条项目预警，其中“{first['title']}”由{first['ownerName']}跟进，进展为{first['statusName']}。")
    if report["dataMode"] in ("demo","mixed"):
        paragraphs.append("开课与课表含模拟数据。")
    elif report["dataMode"] == "unavailable":
        paragraphs.append("目标学期缺少开课数据，请补充后再检查组合。")
    return "\n".join(paragraphs)
