"""Comparison evidence is server-calculated, scoped and preserved through review."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from server import core, planning
from server.agent_runtime import ToolSession, local_workflow
from server.main import app
from server.selection_risk import alternative_courses
from server.seed import ensure_demo


class PlanEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="evidence-", dir=Path(__file__).parent)
        cls.root = Path(cls.temp.name)
        with patch.dict(os.environ, {"ZHIXUE_DB":str(cls.root/"base.sqlite3")}):
            ensure_demo(count=24)
            with core.connection() as db:
                planning.seed_demo_support(db)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        path = self.root/(self._testMethodName+".sqlite3")
        with closing(sqlite3.connect(self.root/"base.sqlite3")) as source, closing(sqlite3.connect(path)) as dest:
            source.backup(dest)
        env = patch.dict(os.environ, {"ZHIXUE_DB":str(path),"ZHIXUE_DEMO":"1"})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.term = planning.next_term(core.TERM)
        with core.connection() as db:
            student = db.execute("SELECT * FROM students WHERE counselor_id='C01' ORDER BY id LIMIT 1").fetchone()
            self.sid,self.major = student["id"],student["major"]
            db.execute("DELETE FROM records WHERE student_id=?", (self.sid,))
            category = next(c for c in planning.audit_curriculum(db,self.sid)["categories"] if c["subcategories"])
            sub = next(s for s in category["subcategories"] if s["required"]>=4)
            self.ids = []
            for day,code in enumerate(("TEST-CMP-A","TEST-CMP-B"),1):
                cid=self.major+":"+code
                self.ids.append(cid)
                db.execute("INSERT INTO courses VALUES(?,?,?,?,?,?,?,?,?)",
                           (cid,code,code,self.major,2,category["name"],2,0,json.dumps({"submodule":sub["name"]})))
                slots=json.dumps([{"day":day,"start":1,"end":2,"weeks":[1,2]}])
                db.execute("INSERT INTO course_offerings VALUES(?,?,?,?,?,?,?,?)",(cid,self.term,slots,20,0,1,1,"模拟课表"))
            db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES(?,?,?,47,'completed')",
                       (self.sid,self.ids[1],core.TERM))
            planning.save_plan(db,self.sid,self.term,[self.ids[0]],"已保存参考","",self.sid)
        self.url=f"/api/students/{self.sid}"
        self.login(self.sid)

    def login(self,who):
        response=self.client.post("/api/login",json={"username":who,"password":"demo123"})
        self.assertEqual(response.status_code,200,response.text)

    def receipt(self):
        choice=self.client.post(self.url+"/selection-risk/compare",json={"courseId":self.ids[1]})
        self.assertEqual(choice.status_code,200,choice.text)
        choice=choice.json()
        result=self.client.post(self.url+"/selection-risk/record",json={"courseId":self.ids[1],"fingerprint":choice["fingerprint"]})
        self.assertEqual(result.status_code,200,result.text)
        return result.json()

    def save(self,evidence,ids=None,version=1):
        return self.client.put(self.url+"/planning",json={"term":self.term,"courseIds":ids if ids is not None else evidence["with"]["courseIds"],
            "title":"我的选课考虑","note":"优先补足同类缺口","expectedVersion":version,
            "comparison":{"id":evidence["id"],"choice":"with","with":{"remaining":0}}})

    def test_evidence_survives_save_submit_counselor_review_and_reload(self):
        evidence=self.receipt()
        saved=self.save(evidence)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(saved.json()["comparison"]["with"],evidence["with"])
        submitted=self.client.post(self.url+"/planning/submit",json={"term":self.term,"expectedVersion":2})
        self.assertEqual(submitted.status_code,200,submitted.text)
        self.login("C01")
        received=self.client.get(self.url+"/planning",params={"term":self.term}).json()["savedPlan"]
        self.assertEqual(received["comparison"]["id"],evidence["id"])
        self.assertEqual(received["comparison"]["choice"],"with")
        self.assertEqual(received["events"][-1]["payload"]["comparison"]["with"],evidence["with"])
        feedback=self.client.post(self.url+"/planning/review",json={"term":self.term,"expectedVersion":2,"status":"revision","comment":"请核对先修条件"})
        self.assertEqual(feedback.status_code,200,feedback.text)
        self.assertEqual(feedback.json()["comparison"]["id"],evidence["id"])

    def test_course_adjustment_preserves_explicit_historical_evidence(self):
        evidence=self.receipt()
        self.assertEqual(self.save(evidence).status_code,200)
        changed=self.save(evidence,[self.ids[0]],2)
        self.assertEqual(changed.status_code,200,changed.text)
        saved=changed.json()
        self.assertNotEqual(set(saved["courseIds"]),set(saved["comparison"]["with"]["courseIds"]))
        self.assertEqual(saved["comparison"]["with"],evidence["with"])

    def test_receipt_retry_is_idempotent_and_forged_fingerprint_rejected(self):
        first=self.receipt()
        self.assertEqual(first["id"],self.receipt()["id"])
        bad=self.client.post(self.url+"/selection-risk/record",json={"courseId":self.ids[1],"fingerprint":"0"*64})
        self.assertEqual(bad.status_code,422)
        with core.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM selection_comparisons").fetchone()[0],1)

    def test_stale_comparison_and_stale_save_cannot_overwrite(self):
        evidence=self.receipt()
        with core.connection() as db:
            planning.save_plan(db,self.sid,self.term,[self.ids[0]],"另一个页面的版本","",self.sid)
        self.assertEqual(self.save(evidence).status_code,422)
        self.assertEqual(self.save(evidence,version=2).status_code,422)
        latest=self.client.get(self.url+"/planning",params={"term":self.term}).json()["savedPlan"]
        self.assertEqual(latest["title"],"另一个页面的版本")
        self.assertEqual(latest["version"],2)

    def test_changed_offerings_invalidate_the_unrecorded_result(self):
        choice=self.client.post(self.url+"/selection-risk/compare",json={"courseId":self.ids[1]}).json()
        with core.connection() as db:
            db.execute("UPDATE course_offerings SET available=0 WHERE course_id=? AND term=?",(self.ids[1],self.term))
        result=self.client.post(self.url+"/selection-risk/record",json={"courseId":self.ids[1],"fingerprint":choice["fingerprint"]})
        self.assertEqual(result.status_code,422)

    def test_forged_receipt_and_other_student_access_rejected(self):
        evidence=self.receipt()
        evidence["id"]="CMP-"+"0"*64
        self.assertEqual(self.save(evidence).status_code,422)
        self.login("C02")
        self.assertEqual(self.client.get(self.url+"/planning").status_code,403)
        self.assertEqual(self.client.post(self.url+"/selection-risk/record",json={"courseId":self.ids[1],"fingerprint":"0"*64}).status_code,403)

    def test_legacy_plan_and_repeated_migration_are_readable(self):
        with core.connection() as db:
            db.execute("ALTER TABLE course_plans DROP COLUMN comparison_snapshot")
            planning.initialize(db)
            planning.initialize(db)
            obj=planning.get_planning(db,self.sid,self.term)["savedPlan"]
        self.assertEqual(obj["comparison"],{})
        self.assertEqual(obj["title"],"已保存参考")

    def test_local_followup_remembers_compared_course_and_current_offering(self):
        session=ToolSession({"id":self.sid,"role":"student"},"test-evidence",self.sid,self.major)
        local_workflow(session,"请对比下学期选课风险，解释课程代码 TEST-CMP-B 选与暂不选的差异。")
        self.assertEqual(session.course_ids,[self.ids[1]])
        answer=local_workflow(session,"如果这门下学期不开怎么办？")
        self.assertIn("TEST-CMP-B",answer)
        self.assertIn("当前记录为“有开课记录”",answer)
        self.assertEqual(session.results[-1]["tool"],"course_alternatives")

    def test_ambiguous_local_followup_asks_for_course(self):
        session=ToolSession({"id":self.sid,"role":"student"},"test-evidence",self.sid,self.major)
        answer=local_workflow(session,"这门下学期不开怎么办？")
        self.assertIn("哪门课程",answer)
        self.assertFalse(session.results)

    def test_elective_alternative_reduces_same_category_without_conflicts(self):
        with core.connection() as db:
            old=db.execute("SELECT * FROM courses WHERE id=?",(self.ids[1],)).fetchone()
            candidate=self.major+":TEST-CMP-C"
            db.execute("INSERT INTO courses VALUES(?,?,?,?,?,?,?,?,?)",
                       (candidate,"TEST-CMP-C","测试同类备选",self.major,2,old["category"],2,0,old["metadata"]))
            db.execute("DELETE FROM course_offerings WHERE term=? AND course_id NOT IN (?,?)",
                       (self.term,self.ids[0],self.ids[1]))
            slots=json.dumps([{"day":3,"start":1,"end":2,"weeks":[1,2]}])
            db.execute("INSERT INTO course_offerings VALUES(?,?,?,?,?,?,?,?)",(candidate,self.term,slots,20,0,1,1,"模拟课表"))
            data,answer=alternative_courses(db,self.sid,self.ids[1])
        self.assertEqual([c["id"] for c in data["alternatives"]],[candidate])
        self.assertEqual(data["alternatives"][0]["contribution"],2)
        self.assertIn("测试同类备选",answer)

    def test_required_course_retains_requirement_and_needs_school_confirmation(self):
        with core.connection() as db:
            db.execute("UPDATE courses SET required=1 WHERE id=?",(self.ids[1],))
            data,answer=alternative_courses(db,self.sid,self.ids[1])
        self.assertFalse(data["alternatives"])
        self.assertIn("向学院确认",answer)

    def name_followup_courses(self):
        with core.connection() as db:
            db.execute("UPDATE courses SET name=? WHERE id=?",("跨领域研讨",self.ids[0]))
            db.execute("UPDATE courses SET name=? WHERE id=?",("跨领域研讨实践",self.ids[1]))

    def test_plain_course_name_overrides_previous_conversation_course(self):
        self.name_followup_courses()
        session=ToolSession({"id":self.sid,"role":"student"},"followup",self.sid,self.major)
        local_workflow(session,"请对比下学期选课风险，解释课程代码 TEST-CMP-B 选与暂不选的差异。")
        answer=local_workflow(session,"跨领域研讨下学期不开怎么办？")
        self.assertEqual(session.results[-1]["data"]["course"]["id"],self.ids[0])
        self.assertIn("《跨领域研讨》",answer)
        self.assertNotIn("《跨领域研讨实践》",answer)

    def test_two_named_courses_request_one_course_instead_of_reusing_context(self):
        self.name_followup_courses()
        session=ToolSession({"id":self.sid,"role":"student"},"followup",self.sid,self.major,course_ids=[self.ids[0]])
        answer=local_workflow(session,"跨领域研讨和跨领域研讨实践都停开了怎么办？")
        self.assertIn("一门",answer)
        self.assertFalse(session.results)
        self.assertEqual(session.course_ids,[])

    def test_fallback_uses_results_for_the_newly_named_course(self):
        self.name_followup_courses()
        session=ToolSession({"id":self.sid,"role":"student"},"followup",self.sid,self.major)
        session.execute("course_alternatives",{"course":self.ids[1]})
        answer=local_workflow(session,"跨领域研讨下学期不开怎么办？")
        self.assertEqual(session.results[-1]["data"]["course"]["id"],self.ids[0])
        self.assertIn("《跨领域研讨》",answer)
        self.assertNotIn("《跨领域研讨实践》",answer)

    def test_http_followup_tracks_new_course_and_explicit_term(self):
        self.name_followup_courses()
        first=self.client.post("/api/assistant",json={"message":"请对比下学期选课风险，解释课程代码 TEST-CMP-B 选与暂不选的差异。"})
        self.assertEqual(first.status_code,200,first.text)
        followup=self.client.post("/api/assistant",json={"threadId":first.json()["threadId"],"message":"跨领域研讨本学期不开怎么办？"})
        self.assertEqual(followup.status_code,200,followup.text)
        self.assertIn("《跨领域研讨》在 "+core.TERM,followup.json()["answer"])
        self.assertNotIn("《跨领域研讨实践》",followup.json()["answer"])

    def test_failed_new_course_lookup_does_not_answer_with_old_course(self):
        self.name_followup_courses()
        session=ToolSession({"id":self.sid,"role":"student"},"followup",self.sid,self.major)
        session.execute("course_alternatives",{"course":self.ids[1]})
        answer=local_workflow(session,"《未知课程》下学期不开怎么办？")
        self.assertIn("未能核对",answer)
        self.assertNotIn("跨领域研讨实践",answer)
        self.assertEqual(session.course_ids,[])
