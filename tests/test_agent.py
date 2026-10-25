"""Conversation, grounding, tool protocol and explicit proposal application tests.

All provider replies are mocked. No credentials or external model service are used.
Each test uses a private copy of a small newly seeded database.
"""
from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient


def call(name, args=None, identifier="call_a"):
    return {"content": None, "tool_calls": [{"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}]}


class AgentAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="agent-", dir=Path(__file__).resolve().parent)
        cls.root = Path(cls.directory.name)
        cls.environment = {k: os.environ.get(k) for k in ("ZHIXUE_DB", "ZHIXUE_DEMO", "ZHIXUE_API_KEY")}
        os.environ["ZHIXUE_DB"] = str(cls.root / "bootstrap.sqlite3")
        os.environ["ZHIXUE_DEMO"] = "1"
        os.environ.pop("ZHIXUE_API_KEY", None)
        from server import core, assistant, planning
        from server.seed import ensure_demo
        from server.main import app
        cls.core, cls.assistant, cls.app = core, assistant, app
        ensure_demo(count=24)
        with core.connection() as db:
            planning.seed_demo_support(db)
            with closing(sqlite3.connect(cls.root / "base.sqlite3")) as output:
                db.backup(output)

    @classmethod
    def tearDownClass(cls):
        for key, value in cls.environment.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        assert cls.root.resolve().is_relative_to(Path(__file__).resolve().parent)
        cls.directory.cleanup()

    def setUp(self):
        os.environ["ZHIXUE_DB"] = str(self.root / (self._testMethodName + ".sqlite3"))
        with closing(sqlite3.connect(self.root / "base.sqlite3")) as source:
            with closing(sqlite3.connect(os.environ["ZHIXUE_DB"])) as output:
                source.backup(output)
        self.old_key = self.assistant.memory_key
        self.assistant.memory_key = ""
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.se = "2024SE002"
        self.cs = "2024CS013"
        self.login(self.se)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.assistant.memory_key = self.old_key

    def login(self, username):
        self.client.cookies.clear()
        response = self.client.post("/api/login", json={"username": username, "password": "demo123"})
        self.assertEqual(response.status_code, 200, response.text)

    def remote(self):
        self.login("admin")
        response = self.client.put("/api/admin/ai", json={"mode": "remote", "baseUrl": "https://provider.example.invalid/v1", "model": "mock-model", "apiKey": "synthetic-test-placeholder"})
        self.assertEqual(response.status_code, 200)
        self.login(self.se)

    def ask(self, message, **kwargs):
        response = self.client.post("/api/assistant", json={"message": message, **kwargs})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_software_student_implicit_major_is_correct(self):
        result = self.ask("我的毕业要求是什么？")
        self.assertIn("软件工程", result["answer"])
        self.assertIn("170", result["answer"])
        self.assertTrue(result["answer"].startswith("软件工程毕业总学分为 170"))
        self.assertNotIn("毕业总学分为 173", result["answer"])
        self.assertEqual([s["tool"] for s in result["steps"]], ["curriculum_rules", "audit_curriculum"])
        self.assertNotIn("当前风险依据", result["answer"])
        self.assertTrue(any(s["tool"] == "audit_curriculum" for s in result["steps"]))

    def test_unknown_counselor_major_requests_clarification(self):
        self.login("C01")
        result = self.ask("毕业要求是什么？")
        self.assertIn("请指定", result["answer"])
        self.assertNotIn("173", result["answer"])
        self.assertNotIn("170", result["answer"])

    def test_thread_context_pronouns_and_persisted_messages(self):
        self.login("C02")
        first = self.ask("查看这位同学的学情", studentId=self.se)
        second = self.ask("那下学期应该怎么安排？", threadId=first["threadId"])
        tools = {s["tool"] for s in second["steps"] if s["status"] == "completed"}
        self.assertTrue({"student_brief", "audit_curriculum", "plan_courses", "draft_action_plan"}.issubset(tools))
        self.assertNotIn("case_history", tools)
        self.assertTrue(second["proposals"])
        self.assertEqual(second["proposals"][0]["studentId"], self.se)
        stored = self.client.get("/api/assistant/threads/" + first["threadId"]).json()
        self.assertEqual(stored["studentId"], self.se)
        self.assertEqual([m["role"] for m in stored["messages"]], ["user", "assistant", "user", "assistant"])
        self.assertEqual(stored["messages"][-1]["content"], second["answer"])

    def test_threads_cannot_be_read_or_continued_by_another_user(self):
        own = self.ask("我的学情怎样")
        self.login(self.cs)
        self.assertEqual(self.client.get("/api/assistant/threads/" + own["threadId"]).status_code, 404)
        self.assertEqual(self.client.post("/api/assistant", json={"message": "继续", "threadId": own["threadId"]}).status_code, 404)
        self.assertFalse(any(t["id"] == own["threadId"] for t in self.client.get("/api/assistant/threads").json()["items"]))

    def test_reassignment_revokes_old_conversation_evidence(self):
        self.login("C02")
        own = self.ask("查看学情", studentId=self.se)
        with self.core.connection() as db:
            db.execute("UPDATE students SET counselor_id='C03' WHERE id=?", (self.se,))
        self.assertEqual(self.client.get("/api/assistant/threads/" + own["threadId"]).status_code, 403)
        self.assertEqual(self.client.get("/api/assistant/threads").json()["items"], [])

    def test_model_reads_tool_result_then_adaptively_calls_again(self):
        self.remote()
        seen = []
        def provider(messages, tools=None):
            seen.append(deepcopy(messages))
            if len(seen) == 1:
                return call("student_brief", {}, "profile_call")
            if len(seen) == 2:
                self.assertEqual(messages[-2]["role"], "assistant")
                self.assertEqual(messages[-1]["role"], "tool")
                self.assertEqual(messages[-1]["tool_call_id"], "profile_call")
                data = json.loads(messages[-1]["content"])["data"]
                self.assertEqual(data["student"]["major"], "SE")
                return call("curriculum_rules", {"major": data["student"]["major"]}, "curriculum_call")
            self.assertEqual(messages[-1]["tool_call_id"], "curriculum_call")
            self.assertEqual(json.loads(messages[-1]["content"])["data"]["totalCredits"], 170)
            return {"content": "软件工程毕业总学分为170，仍须满足所选模块要求。[S2]"}
        with patch("server.assistant.model_request", side_effect=provider) as mocked:
            result = self.ask("结合我的情况核对毕业要求")
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(result["mode"], "remote")
        self.assertIn("170", result["answer"])
        self.assertEqual([s["tool"] for s in result["steps"]], ["student_brief", "curriculum_rules"])

    def test_actual_transport_payload_uses_auto_and_preserves_tool_ids(self):
        self.remote()
        messages = [{"role": "assistant", **call("student_brief", {}, "transport_call")},
                    {"role": "tool", "tool_call_id": "transport_call", "name": "student_brief", "content": '{"credits":170}'}]
        response = httpx.Response(200, json={"choices": [{"message": {"content": "已读取"}}]}, request=httpx.Request("POST", "https://provider.example.invalid/v1/chat/completions"))
        fake = MagicMock(); fake.__enter__.return_value = fake; fake.post.return_value = response
        with patch("server.assistant.httpx.Client", return_value=fake):
            self.assertEqual(self.assistant.model_request(messages, self.assistant.TOOLS)["content"], "已读取")
        sent = fake.post.call_args.kwargs["json"]
        self.assertEqual(sent["tool_choice"], "auto")
        self.assertEqual(sent["messages"][-1]["tool_call_id"], "transport_call")
        self.assertTrue(fake.post.call_args.args[0].endswith("/v1/chat/completions"))

    def test_prior_conversation_is_in_followup_model_context(self):
        first = self.ask("我的毕业要求是什么")
        self.remote()
        calls = []
        def provider(messages, tools=None):
            calls.append(deepcopy(messages))
            if len(calls) == 1:
                self.assertTrue(any(m["role"] == "user" and m["content"] == "我的毕业要求是什么" for m in messages))
                self.assertTrue(any(m["role"] == "assistant" and "软件工程" in m["content"] for m in messages))
                return call("student_brief")
            return {"content": "已结合当前学情核对，请继续查看所选培养路径。[S1]"}
        with patch("server.assistant.model_request", side_effect=provider):
            result = self.ask("那我接下来呢", threadId=first["threadId"])
        self.assertEqual(result["threadId"], first["threadId"])
        self.assertEqual(result["mode"], "remote")

    def test_provider_exception_after_tool_keeps_work_and_finishes_locally(self):
        self.remote()
        with patch("server.assistant.model_request", side_effect=[call("student_brief"), TimeoutError("mock")]) as mocked:
            result = self.ask("请制定我的学习行动计划")
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(result["mode"], "local-fallback")
        self.assertEqual(sum(s["tool"] == "student_brief" for s in result["steps"]), 1)
        self.assertTrue(result["warnings"]); self.assertTrue(result["proposals"])
        self.assertTrue(any(s["tool"] == "plan_courses" for s in result["steps"]))

    def test_malformed_arguments_and_unknown_tools_do_not_mutate(self):
        self.remote()
        malformed = {"tool_calls": [
            {"id": "x", "function": {"name": "student_brief", "arguments": "{broken"}},
            {"id": "y", "function": {"name": "delete_student", "arguments": "{}"}}]}
        with patch("server.assistant.model_request", side_effect=[malformed, {"content": "你已获得9999学分"}]):
            result = self.ask("解释我的学情")
        self.assertEqual(result["mode"], "local-fallback")
        self.assertNotIn("9999", result["answer"])
        self.assertEqual(sum(s["status"] == "error" for s in result["steps"]), 2)
        with self.core.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM students").fetchone()[0], 24)

    def test_no_tool_bogus_numeric_response_is_replaced_with_real_queries(self):
        self.remote()
        with patch("server.assistant.model_request", return_value={"content": "已获得9999学分，可以毕业。"}):
            result = self.ask("我的学情如何")
        self.assertEqual(result["mode"], "local-fallback")
        self.assertNotIn("9999", result["answer"])
        self.assertGreaterEqual(len([s for s in result["steps"] if s["status"] == "completed"]), 2)

    def test_numeric_claim_not_present_in_completed_tools_is_guarded(self):
        self.remote()
        with patch("server.assistant.model_request", side_effect=[call("student_brief"), {"content": "你的累计学分9999，已达到毕业要求。[S1]"}]):
            result = self.ask("核对我的学分")
        self.assertEqual(result["mode"], "local-fallback")
        self.assertNotIn("9999", result["answer"])
        self.assertTrue(any("数字" in warning for warning in result["warnings"]))

    def test_tool_call_cannot_access_another_student(self):
        self.remote()
        with patch("server.assistant.model_request", return_value=call("student_brief", {"studentId": self.cs})):
            response = self.client.post("/api/assistant", json={"message": "看看对方成绩"})
        self.assertEqual(response.status_code, 403)

    def test_unbounded_provider_is_stopped_and_excess_calls_rejected(self):
        self.remote()
        with patch("server.assistant.model_request", return_value=call("student_brief")) as mocked:
            result = self.ask("我的情况")
        self.assertEqual(mocked.call_count, 4)
        self.assertEqual(result["mode"], "local-fallback")
        too_many = {"tool_calls": [call("student_brief", identifier=str(i))["tool_calls"][0] for i in range(11)]}
        with patch("server.assistant.model_request", return_value=too_many) as mocked:
            result = self.ask("重新核对")
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(result["mode"], "local-fallback")

    def test_draft_is_reviewable_and_apply_is_explicit_idempotent(self):
        self.login(self.cs)
        with self.core.connection() as db:
            before = db.execute("SELECT COUNT(*) FROM study_tasks WHERE student_id=?", (self.cs,)).fetchone()[0]
            statuses = [tuple(r) for r in db.execute("SELECT id,status FROM alerts WHERE student_id=? ORDER BY id", (self.cs,))]
        result = self.ask("请根据风险制定我的行动计划")
        proposal = result["proposals"][0]
        self.assertEqual(proposal["status"], "draft")
        self.assertTrue(all(i["title"] and i["description"] and i["dueDate"] for i in proposal["items"]))
        with self.core.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM study_tasks WHERE student_id=?", (self.cs,)).fetchone()[0], before)
        endpoint = "/api/assistant/proposals/" + proposal["id"] + "/apply"
        first = self.client.post(endpoint)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(endpoint).json()
        self.assertEqual(first.json()["appliedCount"], len(proposal["items"]))
        self.assertEqual(second["appliedCount"], 0); self.assertTrue(second["alreadyApplied"])
        self.assertEqual(first.json()["taskIds"], second["taskIds"])
        with self.core.connection() as db:
            rows = db.execute("SELECT source,assigned_by FROM study_tasks WHERE student_id=?", (self.cs,)).fetchall()
            self.assertTrue(all(r["source"] == "assistant" and r["assigned_by"] == self.cs for r in rows))
            self.assertEqual([tuple(r) for r in db.execute("SELECT id,status FROM alerts WHERE student_id=? ORDER BY id", (self.cs,))], statuses)
        history = self.client.get("/api/assistant/threads/" + result["threadId"]).json()
        self.assertEqual(history["messages"][-1]["proposals"][0]["status"], "applied")

    def test_counselor_apply_assigns_tasks_and_notifies_target_student(self):
        self.login("C02")
        result = self.ask("给这位同学拟定行动计划", studentId=self.se)
        proposal = result["proposals"][0]
        applied = self.client.post("/api/assistant/proposals/" + proposal["id"] + "/apply")
        self.assertEqual(applied.status_code, 200)
        with self.core.connection() as db:
            rows = db.execute("SELECT assigned_by,source FROM study_tasks WHERE student_id=?", (self.se,)).fetchall()
            self.assertTrue(all(r["assigned_by"] == "C02" and r["source"] == "assistant" for r in rows))
            messages = db.execute("SELECT * FROM inbox_messages WHERE user_id=? AND kind='study_task'", (self.se,)).fetchall()
            self.assertEqual(len(messages), len(proposal["items"]))

    def test_proposal_scope_is_rechecked_at_apply_time(self):
        self.login("C02")
        result = self.ask("拟定学习行动计划", studentId=self.se)
        pid = result["proposals"][0]["id"]
        self.login(self.se)
        self.assertEqual(self.client.post("/api/assistant/proposals/" + pid + "/apply").status_code, 404)
        self.login("C02")
        with self.core.connection() as db:
            db.execute("UPDATE students SET counselor_id='C03' WHERE id=?", (self.se,))
        self.assertEqual(self.client.post("/api/assistant/proposals/" + pid + "/apply").status_code, 403)
        with self.core.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM study_tasks WHERE student_id=?", (self.se,)).fetchone()[0], 0)

    def test_model_cannot_claim_counseling_write(self):
        self.remote()
        with patch("server.assistant.model_request", side_effect=[call("student_brief"), {"content": "已经帮你结案。[S1]"}]):
            result = self.ask("帮我结案")
        self.assertEqual(result["mode"], "local-fallback")
        self.assertNotIn("已经帮你结案", result["answer"])

    def test_missing_provider_credentials_is_honest_local_fallback(self):
        self.login("admin")
        self.client.put("/api/admin/ai", json={"mode": "remote", "baseUrl": "https://provider.example.invalid/v1", "model": "mock-model"})
        self.assistant.memory_key = ""
        self.login(self.se)
        with patch("server.assistant.httpx.Client") as network:
            result = self.ask("接下来该做什么")
        network.assert_not_called()
        self.assertEqual(result["mode"], "local-fallback")
        self.assertTrue(result["warnings"])

    def test_named_course_is_checked_with_existing_selection(self):
        from server import planning
        with self.core.connection() as db:
            base = {r[0] for r in db.execute("SELECT course_id FROM records WHERE student_id=? AND term=? AND state!='withdrawn'", (self.se, self.core.TERM))}
            target = db.execute("SELECT id FROM courses WHERE major='SE' AND name='深度学习'").fetchone()[0]
        original = planning.check_plan
        with patch("server.planning.check_plan", wraps=original) as checker:
            result = self.ask("我想选深度学习，会冲突吗？")
        self.assertIn("search_courses", [s["tool"] for s in result["steps"]])
        self.assertIn("check_course_plan", [s["tool"] for s in result["steps"]])
        self.assertEqual(set(checker.call_args.args[3]), base | {target})
        self.assertIn("先修", result["answer"])
        first_paragraph = result["answer"].split("\n\n")[0]
        self.assertTrue(first_paragraph.startswith("当前组合未通过检查"))
        self.assertIn("深度学习", first_paragraph)
        self.assertLessEqual(len(result["answer"].split("\n\n")), 2)
        self.assertEqual(result["proposals"], [])

    def test_saved_combination_and_course_pronoun_followup_use_target_term(self):
        from server import planning
        with self.core.connection() as db:
            plan = planning.get_planning(db, self.se)
            baseline = [next(o["courseId"] for o in plan["offerings"] if o["selected"])]
            planning.save_plan(db, self.se, self.core.TERM, baseline, "手工保留组合", "验收", self.se)
            target = db.execute("SELECT id FROM courses WHERE major='SE' AND name='深度学习'").fetchone()[0]
        original = planning.check_plan
        with patch("server.planning.check_plan", wraps=original) as checker:
            first = self.ask("检查深度学习的先修和课表")
        self.assertEqual(set(checker.call_args.args[3]), set(baseline) | {target})
        with patch("server.planning.check_plan", wraps=original) as checker:
            second = self.ask("那下学期这门课呢？", threadId=first["threadId"])
        self.assertEqual(checker.call_args.args[2], planning.next_term(self.core.TERM))
        self.assertIn(target, checker.call_args.args[3])
        self.assertTrue(any(planning.next_term(self.core.TERM) in c["title"] for c in second["citations"]))

    def test_model_can_resolve_course_then_check_using_returned_ids(self):
        self.remote()
        captured = []
        def provider(messages, tools=None):
            captured.append(deepcopy(messages))
            if len(captured) == 1:
                return call("search_courses", {"query": "深度学习"}, "find_course")
            if len(captured) == 2:
                found = json.loads(messages[-1]["content"])["data"]
                self.assertTrue(found["matches"][0]["courseId"].startswith("SE:"))
                self.assertIn("slots", found["matches"][0])
                ids = list(dict.fromkeys([*found["baseCourseIds"], found["matches"][0]["courseId"]]))
                return call("check_course_plan", {"term": found["term"], "courseIds": ids}, "check_combination")
            checked = json.loads(messages[-1]["content"])["data"]
            self.assertTrue(any(c["kind"] == "prerequisite" for c in checked["conflicts"]))
            return {"content": "该组合存在先修条件未满足的问题，请先核对机器学习修读记录。[S2]"}
        with patch("server.assistant.model_request", side_effect=provider):
            result = self.ask("我能选深度学习吗")
        self.assertEqual(result["mode"], "remote")
        self.assertEqual([s["tool"] for s in result["steps"]], ["search_courses", "check_course_plan"])

    def test_archived_tasks_are_not_counted_as_current_actions(self):
        with self.core.connection() as db:
            db.execute("INSERT INTO study_tasks(student_id,title,due_date,updated_at,archived) VALUES (?,?,?,?,1)", (self.se, "已经归档的旧任务", "", self.core.now()))
        result = self.ask("看看我的跟进进展")
        history_step = next(s for s in result["steps"] if s["tool"] == "case_history")
        self.assertIn("0 项学习行动", history_step["summary"])
        self.assertNotIn("已经归档的旧任务", result["answer"])

    def test_credit_question_omits_unrelated_risk_and_gpa(self):
        result = self.ask("我的学分进度怎么样？")
        self.assertEqual([s["tool"] for s in result["steps"]], ["student_brief", "audit_curriculum"])
        self.assertIn("已获", result["answer"].split("\n\n")[0])
        self.assertNotIn("累计演示绩点", result["answer"])
        self.assertNotIn("当前风险依据", result["answer"])

    def test_warning_question_leads_with_trigger_evidence(self):
        self.login(self.cs)
        result = self.ask("我为什么收到预警？")
        self.assertEqual(result["steps"][0]["tool"], "list_student_alerts")
        self.assertTrue(result["answer"].startswith("当前风险依据："))
        self.assertNotIn("curriculum_rules", [s["tool"] for s in result["steps"]])

    def test_unique_exact_course_does_not_request_unnecessary_disambiguation(self):
        result = self.ask("下学期想选操作系统，会冲突吗？")
        search = next(s for s in result["steps"] if s["tool"] == "search_courses")
        self.assertIn("精确匹配：操作系统", search["summary"])
        self.assertIn("相关课程：操作系统实验", result["answer"])
        self.assertNotIn("请明确选择课程", result["answer"])
        self.assertIn("check_course_plan", [s["tool"] for s in result["steps"]])

    def test_explicit_name_switch_beats_previous_student_and_stale_ui_id(self):
        self.login("C01")
        first = self.ask("查看这位同学", studentId="2024CS001")
        with self.core.connection() as db:
            name = db.execute("SELECT name FROM students WHERE id=?", (self.cs,)).fetchone()[0]
        second = self.ask("查一下" + name + "的学情", threadId=first["threadId"], studentId="2024CS001")
        self.assertEqual(second["studentId"], self.cs)
        self.assertIn(self.cs, second["answer"])
        third = self.ask("他的学分呢？", threadId=first["threadId"], studentId="2024CS001")
        self.assertEqual(third["studentId"], self.cs)
        self.assertIn(self.cs, third["answer"])
        override = self.ask("查看这位同学的学分", threadId=first["threadId"], studentId="2024CS001", contextOverride=True)
        self.assertEqual(override["studentId"], "2024CS001")

    def test_ambiguous_name_clears_focus_instead_of_reusing_previous_person(self):
        self.login("C01")
        first = self.ask("查看这位同学", studentId="2024CS001")
        with self.core.connection() as db:
            name = db.execute("SELECT name FROM students WHERE id=?", (self.cs,)).fetchone()[0]
            db.execute("INSERT INTO students VALUES (?,?,?,?,?,?)", ("2024CS998", name, "CS", 2024, "同名验收班", "C01"))
        result = self.ask("查一下" + name + "的学情", threadId=first["threadId"], studentId="2024CS001")
        self.assertIsNone(result["studentId"])
        self.assertIn("多位学生", result["answer"])
        self.assertNotIn("已获", result["answer"])
        resolved = self.ask("选择 " + self.cs, threadId=first["threadId"])
        self.assertEqual(resolved["studentId"], self.cs)

    def test_draft_requeries_wrong_student_and_wrong_term_cached_evidence(self):
        from server import planning
        self.remote(); self.login("admin")
        original = planning.get_planning
        def marked(db, sid, term=None):
            result = original(db, sid, term)
            result["recommended"]["courses"] = [{"name": "甲专属课程" if sid == self.cs else "乙专属课程"}]
            return result
        first = {"tool_calls": [call("plan_courses", {"studentId": self.cs, "term": planning.next_term(self.core.TERM)}, "plan_a")["tool_calls"][0],
                                call("audit_curriculum", {"studentId": self.cs}, "audit_a")["tool_calls"][0]]}
        with patch("server.planning.get_planning", side_effect=marked) as planner, patch("server.assistant.model_request", side_effect=[first, call("draft_action_plan", {"studentId": self.se, "term": self.core.TERM}), {"content": "行动草案已生成，请检查后采纳。"}]):
            result = self.ask("请为这位同学安排学习行动", studentId=self.se)
        self.assertEqual(result["studentId"], self.se)
        self.assertEqual(result["proposals"][0]["studentId"], self.se)
        descriptions = " ".join(i["description"] for i in result["proposals"][0]["items"])
        self.assertIn("乙专属课程", descriptions)
        self.assertNotIn("甲专属课程", descriptions)
        self.assertTrue(any(c.args[1:] == (self.se, self.core.TERM) for c in planner.call_args_list))

    def test_critical_numeric_guard_binds_field_subject_and_negation(self):
        from server.agent_runtime import ToolSession, guarded_answer
        session = ToolSession({"id": "admin", "role": "admin"}, "test", self.se)
        profile = {"student": {"id": self.se, "name": "乙同学", "gpa": 3.0}, "credits": {"earned": 80, "total": 170, "remaining": 90},
                   "metrics": {"failedCourses": 3, "currentGradesPending": False, "dataQuality": {"hasAssessments": True}}}
        session.results = [{"tool": "student_brief", "data": profile, "studentId": self.se, "sourceIds": ["S1"]}]
        session.citations = [{"id": "S1", "title": "乙同学当前学情"}]
        for claim in ("已修170学分，全部通过。[S1]", "已修170学分。[S1]", "没有挂科。[S1]", "已修不是80学分。[S1]"):
            with self.subTest(claim=claim): self.assertIsNone(guarded_answer(claim, session)[0])
        for claim in ("已修80学分，未通过3门。[S1]", "并非全部通过，未通过3门。[S1]", "已修不是170学分，而是80学分。[S1]"):
            with self.subTest(claim=claim): self.assertIsNotNone(guarded_answer(claim, session)[0])
        other = deepcopy(profile); other["student"].update(id=self.cs, name="甲同学"); other["credits"]["earned"] = 90
        session.results.append({"tool": "student_brief", "data": other, "studentId": self.cs, "sourceIds": ["S2"]})
        session.citations.append({"id": "S2", "title": "甲同学当前学情"})
        self.assertIsNone(guarded_answer("已修80学分。[S1]", session)[0])
        self.assertIsNotNone(guarded_answer("乙同学已修80学分。[S1]", session)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
