"""Heterogeneous, source-backed raw-record checks for the academic support rules.

Twenty different input designs are applied to both curricula. This is a controlled
software acceptance set, not forty independent observations of real students.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from evaluate_scenarios import isolated_database, add_catalog, make_student, semester_term
from server import academic, core, data_quality

KINDS = ("performance", "completion", "progress", "selection")


def subset_credits(courses, minimum, maximum=None):
    """Choose source courses with a requested credit sum; never consult engine output."""
    candidates = sorted(courses, key=lambda c: (-c["credits"], c["code"]))
    options = {0: []}
    limit = round((maximum if maximum is not None else sum(c["credits"] for c in courses)) * 2)
    for course in candidates:
        units = round(course["credits"] * 2)
        assert abs(units / 2 - course["credits"]) < 1e-9
        for total, chosen in list(options.items()):
            if total + units <= limit and total + units not in options:
                options[total + units] = [*chosen, course]
    valid = [amount for amount in options if amount / 2 >= minimum - 1e-9]
    if not valid:
        raise AssertionError(f"No source-backed credit subset in {minimum}..{maximum}")
    return options[min(valid)]


def raw_earned(catalog, records):
    passed = {r["course_id"] for r in records if r["term"] <= core.TERM and r["state"] != "withdrawn" and r["score"] is not None and r["score"] >= 60}
    return sum(c["credits"] for c in catalog if c["id"] in passed)


def build_case(db, catalog, major, design, number):
    sid = f"SUPPORT-{major}-{number:02d}"
    cohort = 2023 if design in ("later_load_attention", "later_load_urgent") else 2026 if design == "freshman_pending" else 2024
    failure_count = 1 if design in ("retake_recovery", "withdrawn_retake") else 3 if design == "combined" else 0
    student, failed = make_student(db, catalog, sid, major, failures=failure_count, cohort=cohort)
    semester = 2 * (2026 - cohort) + 1
    historical = [c for c in catalog if c["required"] and c["semester"] < semester]
    current = [c for c in catalog if c["required"] and c["semester"] == semester]
    plan = next(p for p in core.curriculum()["majors"] if p["id"] == major)
    context = {"design": design, "cohort": cohort, "semester": semester, "baseline": "已到期必修及英语路线按原建议学期录入；历史85分，本学期尚未出分", "changes": []}
    expected = {"kinds": {}, "overall": 0, "evidenceLabels": []}
    invariants = {}

    def expect(kind, level, label=None, overall=None):
        expected["kinds"][kind] = level
        expected["overall"] = level if overall is None else overall
        if label:
            expected["evidenceLabels"].append({"kind": kind, "label": label})

    def drop(courses):
        for c in courses:
            db.execute("DELETE FROM records WHERE student_id=? AND course_id=?", (sid, c["id"]))
        context["changes"].append({"action": "remove_records", "courseIds": [c["id"] for c in courses], "credits": sum(c["credits"] for c in courses)})

    if design == "healthy":
        expected["kinds"] = dict.fromkeys(KINDS, 0)
    elif design.startswith("score_"):
        value = float(design.split("_")[1])
        db.execute("UPDATE records SET score=?,state='completed' WHERE student_id=? AND term=?", (value, sid, core.TERM))
        data_quality.set_coverage(db, sid, "grades", core.TERM, "complete", "全部当期课程均已出分的合成场景", "scenario-builder")
        level = 3 if value == 59 else 2 if value in (60, 65) else 0
        expect("performance", level, "最近学期加权均分" if level else None)
        context["changes"].append({"action": "grade_current_courses", "score": value, "courseIds": [c["id"] for c in current]})
    elif design == "three_term_decline":
        for sem, value in ((2, 95), (3, 85), (4, 75)):
            db.execute("UPDATE records SET score=? WHERE student_id=? AND term=?", (value, sid, semester_term(cohort, sem)))
        expect("performance", 1, "三个学期绩点变化")
        context["changes"].append({"action": "three_graded_terms", "semesterScores": [[2, 95], [3, 85], [4, 75]]})
    elif design in ("missing_one", "missing_two"):
        count = 1 if design == "missing_one" else 2
        drop(sorted(current, key=lambda c: (c["credits"], c["code"]))[:count])
        expect("selection", count, "到期未通过且未选课程")
    elif design in ("credit_gap_attention", "credit_gap_urgent"):
        due = sum(c["credits"] for c in historical)
        if design == "credit_gap_attention":
            chosen = subset_credits(historical, max(6, due * .15), math.ceil(due * .25 * 2) / 2 - .5)
            expect("progress", 2, "往期应修必修学分缺口")
        else:
            chosen = subset_credits(historical, max(12, due * .25), due * .35)
            expect("progress", 3, "往期应修必修学分缺口")
        drop(chosen)
        context.update({"historicalRequiredCredits": due, "removedCreditRatio": sum(c["credits"] for c in chosen) / due})
    elif design == "overloaded_current":
        already = {c["id"] for c in current}
        current_credits = sum(c["credits"] for c in current)
        limit = max(30, (current_credits + 6) * 1.25)
        candidates = [c for c in catalog if c["id"] not in already and c.get("language") in (None, "en")]
        extra = subset_credits(candidates, limit - current_credits + .5)
        for c in extra:
            db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,NULL,'enrolled')", (sid, c["id"], core.TERM))
        expect("selection", 2, "当前选课学分")
        context["changes"].append({"action": "add_current_enrollments", "courseIds": [c["id"] for c in extra]})
        context["publishedLoadLimit"] = limit
    elif design in ("later_load_attention", "later_load_urgent"):
        base_remaining = sum(max(0, r["credits"] - sum(c["credits"] for c in historical if c["module"] == r["name"])) for r in plan["categoryRequirements"])
        target_per_term = 29 if design == "later_load_attention" else 35
        needed_drop = max(0, target_per_term * 2 - base_remaining)
        chosen = subset_credits(historical, needed_drop) if needed_drop else []
        drop(chosen)
        expect("progress", 2 if design == "later_load_attention" else 3, "剩余每学期平均需修")
        context.update({"remainingTerms": 2, "inputDerivedRemainingCredits": base_remaining + sum(c["credits"] for c in chosen), "isolation": "删除量低于往期学分缺口15%阈值，验证后续负荷分支"})
        assert sum(c["credits"] for c in chosen) < sum(c["credits"] for c in historical) * .15
    elif design == "no_historical_data":
        db.execute("DELETE FROM records WHERE student_id=? AND term<?", (sid, core.TERM))
        data_quality.set_coverage(db, sid, "grades", data_quality.previous_term(core.TERM), "partial", "场景明确删除历史成绩来源", "scenario-builder")
        expected["kinds"] = dict.fromkeys(KINDS, 0)
        invariants = {"historyNeedsVerification": True, "gpa": None, "earnedCredits": 0}
        context["changes"].append({"action": "remove_history_keep_current_ungraded"})
    elif design == "freshman_pending":
        expected["kinds"] = dict.fromkeys(KINDS, 0)
        invariants = {"gpa": None, "earnedCredits": 0, "latestScore": None}
        context["changes"].append({"action": "first_semester_all_grades_pending"})
    elif design == "retake_recovery":
        cid = next(iter(failed))
        db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,80,'completed')", (sid, cid, core.TERM))
        expected["kinds"] = dict.fromkeys(KINDS, 0)
        invariants = {"failedCourses": 0}
        context["changes"].append({"action": "pass_retake_after_failure", "courseId": cid, "historicalScore": 50, "retakeScore": 80})
    elif design == "future_records":
        cid = next(c["id"] for c in catalog if c["required"] and c["semester"] == 8)
        db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,0,'completed')", (sid, cid, "2028-2029-2"))
        expected["kinds"] = dict.fromkeys(KINDS, 0)
        invariants = {"failedCourses": 0, "earnedCredits": sum(c["credits"] for c in historical)}
        context["changes"].append({"action": "future_failed_grade", "courseId": cid, "term": "2028-2029-2"})
    elif design == "withdrawn_retake":
        cid = next(iter(failed))
        db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,100,'withdrawn')", (sid, cid, core.TERM))
        expect("completion", 1, "尚未通过课程")
        invariants = {"failedCourses": 1}
        context["changes"].append({"action": "withdrawn_score_must_not_resolve_failure", "courseId": cid})
    elif design == "combined":
        db.execute("UPDATE records SET score=65,state='completed' WHERE student_id=? AND term=?", (sid, core.TERM))
        data_quality.set_coverage(db, sid, "grades", core.TERM, "complete", "全部当期课程已出分的组合风险场景", "scenario-builder")
        expected["kinds"] = {"performance": 2, "completion": 2, "selection": 2}
        expected["overall"] = 2
        expected["evidenceLabels"] = [{"kind": "performance", "label": "最近学期加权均分"}, {"kind": "completion", "label": "尚未通过课程"}]
        context["changes"].append({"action": "combine_current_low_passing_scores_and_three_prior_failures", "currentScore": 65, "failedCourseIds": sorted(failed)})
    elif design == "current_enrollment_unknown":
        db.execute("DELETE FROM records WHERE student_id=? AND term=?", (sid, core.TERM))
        data_quality.set_coverage(db, sid, "enrollment", core.TERM, "partial", "场景明确缺少本期选课来源", "scenario-builder")
        expected["kinds"] = dict.fromkeys(KINDS, 0)
        invariants = {"hasCurrentEnrollment": False, "currentGradesPending": True}
        context["changes"].append({"action": "remove_current_enrollment_source"})
    else:
        raise ValueError(design)
    return student, expected, context, invariants


def main():
    designs = ["healthy", "score_59", "score_60", "score_65", "score_70", "three_term_decline", "missing_one", "missing_two", "credit_gap_attention", "credit_gap_urgent", "overloaded_current", "later_load_attention", "later_load_urgent", "no_historical_data", "freshman_pending", "retake_recovery", "future_records", "withdrawn_retake", "combined", "current_enrollment_unknown"]
    cases = []
    with isolated_database() as db:
        catalogs = add_catalog(db)
        for major, catalog in catalogs.items():
            program = next(p for p in core.curriculum()["majors"] if p["id"] == major)
            for number, design in enumerate(designs, 1):
                student, expected, context, invariants = build_case(db, catalog, major, design, number)
                # All expected levels above are fixed from scenario definitions before inference.
                result = academic._analyze(db, student)
                signals = result["_signals"]
                actual = {kind: signals.get(kind, {}).get("severity", 0) for kind in KINDS}
                actual_overall = max(actual.values())
                failures = [f"{kind}: expected {level}, actual {actual[kind]}" for kind, level in expected["kinds"].items() if actual[kind] != level]
                if actual_overall != expected["overall"]:
                    failures.append(f"overall: expected {expected['overall']}, actual {actual_overall}")
                for item in expected["evidenceLabels"]:
                    if item["label"] not in [e["label"] for e in signals.get(item["kind"], {}).get("evidence", [])]:
                        failures.append("Expected rule branch absent: " + item["label"])
                measured = {**result["metrics"], **result["metrics"]["dataQuality"]}
                for key, value in invariants.items():
                    if measured.get(key) != value:
                        failures.append(f"{key}: expected {value}, actual {measured.get(key)}")
                rows = [dict(r) for r in db.execute("SELECT course_id,term,score,state FROM records WHERE student_id=? ORDER BY term,course_id", (student["id"],))]
                independent_credits = raw_earned(catalog, rows)
                if result["credits"]["earned"] != independent_credits:
                    failures.append("Earned-credit reconciliation failed")
                source_ids = {r["course_id"] for r in rows}
                cases.append({"id": student["id"], "major": major, "design": design, "context": context, "expected": {**expected, "invariants": invariants, "earnedCreditsFromRawRows": independent_credits},
                              "actual": {"kinds": actual, "overall": actual_overall, "metrics": result["metrics"], "evidence": {k: v["evidence"] for k, v in signals.items()}}, "passed": not failures, "failures": failures,
                              "recordSource": {"pdf": program["source"]["title"], "pdfSha256": program["source"]["sha256"], "catalogFile": "data/curriculum.json", "courses": [{"id": c["id"], "code": c["code"], "credits": c["credits"], "sourcePage": c.get("sourcePage")} for c in catalog if c["id"] in source_ids]},
                              "rawRecordCount": len(rows), "rawRecordSha256": hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest(), "rawRecords": rows})
    report = {"title": "多风险异质原始记录验收", "generatedAt": datetime.now(timezone.utc).isoformat(), "evaluationType": "controlled_heterogeneous_rule_acceptance", "term": "2026-2027-1",
              "designCount": len(designs), "caseCount": len(cases), "passedCases": sum(c["passed"] for c in cases), "rawRecordCount": sum(c["rawRecordCount"] for c in cases), "allPassed": all(c["passed"] for c in cases),
              "expectedLabelMethod": "输入生成前按公开演示政策指定目标风险种类及等级，并核对整体等级；学分缺口与负荷由原课程学分独立构造，不读取被测输出产生期望标签。",
              "limitations": ["20种设计分别应用于两专业，不是40名统计独立的真实学生；不用于估计真实误报率、预测准确率或干预效果。", "历史成绩与选课为合成输入，课程代码、学分、建议学期和页码来自所给培养方案。", "此处验证规则分支与原始记录核算；真实模型、多用户交互、通知和帮扶状态流转由其他独立测试验证。", "第7学期负荷场景用于隔离第5学期起适用的后续负荷政策，避免与大额往期学分缺口混淆。"], "cases": cases}
    target = ROOT / "docs" / "support-validation.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Heterogeneous cases: {report['passedCases']}/{report['caseCount']}; distinct designs: {len(designs)}; raw records: {report['rawRecordCount']}")
    for case in cases:
        if not case["passed"]:
            print(case["id"], case["design"], "; ".join(case["failures"]))
    print("Report:", target)
    return 0 if report["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
