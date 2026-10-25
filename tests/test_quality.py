"""Coverage declarations and source-backed credit accounting counterexamples."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from server import core, academic, planning, data_quality


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="quality-", dir=Path(__file__).resolve().parent)
        self.old = os.environ.get("ZHIXUE_DB")
        os.environ["ZHIXUE_DB"] = str(Path(self.folder.name) / "quality.sqlite3")
        core.initialize()
        with core.connection() as db:
            data_quality.initialize(db)
            db.execute("INSERT INTO users VALUES ('C01','测试老师','counselor','fixture')")
            db.execute("INSERT INTO users VALUES ('2024CS001','测试学生','student','fixture')")
            db.execute("INSERT INTO students VALUES ('2024CS001','测试学生','CS',2024,'测试班','C01')")
            for c in next(p for p in core.curriculum()["majors"] if p["id"] == "CS")["courses"]:
                db.execute("INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?)", ("CS:" + c["code"], c["code"], c["name"], "CS", c["credits"], c["module"], c["semester"], int(c["required"]), json.dumps(c)))
        self.sid = "2024CS001"

    def tearDown(self):
        if self.old is None:
            os.environ.pop("ZHIXUE_DB", None)
        else:
            os.environ["ZHIXUE_DB"] = self.old
        assert Path(self.folder.name).resolve().is_relative_to(Path(__file__).resolve().parent)
        self.folder.cleanup()

    def record(self, cid="CS:392052", score=85, term="2025-2026-2"):
        with core.connection() as db:
            db.execute("INSERT OR REPLACE INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)", (self.sid, cid, term, score, "completed" if score is not None else "enrolled"))

    def declared(self, status="complete", through="2025-2026-2", kind="grades"):
        with core.connection() as db:
            data_quality.set_coverage(db, self.sid, kind, through, status, "隔离测试完整导出声明", "C01")

    def analyze(self):
        with core.connection() as db:
            return academic._analyze(db, db.execute("SELECT * FROM students WHERE id=?", (self.sid,)).fetchone())

    def test_one_historical_passing_row_does_not_imply_missing_all_others(self):
        self.record()
        result = self.analyze()
        self.assertEqual(result["_signals"], {})
        self.assertIsNone(result["metrics"]["creditGap"])
        self.assertIsNone(result["junior"]["creditsPerTerm"])
        self.assertFalse(result["metrics"]["dataQuality"]["historyComplete"])
        self.assertEqual(result["junior"]["missingCourses"], [])

    def test_partial_coverage_keeps_observed_failure_without_false_whole_term_alarm(self):
        self.record(score=55)
        self.declared(status="partial")
        result = self.analyze()
        self.assertEqual(result["_signals"]["completion"]["severity"], 1)
        self.assertNotIn("performance", result["_signals"])
        self.assertNotIn("progress", result["_signals"])

    def test_explicit_complete_export_makes_a_genuine_gap_actionable(self):
        self.record()
        self.declared()
        self.declared(kind="enrollment", through=core.TERM)
        result = self.analyze()
        self.assertTrue(result["metrics"]["dataQuality"]["historyComplete"])
        self.assertEqual(result["_signals"]["progress"]["severity"], 3)
        self.assertEqual(result["_signals"]["selection"]["severity"], 2)

    def test_aggregate_score_requires_coverage_of_that_graded_term(self):
        self.record(score=59, term=core.TERM)
        self.declared()
        self.assertNotIn("performance", self.analyze()["_signals"])
        self.declared(through=core.TERM)
        self.assertEqual(self.analyze()["_signals"]["performance"]["severity"], 3)

    def test_old_enrollment_coverage_does_not_prove_current_registration(self):
        self.record()
        self.declared()
        self.declared(kind="enrollment", through=data_quality.previous_term(core.TERM))
        result = self.analyze()
        self.assertFalse(result["metrics"]["dataQuality"]["enrollmentComplete"])
        self.assertNotIn("selection", result["_signals"])

    def test_core_general_surplus_cannot_cover_required_general_categories(self):
        with core.connection() as db:
            for i in range(6):
                cid = "CS:QUALITY-CORE-" + str(i)
                db.execute("INSERT INTO courses VALUES (?,?,?,?,?,?,?,?,?)", (cid, cid, "质量测试合成选修", "CS", 12, "通识", 3, 0, json.dumps({"submodule": "核心通识", "generalModule": str(i)})))
                db.execute("INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,85,'completed')", (self.sid, cid, "2025-2026-2"))
            audited = planning.audit_curriculum(db, self.sid)
            profile = academic.profile(db, self.sid)
        general = next(c for c in audited["categories"] if c["name"] == "通识")
        self.assertEqual(general["earned"], 72)
        self.assertEqual(general["credited"], 8)
        self.assertEqual(general["remaining"], 64)
        self.assertEqual([c["required"] for c in general["subcategories"]], [38, 26, 8])
        self.assertEqual(profile["credits"]["remaining"], 165)
        self.assertEqual(profile["credits"]["credited"], 8)
        self.assertEqual(profile["metrics"]["creditProgress"], round(8 / 173 * 100, 1))

    def test_unclassified_general_credits_do_not_satisfy_specific_subcategories(self):
        with core.connection() as db:
            db.execute("INSERT INTO courses VALUES ('CS:UNKNOWN','UNKNOWN','未认定通识','CS',3,'通识',3,0,'{}')")
        self.record("CS:UNKNOWN")
        with core.connection() as db:
            category = next(c for c in planning.audit_curriculum(db, self.sid)["categories"] if c["name"] == "通识")
        self.assertEqual(category["unclassifiedCredits"], 3)
        self.assertEqual(category["remaining"], 72)

    def test_minimal_imported_metadata_is_consistent_in_profile_and_audit(self):
        with core.connection() as db:
            db.execute("UPDATE courses SET metadata='{}' WHERE id='CS:154050'")
        self.record("CS:154050")
        with core.connection() as db:
            audit = planning.audit_curriculum(db, self.sid)
            profile = academic.profile(db, self.sid)
            metadata = planning.course_catalog(db, "CS")["CS:154050"]["meta"]
        self.assertTrue(metadata["innovation"])
        self.assertEqual(next(x for x in audit["checks"] if x["name"] == "创新创业独立分配学分")["value"], 2)
        self.assertEqual(audit["checks"], profile["credits"]["checks"])
        self.assertTrue(next(c for c in profile["courses"] if c["id"] == "CS:154050")["sourcePage"])

    def test_every_personal_course_can_be_reallocated_including_auto_assigned(self):
        self.record("CS:154050")
        with core.connection() as db:
            audit = planning.audit_curriculum(db, self.sid)
            item = next(c for c in audit["allocatableCourses"] if c["id"] == "CS:154050")
            self.assertEqual(item["allocationSource"], "automatic")
            self.assertEqual(item["allocatedTo"], "innovation")
            changed = planning.save_preferences(db, self.sid, "en", "advanced_free", ["CS_SYSTEM"], {"CS:154050": "free"})
        updated = next(c for c in changed["allocatableCourses"] if c["id"] == "CS:154050")
        self.assertEqual((updated["allocatedTo"], updated["allocationSource"]), ("free", "manual"))
        self.assertEqual(changed["pathAudit"]["innovationEarned"], 0)

    def test_losing_coverage_suspends_inference_without_claiming_recovery(self):
        self.record()
        self.declared()
        with core.connection() as db:
            academic.recompute(db)
        self.declared(status="partial")
        with core.connection() as db:
            academic.recompute(db)
            alerts = academic.profile(db, self.sid)["alerts"]
        progress = next(a for a in alerts if a["kind"] == "progress")
        self.assertFalse(progress["active"])
        self.assertEqual(progress["signalState"], "unconfirmed")
        self.assertEqual(progress["status"], "new")


if __name__ == "__main__":
    unittest.main()
