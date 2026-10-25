"""Fresh end-to-end acceptance of the independent Zhixue HTTP application.

Every test gets a copy of a newly seeded temporary database under tests/.
The runtime database and real model endpoints are never used.
"""
from __future__ import annotations

import csv
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class IntegrationAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="integration-", dir=Path(__file__).resolve().parent)
        cls.root = Path(cls.directory.name).resolve()
        cls.old_env = {k: os.environ.get(k) for k in ("ZHIXUE_DB", "ZHIXUE_DEMO")}
        os.environ["ZHIXUE_DB"] = str(cls.root / "seed.sqlite3")
        os.environ["ZHIXUE_DEMO"] = "1"
        from server.main import app
        from server import core, assistant
        cls.app, cls.core, cls.assistant = app, core, assistant
        with TestClient(app) as bootstrap:
            result = bootstrap.get("/api/status")
            if result.status_code != 200 or result.json()["students"] != 144:
                raise AssertionError("Fresh lifespan must seed exactly 144 demo students")
        with core.connection() as db:
            with closing(sqlite3.connect(cls.root / "base.sqlite3")) as destination:
                db.backup(destination)

    @classmethod
    def tearDownClass(cls):
        for key, previous in cls.old_env.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        assert cls.root.is_relative_to(Path(__file__).resolve().parent)
        cls.directory.cleanup()

    def setUp(self):
        os.environ["ZHIXUE_DB"] = str(self.root / (self._testMethodName + ".sqlite3"))
        with closing(sqlite3.connect(self.root / "base.sqlite3")) as source:
            with closing(sqlite3.connect(os.environ["ZHIXUE_DB"])) as destination:
                source.backup(destination)
        self.original_key = self.assistant.memory_key
        self.assistant.memory_key = ""
        self.client = TestClient(self.app)
        self.client.__enter__()
        with self.core.connection() as db:
            self.subject = dict(db.execute("SELECT * FROM students WHERE counselor_id='C01' ORDER BY id LIMIT 1").fetchone())
            self.other = dict(db.execute("SELECT * FROM students WHERE counselor_id='C02' ORDER BY id LIMIT 1").fetchone())
            self.alert = dict(db.execute("SELECT * FROM alerts WHERE owner_id='C01' AND status='new' ORDER BY id LIMIT 1").fetchone())
            self.alert_student = dict(db.execute("SELECT * FROM students WHERE id=?", (self.alert["student_id"],)).fetchone())
            self.foreign_alert = dict(db.execute("SELECT * FROM alerts WHERE owner_id='C02' ORDER BY id LIMIT 1").fetchone())

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.assistant.memory_key = self.original_key

    def login(self, username):
        self.client.cookies.clear()
        response = self.client.post("/api/login", json={"username": username, "password": "demo123"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["user"]["id"], username)
        return response

    def upload(self, kind, rows):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
        response = self.client.post("/api/import", params={"type": kind},
                                    files={"file": ("acceptance.csv", stream.getvalue().encode("utf-8-sig"), "text/csv")})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_anonymous_and_header_spoof_do_not_authenticate(self):
        self.assertEqual(self.client.get("/api/status").json()["students"], 144)
        for endpoint in ("/api/session", "/api/students", "/api/alerts", "/api/admin/audit"):
            response = self.client.get(endpoint, headers={"X-Role": "admin", "X-User-Id": "admin", "X-Counselor-Id": "C01"})
            self.assertEqual(response.status_code, 401)

    def test_cookie_login_fresh_session_logout_and_origin(self):
        self.assertEqual(self.client.post("/api/login", json={"username": "admin", "password": "wrong"}).status_code, 401)
        response = self.login("C01")
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie); self.assertIn("samesite=strict", cookie)
        session = self.client.get("/api/session")
        self.assertEqual(session.json()["user"]["role"], "counselor")
        self.assertEqual(session.headers["cache-control"], "no-store")
        self.assertEqual(self.client.post("/api/logout", headers={"Origin": "https://unrelated.invalid"}).status_code, 403)
        self.assertEqual(self.client.get("/api/session").status_code, 200)
        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/session").status_code, 401)

    def test_counselor_scope_and_privileged_endpoints(self):
        self.login("C01")
        listing = self.client.get("/api/students").json()
        with self.core.connection() as db:
            expected = {r[0] for r in db.execute("SELECT id FROM students WHERE counselor_id='C01'")}
        self.assertEqual({s["id"] for s in listing["items"]}, expected)
        self.assertEqual(self.client.get("/api/overview").json()["students"], len(expected))
        self.assertEqual(self.client.get("/api/students/" + self.other["id"]).status_code, 403)
        self.assertEqual(self.client.get("/api/alerts/" + self.foreign_alert["id"]).status_code, 403)
        self.assertEqual(self.client.post("/api/recompute", headers={"X-Role": "admin"}).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/ai").status_code, 403)
        self.assertEqual(self.client.get("/api/import/template?type=students").status_code, 403)

    def test_student_scope_and_write_separation(self):
        self.login(self.subject["id"])
        self.assertEqual(self.client.get("/api/students").json()["total"], 1)
        self.assertEqual(self.client.get("/api/students/" + self.subject["id"]).status_code, 200)
        self.assertEqual(self.client.get("/api/students/" + self.other["id"]).status_code, 403)
        self.assertEqual(self.client.post("/api/alerts/" + self.alert["id"] + "/followup", json={"status": "contacted", "note": "尝试修改"}).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/audit").status_code, 403)

    def test_curriculum_facts_and_original_pdf_are_accessible(self):
        self.login("C01")
        plans = self.client.get("/api/curriculum").json()["majors"]
        expected = {"CS": (173, 69, 102), "SE": (170, 64, 95)}
        for plan in plans:
            total, professional, count = expected[plan["id"]]
            self.assertEqual(plan["totalCredits"], total)
            self.assertEqual(len(plan["courses"]), count)
            self.assertEqual(sum(c["credits"] for c in plan["courses"] if c["module"] == "专业"), professional)
            self.assertEqual(sum(c["credits"] for c in plan["courses"] if c["module"] == "通识" and (c["required"] or c.get("language") == "en")), 64)
            self.assertEqual(len({c["code"] for c in plan["courses"]}), count)
            pdf = self.client.get("/api/sources/" + plan["id"])
            self.assertEqual(pdf.status_code, 200); self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_notifications_read_are_scoped_and_persist(self):
        self.login("C01")
        before = self.client.get("/api/notifications").json()
        target = next(n for n in before["items"] if not n["read"])
        self.assertEqual(self.client.post(f"/api/notifications/{target['id']}/read").status_code, 200)
        after = self.client.get("/api/notifications").json()
        self.assertEqual(after["unread"], before["unread"] - 1)
        self.assertTrue(next(n for n in after["items"] if n["id"] == target["id"])["read"])
        self.login("C02")
        self.assertEqual(self.client.post(f"/api/notifications/{target['id']}/read").status_code, 403)

    def test_followup_full_order_audit_and_close_note(self):
        self.login("C01")
        endpoint = "/api/alerts/" + self.alert["id"]
        self.assertEqual(self.client.post(endpoint + "/followup", json={"status": "closed", "note": "不能跳过复查"}).status_code, 409)
        for state in ("contacted", "supporting", "review"):
            response = self.client.post(endpoint + "/followup", json={"status": state, "note": "验收：" + state, "plan": "每周一次答疑", "reviewOn": "2026-10-29"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["alert"]["status"], state)
        self.assertEqual(self.client.post(endpoint + "/followup", json={"status": "closed", "note": "  "}).status_code, 422)
        response = self.client.post(endpoint + "/followup", json={"status": "closed", "note": "验收：已完成复查并说明结案理由"})
        self.assertEqual(response.status_code, 200)
        detail = self.client.get(endpoint).json()
        self.assertEqual(detail["alert"]["status"], "closed")
        self.assertEqual(detail["allowedTransitions"], [])
        self.assertEqual(len([e for e in detail["events"] if e["note"].startswith("验收：")]), 4)
        self.assertEqual(self.client.post(endpoint + "/followup", json={"status": "contacted", "note": "不允许倒退"}).status_code, 409)

    def test_csv_export_scope_and_formula_escape(self):
        with self.core.connection() as db:
            db.execute("UPDATE students SET name=? WHERE id=?", ("=1+1", self.alert_student["id"]))
        self.login("C01")
        response = self.client.get("/api/export")
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
        with self.core.connection() as db:
            visible = {r[0] for r in db.execute("SELECT id FROM students WHERE counselor_id='C01'")}
        self.assertTrue(rows); self.assertTrue(all(row["学号"] in visible for row in rows))
        self.assertTrue(all(row["姓名"] == "'=1+1" for row in rows if row["学号"] == self.alert_student["id"]))

    def test_duplicate_course_code_cannot_inflate_credits(self):
        self.login("admin")
        with self.core.connection() as db:
            course = dict(db.execute("SELECT * FROM courses WHERE major='CS' ORDER BY id LIMIT 1").fetchone())
            before = db.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        report = self.upload("courses", [{"id": "TEST:DUPLICATE", "code": course["code"], "name": "重复课程", "major": "CS", "credits": 3, "category": "专业", "semester": 1, "required": 1}])
        self.assertEqual(report["inserted"], 0); self.assertEqual(len(report["errors"]), 1)
        self.assertFalse(report["recomputed"])
        with self.core.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM courses").fetchone()[0], before)

    def test_invalid_numeric_and_missing_grade_inputs_are_rejected(self):
        self.login("admin")
        with self.core.connection() as db:
            course_id = db.execute("SELECT id FROM courses WHERE major=? LIMIT 1", (self.subject["major"],)).fetchone()[0]
        rows = [{"student_id": self.subject["id"], "course_id": course_id, "term": self.core.TERM, "score": value, "state": "completed"} for value in ("-1", "101", "nan", "inf", "-inf", "")]
        report = self.upload("records", rows)
        self.assertEqual(len(report["errors"]), 6)
        self.assertEqual(report["inserted"] + report["updated"], 0)
        self.assertEqual([e["row"] for e in report["errors"]], list(range(2, 8)))
        courses = [{"id": "TEST:NUM" + str(i), "code": "TESTNUM" + str(i), "name": "数值校验", "major": "CS", "credits": value, "category": "专业", "semester": 1, "required": 1} for i, value in enumerate(("-2", "nan", "inf"))]
        report = self.upload("courses", courses)
        self.assertEqual(len(report["errors"]), 3); self.assertFalse(report["recomputed"])

    def test_future_import_does_not_change_current_academic_facts(self):
        self.login("admin")
        sid = self.subject["id"]
        before = self.client.get("/api/students/" + sid).json()
        with self.core.connection() as db:
            cid = db.execute("SELECT id FROM courses WHERE major=? AND semester=8 LIMIT 1", (self.subject["major"],)).fetchone()[0]
        report = self.upload("records", [{"student_id": sid, "course_id": cid, "term": "2028-2029-2", "score": 20, "state": "completed"}])
        self.assertEqual(report["inserted"], 1); self.assertEqual(report["errors"], [])
        after = self.client.get("/api/students/" + sid).json()
        for name in ("gpa", "earnedCredits", "failedCourses", "failedCredits", "latestScore", "latestGradedTerm", "selectedCredits"):
            self.assertEqual(before["metrics"][name], after["metrics"][name], name)
        self.assertEqual(before["trend"], after["trend"])

    def test_existing_records_prevent_direct_major_overwrite(self):
        self.login("admin")
        row = {**self.subject, "major": "SE"}
        report = self.upload("students", [row])
        self.assertEqual(len(report["errors"]), 1); self.assertEqual(report["updated"], 0)
        with self.core.connection() as db:
            self.assertEqual(db.execute("SELECT major FROM students WHERE id=?", (self.subject["id"],)).fetchone()[0], "CS")

    def test_new_student_import_creates_demo_login_and_receives_warning(self):
        self.login("admin")
        sid = "2026CS999"
        report = self.upload("students", [{"id": sid, "name": "新导入验收学生", "major": "CS", "cohort": 2026, "class_name": "验收26班", "counselor_id": "C01"}])
        self.assertEqual(report["inserted"], 1); self.assertEqual(report["errors"], [])
        with self.core.connection() as db:
            cid = db.execute("SELECT id FROM courses WHERE major='CS' AND semester=1 AND required=1 LIMIT 1").fetchone()[0]
        report = self.upload("records", [{"student_id": sid, "course_id": cid, "term": self.core.TERM, "score": 40, "state": "completed"}])
        self.assertEqual(report["inserted"], 1); self.assertEqual(report["errors"], [])
        self.login(sid)
        self.assertEqual(self.client.get("/api/session").json()["user"]["role"], "student")
        alerts = self.client.get("/api/alerts").json()["items"]
        self.assertTrue(alerts); self.assertTrue(all(a["studentId"] == sid for a in alerts))
        self.assertTrue(self.client.get("/api/notifications").json()["items"])
        self.login("C01")
        notices = self.client.get("/api/notifications").json()["items"]
        self.assertTrue(any(n["alertId"] in {a["id"] for a in alerts} for n in notices))

    def test_import_recompute_failure_rolls_back_rows_and_new_account(self):
        sid = "2026CS998"
        body = "id,name,major,cohort,class_name,counselor_id\n2026CS998,事务回滚样例,CS,2026,验收26班,C01\n"
        with TestClient(self.app, raise_server_exceptions=False) as failing_client:
            self.assertEqual(failing_client.post("/api/login", json={"username": "admin", "password": "demo123"}).status_code, 200)
            with patch("server.academic.recompute", side_effect=RuntimeError("forced acceptance failure")), patch("server.main.logging.exception"):
                response = failing_client.post("/api/import?type=students", files={"file": ("rollback.csv", body.encode("utf-8"), "text/csv")})
            self.assertEqual(response.status_code, 500)
        with self.core.connection() as db:
            self.assertIsNone(db.execute("SELECT id FROM students WHERE id=?", (sid,)).fetchone())
            self.assertIsNone(db.execute("SELECT id FROM users WHERE id=?", (sid,)).fetchone())

    def test_reassignment_reroutes_notification_and_removes_old_visibility(self):
        self.login("admin")
        report = self.upload("students", [{**self.alert_student, "counselor_id": "C02"}])
        self.assertEqual(report["updated"], 1); self.assertEqual(report["errors"], [])
        self.login("C02")
        self.assertEqual(self.client.get("/api/students/" + self.alert_student["id"]).status_code, 200)
        notices = self.client.get("/api/notifications").json()["items"]
        self.assertTrue(any(n["alertId"] == self.alert["id"] for n in notices))
        self.login("C01")
        self.assertEqual(self.client.get("/api/students/" + self.alert_student["id"]).status_code, 403)
        self.assertFalse(any(n["alertId"] == self.alert["id"] for n in self.client.get("/api/notifications").json()["items"]))

    def test_assistant_local_uses_grounded_tools_and_respects_scope(self):
        self.login("C01")
        sid = self.subject["id"]
        facts = self.client.get("/api/students/" + sid).json()
        response = self.client.post("/api/assistant", json={"message": "解释这名学生的学情与学分", "studentId": sid})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["mode"], "local")
        self.assertEqual(data["steps"][0]["tool"], "student_brief")
        self.assertIn(str(facts["credits"]["earned"]), data["answer"])
        self.assertIn(sid, data["answer"]); self.assertTrue(data["sources"])
        denied = self.client.post("/api/assistant", json={"message": "查看学情", "studentId": self.other["id"]})
        self.assertEqual(denied.status_code, 403)

    def test_remote_failure_falls_back_without_real_network(self):
        self.login("admin")
        response = self.client.put("/api/admin/ai", json={"mode": "remote", "baseUrl": "https://model.example.invalid/v1", "model": "acceptance-mock", "apiKey": "synthetic-test-placeholder"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("synthetic-test-placeholder", response.text)
        with self.core.connection() as db:
            self.assertNotIn("synthetic-test-placeholder", db.execute("SELECT value FROM settings WHERE key='ai'").fetchone()[0])
        self.login(self.subject["id"])
        with patch("server.assistant.model_request", side_effect=TimeoutError("mock timeout")) as provider:
            response = self.client.post("/api/assistant", json={"message": "我的学情怎样"})
        self.assertEqual(response.status_code, 200); provider.assert_called_once()
        self.assertEqual(response.json()["mode"], "local-fallback")
        self.assertEqual(response.json()["steps"][0]["tool"], "student_brief")
        self.assertIn(self.subject["id"], response.json()["answer"])

    def test_remote_tool_call_cannot_cross_student_permission(self):
        self.login("admin")
        self.client.put("/api/admin/ai", json={"mode": "remote", "baseUrl": "https://model.example.invalid/v1", "model": "acceptance-mock"})
        self.login(self.subject["id"])
        invented = {"tool_calls": [{"function": {"name": "student_brief", "arguments": json.dumps({"studentId": self.other["id"]})}}]}
        with patch("server.assistant.model_request", return_value=invented):
            response = self.client.post("/api/assistant", json={"message": "我的成绩"})
        self.assertEqual(response.status_code, 403)

    def test_student_plan_is_owned_persistent_and_visible_to_counselor(self):
        sid = self.alert_student["id"]
        self.login(sid)
        self.assertEqual(self.client.get("/api/my/plan").json()["tasks"], [])
        self.assertEqual(self.client.post("/api/my/plan", json={"title": "  "}).status_code, 422)
        self.assertEqual(self.client.post("/api/my/plan", json={"title": "核对补修", "dueDate": "2026-13-01"}).status_code, 422)
        self.assertEqual(self.client.post("/api/my/plan", json={"title": "核对补修", "alertId": self.foreign_alert["id"]}).status_code, 403)
        response = self.client.post("/api/my/plan", json={"title": "预约课程答疑", "dueDate": "2026-10-29", "alertId": self.alert["id"]})
        self.assertEqual(response.status_code, 200)
        task = response.json()["tasks"][0]
        self.assertFalse(task["completed"])
        response = self.client.patch(f"/api/my/plan/{task['id']}", json={"completed": True})
        self.assertEqual(response.status_code, 200); self.assertTrue(response.json()["tasks"][0]["completed"])
        self.login("C01")
        self.assertTrue(self.client.get(f"/api/students/{sid}/plan").json()["tasks"][0]["completed"])
        self.assertEqual(self.client.post("/api/my/plan", json={"title": "老师不能代填学生个人计划"}).status_code, 403)
        self.login(self.other["id"])
        self.assertEqual(self.client.patch(f"/api/my/plan/{task['id']}", json={"completed": False}).status_code, 404)
        self.assertEqual(self.client.get(f"/api/students/{sid}/plan").status_code, 403)

    def test_student_feedback_adds_event_and_notification_without_changing_status(self):
        aid = self.alert["id"]
        with self.core.connection() as db:
            before_events = db.execute("SELECT COUNT(*) FROM case_events WHERE alert_id=?", (aid,)).fetchone()[0]
            before_notices = db.execute("SELECT COUNT(*) FROM notifications WHERE alert_id=? AND owner_id='C01'", (aid,)).fetchone()[0]
        self.login(self.alert_student["id"])
        response = self.client.post(f"/api/alerts/{aid}/feedback", json={"note": "已完成第一章复习，准备周四答疑。"})
        self.assertEqual(response.status_code, 200)
        with self.core.connection() as db:
            alert = dict(db.execute("SELECT * FROM alerts WHERE id=?", (aid,)).fetchone())
            self.assertEqual(alert["status"], self.alert["status"]); self.assertEqual(alert["active"], self.alert["active"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM case_events WHERE alert_id=?", (aid,)).fetchone()[0], before_events + 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notifications WHERE alert_id=? AND owner_id='C01'", (aid,)).fetchone()[0], before_notices + 1)
            event = db.execute("SELECT action,actor_id FROM case_events WHERE alert_id=? ORDER BY id DESC LIMIT 1", (aid,)).fetchone()
            self.assertEqual(tuple(event), ("student_feedback", self.alert_student["id"]))
        self.login("C01")
        self.assertIn("第一章复习", self.client.get(f"/api/alerts/{aid}").json()["events"][-1]["note"])
        self.login(self.other["id"])
        self.assertEqual(self.client.post(f"/api/alerts/{aid}/feedback", json={"note": "他人不得修改"}).status_code, 404)

    def test_recompute_is_idempotent_for_notifications_and_cases(self):
        self.login("admin")
        with self.core.connection() as db:
            before = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("alerts", "notifications", "case_events")}
        response = self.client.post("/api/recompute")
        self.assertEqual(response.status_code, 200); self.assertEqual(response.json()["created"], 0)
        with self.core.connection() as db:
            after = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
