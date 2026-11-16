"""Portal contract, authorization and credit reconciliation on synthetic records only."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server import campus, core, planning
from server.selection_risk import next_term_report
from server.agent_runtime import ToolSession, local_workflow
from server.main import app
from server.seed import ensure_demo


class CampusModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="campus-", dir=Path(__file__).parent)
        cls.root = Path(cls.temp.name)
        with patch.dict(os.environ, {"ZHIXUE_DB":str(cls.root/"base.sqlite3")}):
            ensure_demo(count=24)
            with core.connection() as db:
                planning.seed_demo_support(db)
                campus.install_ticket_schema(db)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        path = self.root/(self._testMethodName+".sqlite3")
        with closing(sqlite3.connect(self.root/"base.sqlite3")) as source, closing(sqlite3.connect(path)) as dest:
            source.backup(dest)
        self.env=patch.dict(os.environ, {"ZHIXUE_DB":str(path),"ZHIXUE_DEMO":"1","ZHIXUE_EMBED_ORIGINS":"","ZHIXUE_CAMPUS_LAUNCH_KEY":""})
        self.env.start(); self.addCleanup(self.env.stop)
        self.client=TestClient(app); self.addCleanup(self.client.close)
        with core.connection() as db:
            self.sid=db.execute("SELECT id FROM students WHERE counselor_id='C01' ORDER BY id LIMIT 1").fetchone()[0]
            self.other=db.execute("SELECT id FROM students WHERE counselor_id='C02' ORDER BY id LIMIT 1").fetchone()[0]

    def login(self,who):
        self.assertEqual(self.client.post("/api/login",json={"username":who,"password":"demo123"}).status_code,200)

    def test_only_business_document_is_embeddable(self):
        for route in ("/","/campus","/assets/campus-module.html","/api/session"):
            self.assertEqual(self.client.get(route).headers["X-Frame-Options"],"DENY")
        response=self.client.get("/module")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers["Content-Security-Policy"],"frame-ancestors 'self'")
        with patch.dict(os.environ,{"ZHIXUE_EMBED_ORIGINS":"https://campus.example.edu:443,https://campus.example.edu"}):
            r=self.client.get("/module")
            self.assertEqual(r.headers["content-security-policy"],"frame-ancestors 'self' https://campus.example.edu")
            self.assertNotIn("x-frame-options",r.headers)
            self.assertEqual(self.client.get("/api/campus/config").json()["parentOrigins"],["https://campus.example.edu"])
        for unsafe in ("*","https://*.example.edu","http://host.example","https://user@host.test","https://host.test/path","https://host.test:99999"):
            with self.subTest(unsafe=unsafe),patch.dict(os.environ,{"ZHIXUE_EMBED_ORIGINS":unsafe}):
                with self.assertRaises(ValueError): campus.allowed_parents()

    def test_disabled_and_forged_launches(self):
        self.assertEqual(self.client.post("/api/campus/tickets",json={"userId":self.sid}).status_code,404)
        self.assertEqual(self.client.get("/api/session",headers={"X-User":self.sid}).status_code,401)
        with patch.dict(os.environ,{"ZHIXUE_CAMPUS_LAUNCH_KEY":"K"*40}):
            bearer={"Authorization":"Bearer "+"K"*40}
            for user in ("admin","no-such-person"):
                self.assertEqual(self.client.post("/api/campus/tickets",headers=bearer,json={"userId":user}).status_code,403)
            for headers in ({},{"Authorization":"Bearer wrong"},{**bearer,"Origin":"http://testserver"},{**bearer,"Origin":"https://untrusted.test"}):
                self.assertEqual(self.client.post("/api/campus/tickets",headers=headers,json={"userId":self.sid}).status_code,403)
            self.assertEqual(self.client.post("/api/campus/tickets",headers=bearer,json={"userId":self.sid,"role":"admin"}).status_code,422)

    def test_ticket_is_scoped_expiring_and_single_use(self):
        with patch.dict(os.environ,{"ZHIXUE_CAMPUS_LAUNCH_KEY":"K"*40}):
            def issue():
                return self.client.post("/api/campus/tickets",headers={"Authorization":"Bearer "+"K"*40},json={"userId":self.sid}).json()["ticket"]
            token=issue()
            with core.connection() as db:
                self.assertNotEqual(db.execute("SELECT ticket_hash FROM campus_launch_tickets").fetchone()[0],token)
            url="/api/campus/session"
            self.assertEqual(self.client.post(url,headers={"Origin":"https://outside.test"},json={"ticket":token}).status_code,403)
            r=self.client.post(url,json={"ticket":token})
            self.assertEqual(r.json()["user"]["id"],self.sid)
            self.assertIn("HttpOnly",r.headers["set-cookie"]);self.assertIn("samesite=strict",r.headers["set-cookie"].lower())
            self.assertEqual(self.client.get("/api/session").json()["user"]["role"],"student")
            self.assertEqual(self.client.get("/api/students/"+self.other+"/transcript").status_code,403)
            self.assertEqual(self.client.post(url,json={"ticket":token}).status_code,401)
            expired=issue()
            with core.connection() as db: db.execute("UPDATE campus_launch_tickets SET expires=0")
            self.assertEqual(self.client.post(url,json={"ticket":expired}).status_code,401)

    def test_new_queries_respect_student_and_counselor_scope(self):
        for endpoint in ("transcript","campus-audit","selection-risk"):
            self.assertEqual(self.client.get(f"/api/students/{self.sid}/{endpoint}").status_code,401)
        for role in (self.sid,"C01"):
            self.login(role)
            for endpoint in ("transcript","campus-audit","selection-risk"):
                self.assertEqual(self.client.get(f"/api/students/{self.sid}/{endpoint}").status_code,200)
                self.assertEqual(self.client.get(f"/api/students/{self.other}/{endpoint}").status_code,403)

    def test_reconciliation_and_language_trial_are_read_only(self):
        with core.connection() as db:
            major=db.execute("SELECT major FROM students WHERE id=?",(self.sid,)).fetchone()[0]
            catalog=planning.course_catalog(db,major)
            english=next(c for c in catalog.values() if c["meta"].get("language")=="en")
            foreign=db.execute("SELECT id,credits FROM courses WHERE major!=? ORDER BY id LIMIT 1",(major,)).fetchone()
            db.execute("DELETE FROM records WHERE student_id=?",(self.sid,))
            for course,term,score,state in [(english["id"],"2024-2025-1",76,"completed"),(english["id"],"2024-2025-2",85,"completed"),
                  (foreign["id"],"2025-2026-1",90,"completed"),(foreign["id"],core.TERM,None,"enrolled")]:
                db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES(?,?,?,?,?)",(self.sid,course,term,score,state))
            before=planning.preferences(db,self.sid)
        self.login(self.sid)
        d=self.client.get(f"/api/students/{self.sid}/campus-audit").json()
        r=d["report"]; t=r["totals"]
        self.assertEqual(t["recordedPassed"],english["credits"]+foreign["credits"])
        self.assertEqual(t["routeEarned"],english["credits"]);self.assertEqual(t["routeDifference"],foreign["credits"])
        self.assertEqual(t["recordedPassed"]-t["credited"],t["routeDifference"]+t["categoryDifference"])
        self.assertEqual(r["excluded"][0]["id"],foreign["id"])
        en=next(x for x in r["languageTrials"] if x["id"]=="en")
        alt=next(x for x in r["languageTrials"] if x["id"]=="ja")
        self.assertEqual(en["delta"],0);self.assertEqual(alt["delta"],-english["credits"])
        self.assertEqual([x["id"] for x in alt["changedCourses"]],[english["id"]])
        self.assertFalse(alt["changedCourses"][0]["enters"])
        transcript=self.client.get(f"/api/students/{self.sid}/transcript").json()["items"]
        self.assertEqual(len(transcript),4);self.assertIsNone(transcript[0]["score"]);self.assertIsNone(transcript[0]["gradePoint"])
        with core.connection() as db: self.assertEqual(before,planning.preferences(db,self.sid))
        sess=ToolSession({"id":self.sid,"role":"student"},"unit",self.sid,major)
        answer=local_workflow(sess,"为什么这些已通过的学分未计入？")
        self.assertIn("reconcile_credits",[s["tool"] for s in sess.steps]);self.assertIn("不在当前专业课程目录",answer)
        self.assertEqual(sess.results[0]["data"]["totals"],t)
        trial_session=ToolSession({"id":self.sid,"role":"student"},"trial",self.sid,major)
        answer=local_workflow(trial_session,"请试算改成日语路线后的学分差异")
        self.assertEqual(trial_session.results[0]["data"]["trial"],alt)
        self.assertIn("仅试算日语路线",answer)

    def test_subcategory_excess_cannot_replace_a_different_gap(self):
        import json
        with core.connection() as db:
            major=db.execute("SELECT major FROM students WHERE id=?",(self.sid,)).fetchone()[0]
            db.execute("DELETE FROM records WHERE student_id=?",(self.sid,))
            category=next(c for c in planning.audit_curriculum(db,self.sid)["categories"] if c["subcategories"])
            sub=category["subcategories"][0]
            for n,credit in enumerate((sub["required"],2)):
                cid=f"{major}:campus-example-{n}"
                db.execute("INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?)",(cid,cid,"模拟核对课程",major,credit,category["name"],1,0,json.dumps({"submodule":sub["name"]},ensure_ascii=False)))
                db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES(?,?,?,80,'completed')",(self.sid,cid,core.TERM))
            result=campus.credit_report(db,self.sid)
            t=result["totals"]
            self.assertEqual(t["routeDifference"],0);self.assertEqual(t["categoryDifference"],2)
            self.assertEqual(t["credited"],sub["required"]);self.assertEqual(t["remaining"],t["required"]-t["credited"])
            self.assertEqual(result["categoryDifferences"][0]["name"],category["name"])

    def test_next_term_separates_in_progress_retake_from_new_omissions(self):
        term=planning.next_term(core.TERM)
        with core.connection() as db:
            major=db.execute("SELECT major FROM students WHERE id=?",(self.sid,)).fetchone()[0]
            course=next(c for c in planning.course_catalog(db,major).values()
                        if c["required"] and c["semester"]==2 and not c["meta"].get("language"))
            db.execute("DELETE FROM records WHERE student_id=?", (self.sid,))
            db.executemany("INSERT INTO records(student_id,course_id,term,score,state) VALUES(?,?,?,?,?)",[
                (self.sid,course["id"],"2025-2026-1",54,"completed"),
                (self.sid,course["id"],core.TERM,None,"enrolled")])
            counts=lambda: tuple(db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
                                 for table in ("alerts","case_events","course_plans","records"))
            before=counts()
            report=next_term_report(db,self.sid)
            self.assertIn(course["id"],{c["id"] for c in report["studying"]})
            self.assertNotIn(course["id"],{c["id"] for c in report["priority"]+report["upcoming"]})
            self.assertNotIn(course["id"],report["plan"]["courseIds"])
            self.assertEqual(report["credits"]["credited"],0)
            self.assertEqual(report["credits"]["studying"],course["credits"])
            self.assertEqual(report["credits"]["ifPassedRemaining"],report["credits"]["remaining"]-course["credits"])
            empty=planning.check_plan(db,self.sid,term,[])
            self.assertNotIn(course["id"],{c["id"] for c in empty["missingRequired"]})
            self.assertIn(course["id"],{c["id"] for c in empty["awaitingRequired"]})
            explicit=planning.check_plan(db,self.sid,term,[course["id"]])
            self.assertTrue(any(c["kind"]=="awaiting_result" for c in explicit["conflicts"]))
            self.assertEqual(before,counts())

    def test_credit_projection_respects_module_cap_recognition_and_partial_data(self):
        import json
        with core.connection() as db:
            major=db.execute("SELECT major FROM students WHERE id=?",(self.sid,)).fetchone()[0]
            db.execute("DELETE FROM records WHERE student_id=?",(self.sid,))
            db.execute("DELETE FROM data_coverage WHERE student_id=?",(self.sid,))
            category=next(c for c in planning.audit_curriculum(db,self.sid)["categories"] if c["subcategories"])
            sub=category["subcategories"][0]
            def record(code,credits,score):
                cid=major+":"+code
                db.execute("INSERT INTO courses VALUES(?,?,?,?,?,?,?,?,?)",(cid,code,code,major,credits,category["name"],2,0,json.dumps({"submodule":sub["name"]},ensure_ascii=False)))
                db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES(?,?,?,?,?)",
                           (self.sid,cid,core.TERM,score,"enrolled" if score is None else "completed"))
                return cid
            record("SIM-CAP-PASS",sub["required"]-1,80)
            record("SIM-CAP-STUDY",3,None)
            failed=record("SIM-CAP-ELECTIVE",2,55)
            foreign=db.execute("SELECT id FROM courses WHERE major!=? LIMIT 1",(major,)).fetchone()[0]
            db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES(?,?,?,80,'completed')",(self.sid,foreign,core.TERM))
            report=next_term_report(db,self.sid)
            self.assertEqual(report["credits"]["studying"],3)
            self.assertEqual(report["credits"]["remaining"]-report["credits"]["ifPassedRemaining"],1)
            self.assertIsNone(report["junior"]["ifPassedAverage"])
            self.assertFalse(report["coverage"]["historyComplete"])
            self.assertFalse(any(c["reason"]=="已到建议学期" for c in report["priority"]))
            row=next(c for c in report["priority"] if c["id"]==failed)
            self.assertIsNone(row["offering"])
            self.assertEqual(row["additionalIfPassed"],0)
            self.assertFalse(row["required"])
            self.assertIn(foreign,{c["id"] for c in report["recognition"]["courses"]})

    def test_saved_plan_conflicts_and_agent_use_same_next_term_report(self):
        from server import academic
        term=planning.next_term(core.TERM)
        with core.connection() as db:
            major=db.execute("SELECT major FROM students WHERE id=?",(self.sid,)).fetchone()[0]
            offers=planning.get_planning(db,self.sid,term)["offerings"]
            candidates=[o for o in offers if not o["passed"] and o["available"] and o["slots"]]
            a,b=candidates[:2]
            db.execute("UPDATE course_offerings SET slots=(SELECT slots FROM course_offerings WHERE course_id=? AND term=?) WHERE course_id=? AND term=?",
                       (a["id"],term,b["id"],term))
            planning.save_plan(db,self.sid,term,[a["id"]],"模拟选课草案","",self.sid)
            report=next_term_report(db,self.sid)
            self.assertEqual(report["plan"]["kind"],"saved")
            self.assertEqual(report["plan"]["courseIds"],[a["id"]])
            self.assertEqual([x["id"] for x in report["alerts"]],[x["id"] for x in academic.profile(db,self.sid)["alerts"] if x["active"]])
        self.login(self.sid)
        check=self.client.post(f"/api/students/{self.sid}/planning/check",json={"term":term,"courseIds":[a["id"],b["id"]]}).json()
        self.assertTrue(any(i["kind"]=="time" and set(i["courseIds"])=={a["id"],b["id"]} for i in check["conflicts"]))
        session=ToolSession({"id":self.sid,"role":"student"},"risk-test",self.sid,major)
        answer=local_workflow(session,"请解释我的下学期选课风险")
        result=next(r for r in session.results if r["tool"]=="next_term_risk")
        self.assertEqual(result["term"],term)
        self.assertEqual(result["data"]["credits"],report["credits"])
        self.assertIn(term,answer)
        self.assertTrue(result["sourceIds"])

    def test_course_comparison_holds_other_courses_fixed_and_blocks_infeasible_credit_claims(self):
        import json
        term=planning.next_term(core.TERM)
        with core.connection() as db:
            major=db.execute("SELECT major FROM students WHERE id=?",(self.sid,)).fetchone()[0]
            db.execute("DELETE FROM records WHERE student_id=?",(self.sid,))
            category=next(c for c in planning.audit_curriculum(db,self.sid)["categories"] if c["subcategories"])
            sub=next(s for s in category["subcategories"] if s["required"]>=4)
            ids=[]
            def slots(day):
                return json.dumps([{"day":day,"start":1,"end":2,"weeks":[1,2]}])
            for code in ("SIM-CHOICE-A","SIM-CHOICE-B"):
                cid=major+":"+code
                ids.append(cid)
                db.execute("INSERT INTO courses VALUES(?,?,?,?,?,?,?,?,?)",(cid,code,code,major,2,category["name"],2,0,json.dumps({"submodule":sub["name"]},ensure_ascii=False)))
                db.execute("INSERT INTO course_offerings VALUES(?,?,?,?,?,?,?,?)",(cid,term,slots(1),20,0,1,1,"模拟时段"))
            db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES(?,?,?,47,'completed')",(self.sid,ids[1],core.TERM))
            original=planning.save_plan(db,self.sid,term,[ids[0]],"测试已存方案","保留备注",self.sid)
        self.login(self.sid)
        url=f"/api/students/{self.sid}/selection-risk/compare"
        self.assertEqual(self.client.post(f"/api/students/{self.other}/selection-risk/compare",json={"courseId":ids[1]}).status_code,403)
        self.assertEqual(self.client.post(url,json={"courseId":"other-course"}).status_code,422)
        blocked=self.client.post(url,json={"courseId":ids[1]}).json()
        self.assertIsNone(blocked["gain"]); self.assertIsNone(blocked["with"]["remaining"])
        self.assertTrue(any(x["kind"]=="time" for x in blocked["with"]["issues"]))
        self.assertTrue(blocked["without"]["eligible"])
        with core.connection() as db:
            db.execute("UPDATE course_offerings SET slots=? WHERE course_id=? AND term=?",(slots(2),ids[1],term))
        feasible=self.client.post(url,json={"courseId":ids[1]}).json()
        self.assertEqual(feasible["with"]["courseIds"],ids)
        self.assertEqual(feasible["without"]["courseIds"],ids[:1])
        self.assertEqual(feasible["gain"],2)
        self.assertEqual(feasible["without"]["remaining"]-feasible["with"]["remaining"],2)
        session=ToolSession({"id":self.sid,"role":"student"},"comparison",self.sid,major)
        answer=local_workflow(session,"请对比下学期选课风险，解释课程代码 SIM-CHOICE-B 选与暂不选的差异。")
        self.assertEqual(session.results[0]["data"]["comparison"],feasible)
        self.assertIn("多补",answer)
        with core.connection() as db:
            saved=planning.plan_object(db,db.execute("SELECT * FROM course_plans WHERE id=?",(original["id"],)).fetchone())
            self.assertEqual((saved["version"],saved["courseIds"],saved["note"]),(original["version"],ids[:1],"保留备注"))
