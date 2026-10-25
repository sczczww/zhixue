"""Independent acceptance checks for the new Zhixue implementation."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from server import core, academic, data_quality


class IsolatedDatabase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="zhixue-check-", dir=Path(__file__).resolve().parent)
        self.previous = os.environ.get("ZHIXUE_DB")
        os.environ["ZHIXUE_DB"] = str(Path(self.directory.name) / "checks.sqlite3")
        core.initialize()

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("ZHIXUE_DB", None)
        else:
            os.environ["ZHIXUE_DB"] = self.previous
        assert Path(self.directory.name).resolve().is_relative_to(Path(__file__).resolve().parent)
        self.directory.cleanup()

    def client(self, user=None):
        from server.main import app
        client = TestClient(app)
        if user:
            token = "test-session-" + user
            with core.connection() as conn:
                conn.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user, time.time() + 300))
            client.cookies.set("zhixue", token)
        return client


class AcademicCases(IsolatedDatabase):
    def setUp(self):
        super().setUp()
        with core.connection() as conn:
            conn.executemany("INSERT INTO users VALUES (?,?,?,?)", [("C01", "甲老师", "counselor", "fixture"), ("C02", "乙老师", "counselor", "fixture"), ("admin", "管理员", "admin", "fixture"), ("2024CS001", "甲同学", "student", "fixture"), ("2024CS002", "乙同学", "student", "fixture")])
            conn.executemany("INSERT INTO students VALUES (?,?,?,?,?,?)", [("2024CS001", "甲同学", "CS", 2024, "甲班", "C01"), ("2024CS002", "乙同学", "CS", 2024, "乙班", "C02")])
        self.course("old", 4, 1)
        self.course("now", 4, 5)
        self.course("future", 4, 8)

    def course(self, name, credits=4, semester=1, category="专业", required=True, metadata=None):
        with core.connection() as conn:
            conn.execute("INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?)", ("CS:" + name, name, name, "CS", credits, category, semester, int(required), json.dumps(metadata or {})))

    def record(self, course="old", score=80, term="2024-2025-1", student="2024CS001", state=None):
        with core.connection() as conn:
            conn.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)", (student, "CS:" + course, term, score, state or ("enrolled" if score is None else "completed")))

    def profile(self):
        with core.connection() as conn:
            return academic.profile(conn, "2024CS001")

    def recompute(self):
        with core.connection() as conn:
            return academic.recompute(conn)

    def test_missing_grade_remains_unknown(self):
        self.record("now", None, core.TERM)
        result = self.profile()
        self.assertIsNone(result["student"]["gpa"])
        self.assertEqual(result["trend"], [])
        self.assertTrue(result["metrics"]["currentGradesPending"])
        self.recompute()
        self.assertFalse(any(a["kind"] == "performance" for a in self.profile()["alerts"]))

    def test_absent_history_does_not_imply_missed_old_courses(self):
        self.record("now", None, core.TERM)
        result = self.profile()
        self.assertNotIn("old", result["junior"]["missingCourses"])
        self.assertIsNone(result["metrics"]["creditGap"])
        self.assertTrue(result["metrics"]["dataQuality"]["historyNeedsVerification"])
        self.assertTrue(result["metrics"]["dataNotes"])
        self.recompute()
        self.assertFalse(any(a["kind"] == "progress" for a in self.profile()["alerts"]))
        with core.connection() as conn:
            conn.execute("UPDATE records SET score=80,state='completed' WHERE student_id='2024CS001'")
        self.recompute()
        self.assertFalse(any(a["kind"] == "progress" for a in self.profile()["alerts"]))

    def test_retake_credit_count_and_visible_score_agree(self):
        self.record(score=45)
        self.record(score=80, term="2025-2026-1")
        self.record(score=40, term="2025-2026-2")
        result = self.profile()
        self.assertEqual(result["credits"]["earned"], 4)
        self.assertEqual(result["metrics"]["failedCourses"], 0)
        course = next(c for c in result["courses"] if c["code"] == "old")
        self.assertEqual((course["state"], course["score"]), ("passed", 80))

    def test_future_score_and_withdrawal_do_not_award_credits(self):
        self.record(score=90, term="2027-2028-1")
        self.record("now", 95, core.TERM, state="withdrawn")
        self.assertEqual(self.profile()["credits"]["earned"], 0)

    def test_future_course_is_not_missing(self):
        self.record()
        self.record("now", None, core.TERM)
        self.assertNotIn("future", self.profile()["junior"]["missingCourses"])
        self.assertEqual(self.profile()["junior"]["missingCourses"], [])

    def test_module_surplus_cannot_fill_other_modules(self):
        # Complete each named general-education subcategory, with 28 surplus
        # credits overall. Those surplus credits cannot fill another category.
        for name, credits, submodule in (("general", 50, "通修通识"), ("classified", 30, "分类通识"), ("core", 20, "核心通识")):
            self.course(name, credits, category="通识", required=False, metadata={"submodule": submodule})
            self.record(name)
        result = self.profile()["credits"]
        self.assertEqual(result["earned"], 100)
        self.assertEqual(result["remaining"], 101)  # Professional 69 + personalized 32.

    def test_completion_severity_boundaries(self):
        for index in range(5):
            self.course("fail" + str(index), 1)
            self.record("fail" + str(index), 55)
            self.recompute()
            alert = next(a for a in self.profile()["alerts"] if a["kind"] == "completion")
            self.assertEqual(alert["level"], 1 if index == 0 else 2 if index < 4 else 3)

    def test_score_thresholds_use_unrounded_weighted_score(self):
        self.record(score=59.99)
        with core.connection() as conn:
            data_quality.set_coverage(conn, "2024CS001", "grades", "2024-2025-1", "complete", "完整单课程学期均分边界fixture", "test")
        for value, expected in [(59.99, 3), (60, 2), (69.99, 2), (70, 0)]:
            with core.connection() as conn:
                conn.execute("UPDATE records SET score=?", (value,))
            self.recompute()
            alerts = [a for a in self.profile()["alerts"] if a["kind"] == "performance" and a["active"]]
            self.assertEqual(max((a["level"] for a in alerts), default=0), expected)

    def test_recompute_is_idempotent_and_routes_to_both_audiences(self):
        self.record(score=55)
        first = self.recompute()
        second = self.recompute()
        self.assertGreater(first["created"], 0)
        self.assertEqual(second["created"], 0)
        with core.connection() as conn:
            alerts = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 2 * alerts)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM case_events WHERE action='created'").fetchone()[0], alerts)

    def test_recovery_retains_followup_history(self):
        self.record(score=55)
        self.recompute()
        self.record(score=85, term="2025-2026-1")
        self.recompute()
        completion = next(a for a in self.profile()["alerts"] if a["kind"] == "completion")
        self.assertFalse(completion["active"])
        self.assertEqual(completion["status"], "new")

    def test_malicious_role_headers_do_not_authenticate(self):
        response = self.client().get("/api/students", headers={"X-Role": "admin", "X-User-Id": "admin"})
        self.assertEqual(response.status_code, 401)
        response = self.client("2024CS001").post("/api/recompute", headers={"X-Role": "admin"})
        self.assertEqual(response.status_code, 403)

    def test_student_and_counselor_scope(self):
        self.assertEqual(self.client("2024CS001").get("/api/students/2024CS002").status_code, 403)
        self.assertEqual(self.client("C02").get("/api/students/2024CS001").status_code, 403)
        visible = self.client("C01").get("/api/students").json()
        self.assertEqual([r["id"] for r in visible["items"]], ["2024CS001"])

    def test_notification_ack_scope_and_persistence(self):
        self.record(score=55)
        self.recompute()
        teacher = self.client("C01")
        notification = teacher.get("/api/notifications").json()["items"][0]
        self.assertEqual(self.client("C02").post(f"/api/notifications/{notification['id']}/read").status_code, 403)
        self.assertEqual(teacher.post(f"/api/notifications/{notification['id']}/read").status_code, 200)
        self.assertTrue(next(n for n in teacher.get("/api/notifications").json()["items"] if n["id"] == notification["id"])["read"])

    def test_reassignment_revokes_old_notifications(self):
        self.record(score=55)
        self.recompute()
        self.assertTrue(self.client("C01").get("/api/notifications").json()["items"])
        with core.connection() as conn:
            conn.execute("UPDATE students SET counselor_id='C02' WHERE id='2024CS001'")
        self.recompute()
        self.assertEqual(self.client("C01").get("/api/notifications").json()["items"], [])
        self.assertTrue(self.client("C02").get("/api/notifications").json()["items"])

    def test_followup_state_machine_and_csv(self):
        self.record(score=55)
        self.recompute()
        teacher = self.client("C01")
        alert = next(a for a in self.profile()["alerts"] if a["kind"] == "completion")
        url = "/api/alerts/" + alert["id"] + "/followup"
        self.assertEqual(teacher.post(url, json={"status": "closed", "note": "跳过流程"}).status_code, 409)
        for state in ["contacted", "supporting", "review", "closed"]:
            response = teacher.post(url, json={"status": state, "note": "=不执行公式", "plan": "每周答疑", "reviewOn": "2026-11-01"})
            self.assertEqual(response.status_code, 200, response.text)
        detail = teacher.get("/api/alerts/" + alert["id"]).json()
        self.assertEqual(detail["alert"]["status"], "closed")
        self.assertEqual(len(detail["events"]), 5)
        self.recompute()
        self.assertEqual(teacher.get("/api/alerts/" + alert["id"]).json()["alert"]["status"], "closed")
        exported = teacher.get("/api/export")
        rows = list(csv.reader(io.StringIO(exported.text.lstrip("\ufeff"))))
        self.assertTrue(any("'=不执行公式" in row for row in rows))
        self.assertNotIn("乙同学", exported.text)


class DemoAcceptance(IsolatedDatabase):
    def test_144_student_demo_and_actual_cluster_workflow(self):
        from server.seed import ensure_demo
        ensure_demo(144)
        teacher = self.client("C01")
        overview = teacher.get("/api/overview")
        self.assertEqual(overview.status_code, 200, overview.text)
        self.assertEqual(overview.json()["students"], 36)
        with core.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM students").fetchone()[0], 144)
            summary = academic.recompute(conn)
            self.assertEqual(summary["created"], 0)
        analytics = teacher.get("/api/analytics")
        self.assertEqual(analytics.status_code, 200, analytics.text)
        self.assertEqual(len(analytics.json()["views"]), 4)
        self.assertTrue(any(v["method"] == "K-means 聚类" for v in analytics.json()["views"]))
        for view in analytics.json()["views"]:
            self.assertEqual(sum(g["count"] for g in view["groups"]), 36)
        first = teacher.get("/api/students").json()["items"][0]
        detail = teacher.get("/api/students/" + first["id"]).json()
        self.assertEqual(detail["credits"]["total"], 173)
        self.assertEqual(sum(c["required"] for c in detail["credits"]["categories"]), 173)
        self.assertEqual(len(detail["credits"]["checks"]), 5)


if __name__ == "__main__":
    unittest.main()
