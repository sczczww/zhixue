"""Planning tests use separate databases and never modify the live demo."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from server import core, planning, academic, data_quality


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="planning-check-", dir=Path(__file__).resolve().parent)
        self.previous = os.environ.get("ZHIXUE_DB")
        os.environ["ZHIXUE_DB"] = str(Path(self.directory.name) / "test.sqlite3")
        core.initialize()
        with core.connection() as db:
            db.executemany("INSERT INTO users(id,name,role,password_hash) VALUES (?,?,?,?)", [("C01", "甲老师", "counselor", "fixture"), ("C02", "乙老师", "counselor", "fixture"), ("2024CS001", "甲学生", "student", "fixture"), ("2024SE002", "乙学生", "student", "fixture"), ("admin", "管理员", "admin", "fixture")])
            db.executemany("INSERT INTO students VALUES (?,?,?,?,?,?)", [("2024CS001", "甲学生", "CS", 2024, "甲班", "C01"), ("2024SE002", "乙学生", "SE", 2024, "乙班", "C02")])
            # These constraint fixtures intentionally start with a known empty
            # academic history, distinct from an unknown/partial real import.
            for sid in ("2024CS001", "2024SE002"):
                data_quality.set_coverage(db, sid, "grades", data_quality.previous_term(core.TERM), "complete", "隔离规划测试的完整空历史快照", "C01")
                data_quality.set_coverage(db, sid, "enrollment", core.TERM, "complete", "隔离规划测试的完整当前注册快照", "C01")
            for program in core.curriculum()["majors"]:
                for c in program["courses"]:
                    db.execute("INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?)", (program["id"] + ":" + c["code"], c["code"], c["name"], program["id"], c["credits"], c["module"], c["semester"], int(c["required"]), json.dumps(c)))
        self.sid = "2024CS001"
        self.a = "CS:154056"
        self.b = "CS:154057"

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("ZHIXUE_DB", None)
        else:
            os.environ["ZHIXUE_DB"] = self.previous
        assert Path(self.directory.name).resolve().is_relative_to(Path(__file__).resolve().parent)
        self.directory.cleanup()

    def client(self, user):
        from server.main import app
        client = TestClient(app)
        token = "planning-fixture-" + user
        with core.connection() as db:
            db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user, time.time() + 600))
        client.cookies.set("zhixue", token)
        return client

    def record(self, cid, score=85, term="2025-2026-2", sid=None):
        with core.connection() as db:
            db.execute("INSERT OR REPLACE INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)", (sid or self.sid, cid, term, score, "completed" if score is not None else "enrolled"))

    def offer(self, cid, day=1, weeks=None, capacity=20, enrolled=0, slots=True, available=True):
        timing = [{"day": day, "start": 1, "end": 2, "weeks": list(range(1, 17)) if weeks is None else weeks}] if slots else []
        with core.connection() as db:
            db.execute("INSERT OR REPLACE INTO course_offerings VALUES (?,?,?,?,?,?,?,?)", (cid, core.TERM, json.dumps(timing), capacity, enrolled, int(available), 0, "测试专用配置，非校方安排"))

    def check(self, ids):
        with core.connection() as db:
            return planning.check_plan(db, self.sid, core.TERM, ids)

    def preferences(self, path="advanced_free", modules=None, allocations=None, language="en"):
        with core.connection() as db:
            return planning.save_preferences(db, self.sid, language, path, modules or ["CS_SYSTEM"], allocations)

    def test_language_switch_is_real_and_does_not_count_two_routes(self):
        plan = next(p for p in core.curriculum()["majors"] if p["id"] == "CS")
        en = next(c for c in plan["courses"] if c.get("language") == "en")
        ja = next(c for c in plan["courses"] if c.get("language") == "ja")
        self.record("CS:" + en["code"])
        self.record("CS:" + ja["code"])
        audit = self.preferences(language="ja")
        self.assertEqual(next(c for c in audit["checks"] if c["name"] == "日语路线学分")["value"], ja["credits"])
        with core.connection() as db:
            result = academic.profile(db, self.sid)
        self.assertEqual(result["credits"]["earned"], ja["credits"])
        self.assertEqual(result["credits"]["preferences"]["language"], "ja")

    def test_module_requires_both_mandatory_and_optional_minimum(self):
        plan = next(p for p in core.curriculum()["majors"] if p["id"] == "CS")
        module = plan["advancedModules"][0]
        choices = [c for c in plan["courses"] if c.get("electiveModule") == module["name"]]
        for c in choices:
            if c.get("requiredInModule"):
                self.record("CS:" + c["code"])
        audit = self.preferences()
        result = next(m for m in audit["moduleAudits"] if m["id"] == "CS_SYSTEM")
        self.assertEqual(result["requiredMissing"], [])
        self.assertFalse(result["met"])
        for c in [c for c in choices if not c.get("requiredInModule") and not c.get("innovation")][:4]:
            self.record("CS:" + c["code"])
        audit = self.preferences()
        result = next(m for m in audit["moduleAudits"] if m["id"] == "CS_SYSTEM")
        self.assertEqual(result["optionalEarned"], 8)
        self.assertTrue(result["met"])

    def test_shared_course_credits_go_to_exactly_one_module(self):
        self.record("CS:155031")
        audit = self.preferences("dual_advanced", ["CS_SYSTEM", "CS_AI"], {"CS:155031": "CS_AI"})
        groups = {m["id"]: m for m in audit["moduleAudits"]}
        self.assertEqual(groups["CS_SYSTEM"]["earned"], 0)
        self.assertEqual(groups["CS_AI"]["earned"], 2)
        self.assertEqual(audit["pathAudit"]["innovationEarned"], 0)
        with self.assertRaises(ValueError):
            self.preferences("dual_advanced", ["CS_SYSTEM", "CS_AI"], {"CS:155031": ["CS_SYSTEM", "CS_AI"]})

    def test_dual_path_is_feasible_with_distinct_credit_allocation(self):
        plan = next(p for p in core.curriculum()["majors"] if p["id"] == "CS")
        for c in plan["courses"]:
            if c.get("electiveModule") or c.get("innovation"):
                self.record("CS:" + c["code"])
        audit = self.preferences("dual_advanced", ["CS_SYSTEM", "CS_AI"], {"CS:155031": "CS_SYSTEM"})
        self.assertTrue(all(m["met"] for m in audit["moduleAudits"]))
        self.assertTrue(audit["pathAudit"]["met"])
        total_assigned = sum(m["earned"] for m in audit["moduleAudits"]) + audit["pathAudit"]["innovationEarned"]
        self.assertLessEqual(total_assigned, audit["pathAudit"]["personalEarned"])

    def test_unknown_cross_module_is_never_automatically_certified(self):
        audit = self.preferences("advanced_cross")
        self.assertFalse(audit["pathAudit"]["met"])
        self.assertIn("年度目录", "".join(audit["pathAudit"]["notes"]))

    def test_verified_cross_module_can_complete_a_real_path(self):
        program = next(p for p in core.curriculum()["majors"] if p["id"] == "CS")
        for c in program["courses"]:
            if c.get("electiveModule") == "计算机系统类进阶模块" and c["code"] != "155031" or c["code"] == "154050":
                self.record("CS:" + c["code"])
        metadata = {"crossModule": "测试认定交叉模块", "crossModuleRequiredCredits": 6, "crossModuleVerified": True, "recognitionSource": "独立测试认定文件；非校方真实数据"}
        with core.connection() as db:
            db.execute("INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?)", ("CS:TEST-CROSS", "TEST-CROSS", "测试交叉课程", "CS", 6, "个性化", 4, 0, json.dumps(metadata)))
        self.record("CS:TEST-CROSS")
        audit = self.preferences("advanced_cross")
        self.assertTrue(audit["pathAudit"]["met"])
        self.assertEqual(audit["pathAudit"]["recognition"]["earned"], 6)

    def test_reference_and_imported_course_ids_do_not_duplicate_requirements(self):
        with core.connection() as db:
            db.execute("UPDATE courses SET id='IMPORTED-ASSEMBLY' WHERE id='CS:154047'")
        self.record("IMPORTED-ASSEMBLY")
        audit = self.preferences()
        module = next(m for m in audit["moduleAudits"] if m["id"] == "CS_SYSTEM")
        ids = [c["id"] for c in module["courses"]]
        self.assertIn("IMPORTED-ASSEMBLY", ids)
        self.assertNotIn("CS:154047", ids)
        self.assertNotIn("汇编语言", [c["name"] for c in module["requiredMissing"]])

    def test_slots_distinguish_overlapping_and_alternating_weeks(self):
        self.offer(self.a, weeks=[1, 3, 5])
        self.offer(self.b, weeks=[2, 4, 6])
        self.assertTrue(self.check([self.a, self.b])["eligible"])
        self.offer(self.b, weeks=[3, 4])
        self.assertIn("time", {x["kind"] for x in self.check([self.a, self.b])["conflicts"]})

    def test_capacity_availability_and_unknown_schedule(self):
        self.offer(self.a, capacity=0)
        self.assertFalse(self.check([self.a])["eligible"])
        self.offer(self.a, slots=False)
        self.assertIn("unknown_schedule", {x["kind"] for x in self.check([self.a])["conflicts"]})
        self.offer(self.a, available=False)
        self.assertIn("unavailable", {x["kind"] for x in self.check([self.a])["conflicts"]})

    def test_known_unoffered_course_has_precise_name_and_excluded_credit_note(self):
        with core.connection() as db:
            result = planning.check_plan(db, "2024SE002", planning.next_term(core.TERM), ["SE:153011"])
        message = next(c["message"] for c in result["conflicts"] if c["kind"] == "unavailable")
        self.assertIn("操作系统", message)
        self.assertIn("尚无已确认开课记录", message)
        self.assertNotIn("不属于", message)
        self.assertEqual(result["totalCredits"], 0)
        self.assertIn("不表示该课程本身为0学分", "".join(result["notes"]))
        foreign = self.check(["SE:153011"])
        self.assertNotIn("操作系统", next(c["message"] for c in foreign["conflicts"] if c["kind"] == "unavailable"))

    def test_prerequisite_needs_prior_pass_not_simultaneous_selection(self):
        prereq = "CS:154066"
        self.offer(self.a)
        self.offer(prereq, day=2)
        with core.connection() as db:
            db.execute("INSERT INTO course_dependencies VALUES (?,?,?,?)", (self.a, prereq, 1, "测试演示先修"))
        self.assertFalse(self.check([self.a, prereq])["eligible"])
        self.record(prereq, term=core.TERM)
        self.assertFalse(self.check([self.a])["eligible"])
        self.record(prereq)
        self.assertTrue(self.check([self.a])["eligible"])

    def test_cross_major_and_duplicate_courses_are_rejected(self):
        self.offer(self.a)
        self.offer("SE:154056")
        self.assertFalse(self.check(["SE:154056"])["eligible"])
        self.assertFalse(self.check([self.a, self.a])["eligible"])

    def test_demo_support_does_not_overwrite_real_offering_or_plan(self):
        self.offer(self.a, capacity=7)
        with core.connection() as db:
            plan = planning.save_plan(db, self.sid, core.TERM, [self.a], "保留方案", "保留说明", self.sid)
            planning.seed_demo_support(db)
            planning.seed_demo_support(db)
            row = db.execute("SELECT * FROM course_offerings WHERE course_id=? AND term=?", (self.a, core.TERM)).fetchone()
            self.assertEqual(row["capacity"], 7)
            self.assertEqual(row["is_demo"], 0)
            self.assertEqual(db.execute("SELECT title FROM course_plans WHERE id=?", (plan["id"],)).fetchone()[0], "保留方案")

    def test_recommendations_are_checked_and_exclude_blocked_choices(self):
        self.offer(self.a, capacity=0)
        self.offer(self.b)
        with core.connection() as db:
            result = planning.get_planning(db, self.sid)
        self.assertNotIn(self.a, result["recommended"]["courseIds"])
        self.assertIn(self.b, result["recommended"]["courseIds"])
        self.assertTrue(result["recommended"]["eligible"])
        self.assertFalse(result["recommended"]["complete"])
        self.assertTrue(result["recommended"]["missingRequired"])

    def test_submission_reassignment_is_notified_once(self):
        self.offer(self.a)
        with core.connection() as db:
            saved = planning.save_plan(db, self.sid, core.TERM, [self.a], "转交测试", "", self.sid)
            planning.submit_plan(db, self.sid, core.TERM, self.sid)
            db.execute("UPDATE students SET counselor_id='C02' WHERE id=?", (self.sid,))
            planning.sync_plan_owner(db, self.sid)
            planning.sync_plan_owner(db, self.sid)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM inbox_messages WHERE user_id='C02' AND kind='semester_plan'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT submitted_owner_id FROM course_plans WHERE id=?", (saved["id"],)).fetchone()[0], "C02")
        url = f"/api/students/{self.sid}/planning/review"
        self.assertEqual(self.client("C01").post(url, json={"term": core.TERM, "status": "approved", "comment": "原负责老师"}).status_code, 403)
        self.assertEqual(self.client("C02").post(url, json={"term": core.TERM, "status": "approved", "comment": "新负责老师"}).status_code, 200)

    def test_changed_preferences_invalidate_approval_but_identical_save_does_not(self):
        self.offer(self.a)
        self.preferences()
        with core.connection() as db:
            saved = planning.save_plan(db, self.sid, core.TERM, [self.a], "偏好关联", "", self.sid)
            planning.submit_plan(db, self.sid, core.TERM, self.sid)
            planning.review_plan(db, self.sid, core.TERM, "approved", "同意此版本", "C01")
            planning.save_preferences(db, self.sid, "en", "advanced_free", ["CS_SYSTEM"])
            self.assertEqual(db.execute("SELECT status FROM course_plans WHERE id=?", (saved["id"],)).fetchone()[0], "approved")
            old_messages = db.execute("SELECT COUNT(*) FROM inbox_messages").fetchone()[0]
            planning.save_preferences(db, self.sid, "en", "advanced_free", ["CS_AI"])
            row = db.execute("SELECT * FROM course_plans WHERE id=?", (saved["id"],)).fetchone()
            self.assertEqual(row["status"], "revision")
            self.assertIn("重新检查", row["review_comment"])
            self.assertEqual(json.loads(row["preference_snapshot"])["advancedModules"], ["CS_SYSTEM"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM inbox_messages").fetchone()[0], old_messages + 1)
            planning.save_preferences(db, self.sid, "en", "advanced_free", ["CS_AI"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM plan_events WHERE action='preferences_changed'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM plan_events WHERE action='approved'").fetchone()[0], 1)

    def test_changed_preferences_return_pending_plan_for_recheck(self):
        self.offer(self.a)
        self.preferences()
        with core.connection() as db:
            saved = planning.save_plan(db, self.sid, core.TERM, [self.a], "待审核", "", self.sid)
            planning.submit_plan(db, self.sid, core.TERM, self.sid)
            planning.save_preferences(db, self.sid, "ja", "advanced_free", ["CS_SYSTEM"])
            self.assertEqual(db.execute("SELECT status FROM course_plans WHERE id=?", (saved["id"],)).fetchone()[0], "revision")
            with self.assertRaises(ValueError):
                planning.review_plan(db, self.sid, core.TERM, "approved", "旧状态审核应拒绝", "C01")

    def test_plan_submission_review_revision_and_version_persist(self):
        self.offer(self.a)
        student = self.client(self.sid)
        teacher = self.client("C01")
        url = "/api/students/" + self.sid + "/planning"
        saved = student.put(url, json={"term": core.TERM, "courseIds": [self.a], "title": "秋季安排"})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(student.post(url + "/submit", json={"term": core.TERM}).json()["status"], "submitted")
        self.assertEqual(student.put(url, json={"term": core.TERM, "courseIds": [self.a]}).status_code, 422)
        self.assertEqual(self.client("C02").post(url + "/review", json={"term": core.TERM, "status": "approved", "comment": "同意方案"}).status_code, 403)
        reviewed = teacher.post(url + "/review", json={"term": core.TERM, "status": "revision", "comment": "请补充修读目标"})
        self.assertEqual(reviewed.status_code, 200, reviewed.text)
        revised = student.put(url, json={"term": core.TERM, "courseIds": [self.a], "note": "已补充"}).json()
        self.assertEqual(revised["version"], 2)
        student.post(url + "/submit", json={"term": core.TERM})
        self.assertEqual(teacher.post(url + "/review", json={"term": core.TERM, "status": "approved", "comment": "安排合理"}).json()["status"], "approved")
        self.assertEqual(student.get(url).json()["savedPlan"]["status"], "approved")
        with core.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM records").fetchone()[0], 0, "Approving a plan is not actual course registration")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM plan_events").fetchone()[0], 6)

    def test_student_cannot_review_and_counselor_cannot_edit_preferences(self):
        payload = {"language": "en", "path": "advanced_free", "advancedModules": ["CS_SYSTEM"]}
        self.assertEqual(self.client("C01").put(f"/api/students/{self.sid}/curriculum-preferences", json=payload).status_code, 403)
        self.assertEqual(self.client(self.sid).get("/api/students/2024SE002/planning").status_code, 403)
        self.assertEqual(self.client(self.sid).post(f"/api/students/{self.sid}/planning/review", json={"term": core.TERM, "status": "approved", "comment": "自行通过"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
