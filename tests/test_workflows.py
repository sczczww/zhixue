"""Cross-feature checks for actionable student/counselor support and imports."""
import csv
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from fastapi.testclient import TestClient


class UpgradedWorkflows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous={k:os.environ.get(k) for k in ('ZHIXUE_DB','ZHIXUE_DEMO')}
        cls.tmp=tempfile.TemporaryDirectory(prefix='workflow-',dir=Path(__file__).resolve().parents[1]/'tmp')
        cls.root=Path(cls.tmp.name)
        os.environ['ZHIXUE_DB']=str(cls.root/'base.sqlite3');os.environ['ZHIXUE_DEMO']='1'
        from server.main import app
        from server import core
        cls.app=app;cls.core=core
        with TestClient(app) as client:
            assert client.get('/api/status').json()['students']==144

    @classmethod
    def tearDownClass(cls):
        for key,value in cls.previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
        cls.tmp.cleanup()

    def setUp(self):
        path=self.root/(self._testMethodName+'.sqlite3')
        with closing(sqlite3.connect(self.root/'base.sqlite3')) as src,closing(sqlite3.connect(path)) as dst:src.backup(dst)
        os.environ['ZHIXUE_DB']=str(path)
        self.client=TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):self.client.__exit__(None,None,None)

    def login(self,who):
        self.assertEqual(self.client.post('/api/login',json={'username':who,'password':'demo123'}).status_code,200)

    def upload(self,kind,rows):
        out=io.StringIO();writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        return self.client.post('/api/import?type='+kind,files={'file':('sample.csv',out.getvalue().encode(),'text/csv')})

    def test_own_task_edit_archive_and_teacher_assignment(self):
        self.login('2024CS001')
        result=self.client.post('/api/my/plan',json={'title':'每周复习','description':'周二和周四各30分钟'}).json()
        task=result['tasks'][0]
        edit=self.client.patch('/api/my/plan/'+str(task['id']),json={'title':'每周两次复习','dueDate':'2026-11-01'})
        self.assertEqual(edit.status_code,200)
        self.assertEqual(self.client.delete('/api/my/plan/'+str(task['id'])).status_code,200)
        self.assertFalse(self.client.get('/api/my/plan').json()['tasks'])
        self.login('C01')
        assigned=self.client.post('/api/students/2024CS001/plan',json={'title':'联系任课老师','description':'确认补修安排'})
        self.assertEqual(assigned.status_code,200)
        task=assigned.json()['tasks'][0]
        self.login('2024CS001')
        self.assertEqual(self.client.patch('/api/my/plan/'+str(task['id']),json={'title':'覆盖老师任务'}).status_code,403)
        self.assertEqual(self.client.delete('/api/my/plan/'+str(task['id'])).status_code,403)
        self.assertEqual(self.client.patch('/api/my/plan/'+str(task['id']),json={'completed':True}).status_code,200)
        self.login('C01')
        messages=self.client.get('/api/notifications').json()['items']
        self.assertTrue(any(x.get('kind')=='study_task' and '已完成' in x['title'] for x in messages))

    def test_feedback_and_teacher_update_have_distinct_notifications(self):
        self.login('2024CS013')
        alert=self.client.get('/api/alerts').json()['items'][0]
        self.assertEqual(self.client.post('/api/alerts/'+alert['id']+'/feedback',json={'note':'已经确认补修时间'}).status_code,200)
        self.login('C01')
        overview=self.client.get('/api/overview').json()
        self.assertGreater(overview['unreadFeedback'],0)
        detail=self.client.get('/api/alerts/'+alert['id']).json()
        state=detail['alert']['status']
        if state=='closed':self.fail('Fixture expected active follow-up')
        response=self.client.post('/api/alerts/'+alert['id']+'/followup',json={'status':state,'note':'本周继续答疑','reviewOn':'2026-11-01'})
        self.assertEqual(response.status_code,200)
        self.login('2024CS013')
        self.assertTrue(any(x['kind']=='followup' for x in self.client.get('/api/notifications').json()['items']))

    def test_generic_notification_scope_after_reassignment(self):
        with self.core.connection() as db:
            mid=self.core.notify(db,'C01','审核方案','semester_plan','P-TEST','2024CS001')
        self.login('C01')
        self.assertTrue(any(x['id']==f'msg:{mid}' for x in self.client.get('/api/notifications').json()['items']))
        with self.core.connection() as db:db.execute("UPDATE students SET counselor_id='C02' WHERE id='2024CS001'")
        self.assertFalse(any(x['id']==f'msg:{mid}' for x in self.client.get('/api/notifications').json()['items']))
        self.assertEqual(self.client.post(f'/api/notifications/msg:{mid}/read').status_code,403)

    def test_offering_import_validation_and_provenance(self):
        self.login('admin')
        with self.core.connection() as db:cid=db.execute("SELECT id FROM courses WHERE major='CS' LIMIT 1").fetchone()[0]
        row={'course_id':cid,'term':'2026-2027-2','slots':json.dumps([{'day':2,'start':3,'end':4,'weeks':[1,3,5]}]),'capacity':'40','enrolled':'30','available':'1','source':'测试课程安排表'}
        response=self.upload('offerings',[row,{**row,'capacity':'-1'},{**row,'slots':'[{"day":2,"start":4,"end":2}]'},{**row,'enrolled':'41'}])
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json()['errors']),3)
        with self.core.connection() as db:
            stored=db.execute('SELECT * FROM course_offerings WHERE course_id=? AND term=?',(cid,row['term'])).fetchone()
            self.assertEqual(stored['is_demo'],0);self.assertEqual(stored['enrolled'],30)
            self.assertEqual(json.loads(stored['slots'])[0]['weeks'],[1,3,5])

    def test_dependency_cycle_is_rejected_without_changing_accepted_relation(self):
        self.login('admin')
        with self.core.connection() as db:
            ids=[r[0] for r in db.execute("SELECT id FROM courses WHERE major='CS' AND id NOT IN (SELECT course_id FROM course_dependencies) AND id NOT IN (SELECT prerequisite_id FROM course_dependencies) LIMIT 2")]
        rows=[{'course_id':ids[0],'prerequisite_id':ids[1],'source':'测试先修说明'},{'course_id':ids[1],'prerequisite_id':ids[0],'source':'测试循环'}]
        result=self.upload('dependencies',rows)
        self.assertEqual(result.status_code,200);self.assertEqual(len(result.json()['errors']),1)

    def test_analytics_never_changes_warning_levels_and_counts_scoped_population(self):
        self.login('C01')
        before=self.client.get('/api/alerts').json()['items']
        response=self.client.get('/api/analytics')
        self.assertEqual(response.status_code,200)
        views=response.json()['views'];self.assertEqual(len(views),4)
        for view in views:
            self.assertGreaterEqual(len(view['features']),4)
            self.assertEqual(sum(g['count'] for g in view['groups']),36)
            self.assertEqual(view['sampleCount']+view['missingCount'],36)
        self.assertEqual(before,self.client.get('/api/alerts').json()['items'])


if __name__=='__main__':unittest.main()
