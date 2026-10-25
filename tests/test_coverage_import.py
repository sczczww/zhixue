import unittest
from server import core
from server.imports import import_one
from test_academic import IsolatedDatabase


class CoverageImport(IsolatedDatabase):
    def setUp(self):
        super().setUp()
        with core.connection() as db:
            db.executemany('INSERT INTO users VALUES (?,?,?,?)',[('C','老师','counselor','x'),('S','学生','student','x')])
            db.execute("INSERT INTO students VALUES ('S','学生','CS',2024,'A','C')")
        self.row={'student_id':'S','kind':'grades','through_term':'2025-2026-2','status':'complete','source':'完整成绩导出核对'}

    def test_upsert_uses_server_actor_and_can_mark_partial(self):
        with core.connection() as db:
            row=dict(self.row,confirmed_by='forged')
            self.assertEqual(import_one(db,'coverage',row,'real-admin'),'inserted')
            self.assertEqual(db.execute('SELECT confirmed_by FROM data_coverage').fetchone()[0],'real-admin')
            row['status']='partial'
            self.assertEqual(import_one(db,'coverage',row,'real-admin'),'updated')
            self.assertEqual(db.execute('SELECT status FROM data_coverage').fetchone()[0],'partial')

    def test_future_unknown_student_and_bad_status_rejected(self):
        with core.connection() as db:
            for changes in [{'through_term':'2027-2028-1'},{'student_id':'missing'},{'status':'assumed'}]:
                with self.subTest(changes=changes),self.assertRaises(ValueError):
                    import_one(db,'coverage',dict(self.row,**changes),'admin')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM data_coverage').fetchone()[0],0)


if __name__=='__main__':unittest.main()
