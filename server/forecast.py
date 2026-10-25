"""Auxiliary next-semester classifier with separate student and time holdouts.

Labels come from observed next-semester course outcomes, never rule alerts.
This module is read-only and cannot create, escalate, or close a formal alert.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import threading

from . import core

FEATURES = ['最近学期加权均分', '上一有成绩学期均分', '相较上一有成绩学期变化', '最近学期未通过门数',
            '最近学期未通过学分', '最近学期修读学分', '最近学期课程数', '累计通过学分', '累计重修次数']
TARGET = '下一学期有至少2门课程成绩低于60分'
LIMITATIONS = ['辅助分数不是经真实学生数据校准的风险概率，不改变规则预警等级。',
               '历史学期与测试学期分开，训练与测试学生不重叠；样本少时指标可能波动。',
               '因素表示模型中的相关贡献，不代表因果关系；无完整成绩声明时不生成预测。']
_CACHE = {}
_LOCK = threading.Lock()


def next_term(term):
    y = int(term[:4])
    return f'{y}-{y+1}-2' if term.endswith('1') else f'{y+1}-{y+2}-1'


def snapshot(rows, term):
    """Features have no access to an observation after the snapshot term."""
    past = [r for r in rows if r['term'] <= term]
    by_term = defaultdict(list)
    for r in past:
        by_term[r['term']].append(r)
    current = by_term.get(term, [])
    if not current:
        return None
    def mean(rs):
        return sum(r['score'] * r['credits'] for r in rs) / sum(r['credits'] for r in rs)
    terms = sorted(by_term)
    avg = mean(current)
    previous = mean(by_term[terms[-2]]) if len(terms) > 1 else avg
    best, attempts = {}, defaultdict(int)
    for r in past:
        attempts[r['course_id']] += 1
        if r['score'] >= 60:
            best[r['course_id']] = r['credits']
    fails = [r for r in current if r['score'] < 60]
    return [avg, previous, avg-previous, len(fails), sum(r['credits'] for r in fails),
            sum(r['credits'] for r in current), len(current), sum(best.values()),
            sum(max(n-1,0) for n in attempts.values())]


def make_dataset(records, declarations, current_term):
    by_student = defaultdict(list)
    through = {r['student_id']: r['through_term'] for r in declarations
               if r['kind']=='grades' and r['status']=='complete' and r['through_term']<=current_term}
    for r in records:
        if r['state']=='completed' and r['score'] is not None and r['term']<=min(through.get(r['student_id'], ''),current_term):
            by_student[r['student_id']].append(r)
    samples, latest = [], []
    for sid, rows in sorted(by_student.items()):
        terms = sorted({r['term'] for r in rows})
        for term in terms:
            outcome = next_term(term)
            following = [r for r in rows if r['term']==outcome]
            if following:
                # Retakes of the same course in other semesters are not extra failures here.
                failures = {r['course_id'] for r in following if r['score']<60}
                samples.append({'studentId':sid, 'featureTerm':term, 'targetTerm':outcome,
                                'x':snapshot(rows,term), 'y':int(len(failures)>=2)})
        # A stale partial last semester must never be passed off as a current forecast.
        if terms and terms[-1] == through[sid] and next_term(terms[-1]) >= current_term:
            latest.append({'studentId':sid,'featureTerm':terms[-1],'targetTerm':next_term(terms[-1]),
                           'x':snapshot(rows,terms[-1])})
    return samples, latest


def split_samples(samples):
    if not samples:
        return [], [], None
    cutoff = max(r['featureTerm'] for r in samples)
    candidates = sorted({r['studentId'] for r in samples if r['featureTerm']==cutoff},
                        key=lambda sid:hashlib.sha256(sid.encode()).hexdigest())
    heldout = set(candidates[::4])
    train = [r for r in samples if r['studentId'] not in heldout and r['featureTerm']<cutoff]
    test = [r for r in samples if r['studentId'] in heldout and r['featureTerm']==cutoff]
    return train, test, cutoff


def _metrics(y, p):
    from sklearn.metrics import (roc_auc_score, brier_score_loss, balanced_accuracy_score,
                                 precision_score, recall_score, f1_score, accuracy_score)
    pred = [int(x>=.5) for x in p]
    return {k:round(float(v),4) for k,v in {
        'auc':roc_auc_score(y,p), 'brier':brier_score_loss(y,p),
        'balancedAccuracy':balanced_accuracy_score(y,pred), 'precision':precision_score(y,pred,zero_division=0),
        'recall':recall_score(y,pred,zero_division=0), 'f1':f1_score(y,pred,zero_division=0),
        'accuracy':accuracy_score(y,pred)}.items()}


def _fit(records, declarations):
    import numpy as np
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.dummy import DummyClassifier
    samples, latest = make_dataset(records,declarations,core.TERM)
    train,test,cutoff = split_samples(samples)
    result = {'available':False,'isDemo':core.is_demo(),'target':TARGET,
              'model':'标准化 + Logistic Regression','limitations':LIMITATIONS,'items':[]}
    evaluation = {'trainSamples':len(train),'testSamples':len(test),
                  'trainStudents':len({r['studentId'] for r in train}),
                  'testStudents':len({r['studentId'] for r in test}),
                  'trainPositive':sum(r['y'] for r in train), 'testPositive':sum(r['y'] for r in test),
                  'cutoff':cutoff,'metrics':{},'baseline':{},'baselineName':'训练集多数类基线'}
    result['evaluation'] = evaluation
    if len(train)<24 or len(test)<8 or len({r['y'] for r in train})<2 or len({r['y'] for r in test})<2:
        result['reason'] = '按学生及时间留出后，训练/测试样本或正负类别不足，暂不展示模型分数。'
        return result
    x_train,y_train = [r['x'] for r in train],[r['y'] for r in train]
    x_test,y_test = [r['x'] for r in test],[r['y'] for r in test]
    model = make_pipeline(StandardScaler(),LogisticRegression(class_weight='balanced',max_iter=600,random_state=1022))
    model.fit(x_train,y_train)
    dummy = DummyClassifier(strategy='prior').fit(x_train,y_train)
    evaluation['metrics'] = _metrics(y_test,model.predict_proba(x_test)[:,1])
    evaluation['baseline'] = _metrics(y_test,dummy.predict_proba(x_test)[:,1])
    result['available'] = True
    # Use the exact evaluated model. Do not silently refit on the test set.
    scaler,lr = model.steps[0][1],model.steps[1][1]
    for row in latest:
        vector=np.asarray([row['x']],dtype=float)
        contribution=scaler.transform(vector)[0]*lr.coef_[0]
        factors=[{'name':FEATURES[i],'value':round(float(row['x'][i]),2),
                  'contribution':round(float(contribution[i]),4)}
                 for i in sorted(range(len(FEATURES)),key=lambda i:abs(contribution[i]),reverse=True)[:3]]
        result['items'].append({'studentId':row['studentId'],'score':round(float(model.predict_proba(vector)[0,1]),4),
                                'featureTerm':row['featureTerm'],'targetTerm':row['targetTerm'], 'factors':factors,
                                'notes':['依据已确认完整历史成绩；需结合当前选课和人工核对。']})
    result['items'].sort(key=lambda r:(-r['score'],r['studentId']))
    return result


def build_forecast(conn, visible_ids):
    # Training/evaluation statistics obey the same role scope as individual results.
    # Even an empty scope must not disclose the school-wide population counts.
    records=[dict(r) for r in conn.execute('SELECT r.student_id,r.course_id,r.term,r.score,r.state,c.credits FROM records r JOIN courses c ON c.id=r.course_id ORDER BY r.student_id,r.term,r.course_id') if r['student_id'] in visible_ids]
    declarations=[dict(r) for r in conn.execute('SELECT * FROM data_coverage ORDER BY student_id,kind') if r['student_id'] in visible_ids]
    fingerprint=hashlib.sha256(json.dumps([str(core.db_path()),core.TERM,core.is_demo(),records,declarations],sort_keys=True).encode()).hexdigest()
    with _LOCK:
        if fingerprint not in _CACHE:
            result=_fit(records,declarations)
            _CACHE.clear()
            _CACHE[fingerprint]=result
        result=json.loads(json.dumps(_CACHE[fingerprint]))
    names={r['id']:r['name'] for r in conn.execute('SELECT id,name FROM students') if r['id'] in visible_ids}
    result['items']=[dict(r,name=names[r['studentId']]) for r in result['items'] if r['studentId'] in names]
    return result
