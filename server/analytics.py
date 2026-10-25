"""Descriptive cohort analysis, kept separate from formal warning decisions."""
from collections import Counter, defaultdict
import math
from . import core

def _finite(value):
    return value is not None and isinstance(value,(int,float)) and math.isfinite(value)

def build_analytics(conn, profiles):
    attempts=defaultdict(lambda:defaultdict(list))
    wanted={p['student']['id'] for p in profiles}
    for row in conn.execute("SELECT student_id,course_id,term,score FROM records WHERE term<=? AND state!='withdrawn' AND score IS NOT NULL ORDER BY term,id",(core.TERM,)):
        if row['student_id'] in wanted:attempts[row['student_id']][row['course_id']].append(row['score'])
    vectors={key:[] for key in ('performance','completion','progress','selection')}
    for p in profiles:
        sid=p['student']['id'];m=p['metrics'];trend=p['trend']
        grades=[r['gpa'] for r in trend]
        gpa_std=(sum((g-sum(grades)/len(grades))**2 for g in grades)/len(grades))**.5 if grades else None
        vectors['performance'].append([p['student']['gpa'],m.get('latestScore'),grades[-1]-grades[0] if len(grades)>1 else None,gpa_std])
        history=attempts[sid]
        has_grades=bool(history)
        repeats=[scores for scores in history.values() if len(scores)>1]
        vectors['completion'].append([m['failedCourses'] if has_grades else None,m['failedCredits'] if has_grades else None,len(repeats) if has_grades else None,sum(any(x<60 for x in scores) and any(x>=60 for x in scores) for scores in repeats) if has_grades else None])
        cats=p['credits']['categories']
        vectors['progress'].append([m['creditProgress'] if has_grades else None,m['creditGap']/max(1,m['plannedCredits']) if m.get('creditGap') is not None else None,*[next((min(c['earned']/max(1,c['required']),1) for c in cats if c['name']==name),None) if has_grades else None for name in ('通识','专业','个性化')]])
        selection_known=m.get('dataQuality',{}).get('hasCurrentEnrollment',False)
        vectors['selection'].append([m['selectedCredits'] if selection_known else None,m['selectedCredits']/max(1,m['loadLimit']) if selection_known else None,len(p['junior']['missingCourses']) if selection_known else None,m['failedCourses'] if has_grades else None])
    specs=[('performance','成绩趋势',['累计绩点','最近学期均分','首末学期绩点变化','学期绩点波动']),('completion','课程通过',['未通过课程数','未通过学分','重复修读课程数','重修后通过课程数']),('progress','学分进度',['总学分完成比例','往期必修缺口比例','通识完成比例','专业完成比例','个性化完成比例']),('selection','选课负荷',['本期选课学分','相对计划负荷','到期未修课程数','待补修课程数'])]
    views=[]
    for key,name,feature_names in specs:
        values=vectors[key]
        known=[i for i,v in enumerate(values) if any(_finite(x) for x in v)]
        missing=[i for i in range(len(values)) if i not in known]
        labels=[0]*len(known);model_name='描述性观察组';silhouette=None;anomalies=[]
        numeric_data=[];scaled=None;centers={}
        if known:
            import numpy as np
            from sklearn.preprocessing import StandardScaler
            numeric_data=np.array([[float(x) if _finite(x) else np.nan for x in values[i]] for i in known])
            missing_count=int(np.isnan(numeric_data).sum())
            for column in range(numeric_data.shape[1]):
                finite=numeric_data[:,column][np.isfinite(numeric_data[:,column])]
                numeric_data[~np.isfinite(numeric_data[:,column]),column]=float(np.median(finite)) if len(finite) else 0
            scaled=StandardScaler().fit_transform(numeric_data)
            distinct=len(np.unique(scaled,axis=0))
            if len(known)>=8 and distinct>=2:
                from sklearn.cluster import KMeans
                from sklearn.metrics import silhouette_score
                candidates=[]
                for k in range(2,min(5,distinct,len(known)//3)+1):
                    model=KMeans(n_clusters=k,n_init=10,random_state=1022)
                    trial=model.fit_predict(scaled)
                    counts=Counter(trial)
                    if len(counts)<2 or min(counts.values())<2:continue
                    score=float(silhouette_score(scaled,trial))
                    candidates.append((score,-k,trial,model.cluster_centers_))
                if candidates:
                    score,_,selected,centers=max(candidates,key=lambda x:(x[0],x[1]))
                    labels=selected.tolist();silhouette=round(score,3);model_name='K-means 聚类'
            # Outliers describe atypical patterns. They never change academic warning severity.
            if len(known)>=20 and distinct>=5:
                from sklearn.ensemble import IsolationForest
                detector=IsolationForest(n_estimators=100,contamination='auto',random_state=1022)
                detector.fit(scaled)
                decisions=detector.decision_function(scaled)
                # Report a small, ranked inspection list; avoid pretending every outlier is at risk.
                for local in sorted(range(len(known)),key=lambda j:decisions[j]):
                    if decisions[local]>=0 or len(anomalies)>=5:break
                    original=known[local]
                    deviations=sorted(range(len(feature_names)),key=lambda j:abs(scaled[local,j]),reverse=True)[:2]
                    anomalies.append({'id':profiles[original]['student']['id'],'name':profiles[original]['student']['name'],'reason':'、'.join(feature_names[j]+('偏高' if scaled[local,j]>0 else '偏低') for j in deviations),'label':'建议人工观察','score':round(float(-decisions[local]),3)})
        else:missing_count=0
        groups=[]
        for rank,label in enumerate(sorted(set(labels),key=lambda lab:sum(values[known[j]][0] or 0 for j,x in enumerate(labels) if x==lab)/max(1,labels.count(lab)))):
            indices=[known[j] for j,x in enumerate(labels) if x==label]
            members=[{'id':profiles[i]['student']['id'],'name':profiles[i]['student']['name']} for i in indices]
            metrics=[]
            for column,title in enumerate(feature_names):
                xs=[values[i][column] for i in indices if _finite(values[i][column])]
                metrics.append({'name':title,'value':round(sum(xs)/len(xs),2) if xs else None,'known':len(xs)})
            main=metrics[0]
            description=f"{main['name']}均值 {main['value']}" if main['value'] is not None else '已有部分学情资料'
            groups.append({'name':f'{name}观察组 {rank+1}','count':len(indices),'description':description,'students':members,'metrics':metrics})
        if missing:
            groups.append({'name':'资料待完善','count':len(missing),'description':'尚无足够资料，未进入算法分组。','students':[{'id':profiles[i]['student']['id'],'name':profiles[i]['student']['name']} for i in missing],'metrics':[]})
        views.append({'id':key,'name':name,'description':f'依据{len(feature_names)}项学情指标观察差异。样本足够时以轮廓系数选择分组数；分组和异常观察不改变正式预警等级。','method':model_name,'selectionMethod':'silhouette' if silhouette is not None else None,'groups':groups,'anomalies':anomalies,'features':feature_names,'silhouette':silhouette,'sampleCount':len(known),'missingCount':len(missing),'imputedValues':missing_count})
    return {'views':views,'note':'仅分析当前账号可见学生；不同专业和年级的课程进度不可直接视为能力差异。聚类质量指标不是预测准确率，异常观察也不是学业处分依据。'}
