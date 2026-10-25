"""Tests of leakage controls and scope, not a claim of real predictive accuracy."""
import unittest
from server import core, forecast
from test_academic import IsolatedDatabase


def fixtures():
    records, coverage = [], []
    for i in range(64):
        sid=f'S{i:03d}'
        coverage.append({'student_id':sid,'kind':'grades','status':'complete','through_term':'2025-2026-2'})
        for term in ['2024-2025-1','2024-2025-2','2025-2026-1','2025-2026-2']:
            for c in range(3):
                records.append({'student_id':sid,'course_id':term+str(c),'term':term,
                                'score':50 if i%2 and c<2 else 85,'state':'completed','credits':3})
    return records,coverage


class ForecastTests(unittest.TestCase):
    def test_future_scores_cannot_change_past_features(self):
        records,_=fixtures()
        rows=[r for r in records if r['student_id']=='S001']
        before=forecast.snapshot(rows,'2024-2025-2')
        for r in rows:
            if r['term']>'2024-2025-2':r['score']=99
        self.assertEqual(before,forecast.snapshot(rows,'2024-2025-2'))

    def test_disjoint_students_and_time(self):
        rows,coverage=fixtures()
        samples,_=forecast.make_dataset(rows,coverage,core.TERM)
        train,test,cutoff=forecast.split_samples(samples)
        self.assertTrue(train and test)
        self.assertFalse({r['studentId'] for r in train}&{r['studentId'] for r in test})
        self.assertLess(max(r['featureTerm'] for r in train),min(r['featureTerm'] for r in test))
        self.assertTrue(all(r['targetTerm']==forecast.next_term(r['featureTerm']) for r in samples))

    def test_partial_coverage_excluded(self):
        rows,coverage=fixtures()
        coverage[0]['status']='partial'
        samples,latest=forecast.make_dataset(rows,coverage,core.TERM)
        self.assertNotIn('S000',{r['studentId'] for r in samples+latest})

    def test_both_classes_required_and_baseline_reported(self):
        rows,coverage=fixtures()
        result=forecast._fit(rows,coverage)
        self.assertTrue(result['available'])
        self.assertTrue(all(isinstance(r['notes'],list) for r in result['items']))
        self.assertEqual(set(result['evaluation']['metrics']),set(result['evaluation']['baseline']))
        for r in rows:r['score']=85
        self.assertFalse(forecast._fit(rows,coverage)['available'])


class ForecastScope(IsolatedDatabase):
    def test_result_scope_and_read_only(self):
        rows,coverage=fixtures()
        with core.connection() as db:
            db.execute("INSERT INTO users VALUES ('C','老师','counselor','x')")
            for r in coverage:
                sid=r['student_id']
                db.execute('INSERT INTO users VALUES (?,?,?,?)',(sid,sid,'student','x'))
                db.execute('INSERT INTO students VALUES (?,?,?,?,?,?)',(sid,sid,'CS',2024,'A','C'))
                from server.data_quality import set_coverage
                set_coverage(db,sid,'grades',r['through_term'],'complete','fixture','test')
            for r in rows:
                db.execute('INSERT OR IGNORE INTO courses VALUES (?,?,?,?,?,?,?,?,?)',(r['course_id'],r['course_id'],r['course_id'],'CS',3,'专业',1,0,'{}'))
                db.execute('INSERT INTO records(student_id,course_id,term,score,state) VALUES (?,?,?,?,?)',tuple(r[k] for k in ('student_id','course_id','term','score','state')))
            before=db.total_changes
            result=forecast.build_forecast(db,{f'S{i:03d}' for i in range(32)})
            self.assertTrue(result['available'])
            self.assertEqual({r['studentId'] for r in result['items']},{f'S{i:03d}' for i in range(32)})
            self.assertEqual(result['evaluation']['trainStudents']+result['evaluation']['testStudents'],32)
            empty=forecast.build_forecast(db,set())
            self.assertEqual(empty['evaluation']['trainSamples'],0)
            self.assertEqual(empty['items'],[])
            self.assertEqual(db.total_changes,before)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM alerts').fetchone()[0],0)


if __name__=='__main__':unittest.main()
