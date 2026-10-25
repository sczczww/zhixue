"""Quantified synthetic acceptance for the independent Zhixue rule implementation.

The scenario labels are fixed before inference: no failures / 1 / 2 / 5 outstanding
courses imply levels 0 / 1 / 2 / 3 under the public demonstration specification.
This measures controlled rule consistency, not real-world predictive accuracy.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import core, academic, data_quality


@contextmanager
def isolated_database():
    old_db = os.environ.get("ZHIXUE_DB")
    old_term = core.TERM
    with tempfile.TemporaryDirectory(prefix="scenario-", dir=ROOT / "tests") as folder:
        path = Path(folder).resolve()
        assert path.is_relative_to((ROOT / "tests").resolve())
        os.environ["ZHIXUE_DB"] = str(path / "acceptance.sqlite3")
        core.TERM = "2026-2027-1"
        try:
            core.initialize()
            with core.connection() as db:
                db.execute("INSERT INTO users VALUES ('TEST-C','验收辅导员','counselor','unused-test-hash')")
                yield db
        finally:
            core.TERM = old_term
            if old_db is None:
                os.environ.pop("ZHIXUE_DB", None)
            else:
                os.environ["ZHIXUE_DB"] = old_db


def add_catalog(db):
    plans = core.curriculum()["majors"]
    catalogs = {}
    for plan in plans:
        courses = []
        for source in plan["courses"]:
            if source.get("language") not in (None, "en"):
                continue
            c = {**source, "id": plan["id"] + ":" + source["code"],
                 "required": bool(source["required"] or source.get("language") == "en")}
            courses.append(c)
            db.execute("INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?)", (c["id"], c["code"], c["name"], plan["id"], c["credits"], c["module"], c["semester"], int(c["required"]), json.dumps(c, ensure_ascii=False)))
        catalogs[plan["id"]] = courses
    return catalogs


def semester_term(cohort, semester):
    year = cohort + (semester - 1) // 2
    return f"{year}-{year+1}-{1 if semester % 2 else 2}"


def make_student(db, catalog, sid, major, failures=0, variant=0, cohort=2024):
    db.execute("INSERT INTO students VALUES (?,?,?,?,?,?)", (sid, "合成验收样例", major, cohort, "验收班", "TEST-C"))
    semester = (2026 - cohort) * 2 + 1
    mandatory = [c for c in catalog if c["required"]]
    historical = [c for c in mandatory if c["semester"] < semester]
    # Low-credit failures isolate count-based warnings from the separate credit-gap policy.
    candidates = sorted((c for c in historical if c["credits"] <= 1), key=lambda c: c["code"])
    rotated = candidates[variant % len(candidates):] + candidates[:variant % len(candidates)] if candidates else []
    chosen = {c["id"] for c in rotated[:failures]}
    assert len(chosen) == failures
    for c in mandatory:
        if c["semester"] > semester:
            continue
        score = (50 if c["id"] in chosen else 85) if c["semester"] < semester else None
        db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)", (sid, c["id"], semester_term(cohort, c["semester"]), score, "completed" if score is not None else "enrolled"))
    data_quality.set_coverage(db, sid, "grades", data_quality.previous_term(core.TERM), "complete", "按全部应修课程构造的完整历史成绩fixture", "scenario-builder")
    data_quality.set_coverage(db, sid, "enrollment", core.TERM, "complete", "显式构造的全部当期选课fixture", "scenario-builder")
    return {"id": sid, "name": "合成验收样例", "major": major, "cohort": cohort, "class_name": "验收班", "counselor_id": "TEST-C"}, chosen


def analyze(db, student):
    result = academic._analyze(db, student)
    return result, max((item["severity"] for item in result["_signals"].values()), default=0)


def boundary_checks(db, catalogs):
    checks = []
    student, failed = make_student(db, catalogs["CS"], "BOUNDARY-RETAKE", "CS", failures=1)
    before, _ = analyze(db, student)
    cid = next(iter(failed))
    db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)", (student["id"], cid, core.TERM, 80, "completed"))
    after, level = analyze(db, student)
    credit = db.execute("SELECT credits FROM courses WHERE id=?", (cid,)).fetchone()[0]
    checks.append({"name": "重修通过解除未通过状态且只补计该课学分", "passed": after["metrics"]["failedCourses"] == 0 and after["credits"]["earned"] == before["credits"]["earned"] + credit and level == 0})

    duplicate_before = after["credits"]["earned"]
    db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)", (student["id"], cid, "2025-2026-2", 90, "completed"))
    duplicate_after, _ = analyze(db, student)
    checks.append({"name": "同课程不同学期重复通过不重复计学分", "passed": duplicate_after["credits"]["earned"] == duplicate_before})

    future_cid = next(c["id"] for c in catalogs["CS"] if c["semester"] == 8)
    db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)", (student["id"], future_cid, "2028-2029-2", 0, "completed"))
    future, _ = analyze(db, student)
    checks.append({"name": "未来成绩不改变当前绩点学分和未通过门数", "passed": all(future["metrics"][k] == duplicate_after["metrics"][k] for k in ("gpa", "earnedCredits", "failedCourses", "latestScore"))})

    freshman, _ = make_student(db, catalogs["SE"], "BOUNDARY-NULL", "SE", cohort=2026)
    pending, level = analyze(db, freshman)
    checks.append({"name": "新生全部尚未出分保留空成绩且无虚假低分预警", "passed": pending["metrics"]["latestScore"] is None and pending["student"]["gpa"] is None and level == 0})
    checks.append({"name": "未来学期必修课程不算本学期漏选", "passed": pending["junior"]["missingCourses"] == []})

    withdrawn, failures = make_student(db, catalogs["SE"], "BOUNDARY-WITHDRAW", "SE", failures=1)
    failed_cid = next(iter(failures))
    db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)", (withdrawn["id"], failed_cid, core.TERM, 100, "withdrawn"))
    result, level = analyze(db, withdrawn)
    checks.append({"name": "撤销的高分记录不解除历史未通过课程", "passed": result["metrics"]["failedCourses"] == 1 and level == 1})

    # Single-course current-term data isolates the exact score thresholds from count rules.
    current_course = next(c for c in catalogs["CS"] if c["semester"] == 1 and c["credits"] == 3)
    for index, (score, expected) in enumerate(((59.99, 3), (60, 2), (69.99, 2), (70, 0))):
        sid = "BOUNDARY-SCORE-" + str(index)
        db.execute("INSERT INTO students VALUES (?,?,?,?,?,?)", (sid, "均分边界", "CS", 2026, "验收班", "TEST-C"))
        student_row = db.execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
        db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)", (sid, current_course["id"], core.TERM, score, "completed"))
        data_quality.set_coverage(db, sid, "grades", core.TERM, "complete", "完整单课程学期均分边界fixture", "scenario-builder")
        result, _ = analyze(db, student_row)
        actual = result["_signals"].get("performance", {}).get("severity", 0)
        checks.append({"name": f"原始加权均分{score}对应成绩等级{expected}", "passed": actual == expected, "expected": expected, "actual": actual})
    return checks


def main():
    labels = [0, 1, 2, 3]
    matrix = [[0] * 4 for _ in range(4)]
    scenarios = []
    with isolated_database() as db:
        catalogs = add_catalog(db)
        for expected, failure_count in ((0, 0), (1, 1), (2, 2), (3, 5)):
            for index in range(32):
                mid = "CS" if index % 2 == 0 else "SE"
                sid = f"ACCEPT-{expected}-{index:02d}"
                student, failures = make_student(db, catalogs[mid], sid, mid, failure_count, variant=index // 2)
                result, actual = analyze(db, student)
                matrix[expected][actual] += 1
                scenarios.append({"id": sid, "major": mid, "expected": expected, "predicted": actual,
                                  "outstandingCourses": failure_count, "failedCodes": sorted(failures),
                                  "signals": list(result["_signals"]), "matched": expected == actual})
        checks = boundary_checks(db, catalogs)
        raw_count = db.execute("SELECT COUNT(*) FROM records WHERE student_id LIKE 'ACCEPT-%'").fetchone()[0]
    by_class = []
    for index in labels:
        tp = matrix[index][index]
        support = sum(matrix[index])
        predicted = sum(row[index] for row in matrix)
        precision = tp / predicted if predicted else 0
        recall = tp / support if support else 0
        by_class.append({"level": index, "support": support, "precision": round(precision, 4),
                         "recall": round(recall, 4), "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0})
    report = {
        "title": "独立知学项目：合成原始记录分级验收",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "term": "2026-2027-1", "source": "用户提供培养方案的真实课程代码、学分与计划学期",
        "evaluationType": "controlled_synthetic_rule_consistency",
        "scenarioCount": 128, "rawRecordCount": raw_count, "majors": {"CS": 64, "SE": 64},
        "labels": [{"level": 0, "name": "正常"}, {"level": 1, "name": "轻度"}, {"level": 2, "name": "一般"}, {"level": 3, "name": "危急"}],
        "scenarioDesign": "2024级第5学期，完整录入已到期必修与所选英语路径，当前必修在修；历史正常成绩85分，0/1/2/5门低学分课程50分。各等级各32个案例，两专业各一半；标签在推断前按场景定义固定。",
        "confusionMatrix": matrix, "matrixOrientation": "行=预先定义的期望等级，列=实际规则最高等级",
        "accuracy": round(sum(s["matched"] for s in scenarios) / len(scenarios), 4),
        "perClass": by_class, "scenarios": scenarios, "boundaryChecks": checks,
        "boundariesPassed": sum(c["passed"] for c in checks),
        "allPassed": all(s["matched"] for s in scenarios) and all(c["passed"] for c in checks),
        "officialThreshold": None,
        "limitations": [
            "这是合成场景的规则一致性验收，不是真实学生观测数据，不是模型泛化或风险预测准确率。",
            "样例有意控制其他变量并重复覆盖相同分支，128不是128个统计独立的真实学生样本，不能据此估计真实误报率。",
            "核心通识和个性化选修未伪造校方目录；案例用已核实必修记录隔离分级条件，年度课程认定仍需教务确认。",
            "B1附件没有给出准确率数字门槛，本报告不自行宣称达到官方数值标准。",
            "身份权限、自动分发、闭环、学生行动计划和助手异常回退由独立HTTP集成测试验证，不能从本混淆矩阵推断这些功能。",
        ],
    }
    output = ROOT / "docs" / "validation.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Raw-record scenarios: {sum(s['matched'] for s in scenarios)}/128; boundaries: {report['boundariesPassed']}/{len(checks)}")
    print("Matrix:", matrix)
    for check in checks:
        if not check["passed"]:
            print("FAILED:", check)
    print("Report:", output)
    return 0 if report["allPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
