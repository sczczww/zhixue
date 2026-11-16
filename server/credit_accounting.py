"""Reconcile course records and curriculum requirements, including read-only trials."""
from . import academic, core, planning


def credit_report(conn, student_id, profile=None, *, include_trials=False):
    p = profile if profile is not None else academic.profile(conn,student_id)
    audit = planning.audit_curriculum(conn,student_id)
    catalog = planning.course_catalog(conn,p['student']['major'])
    passed = [dict(r) for r in conn.execute('''SELECT DISTINCT c.id,c.code,c.name,c.credits FROM records r JOIN courses c ON c.id=r.course_id
        WHERE r.student_id=? AND r.term<=? AND r.state!='withdrawn' AND r.score>=60 ORDER BY c.code''',(student_id,core.TERM))]
    counted = set(audit['countedCourseIds'])
    excluded = []
    for row in passed:
        if row['id'] not in counted:
            course = catalog.get(row['id'])
            reason = '不在当前专业课程目录' if not course else '不属于当前所选外语路线'
            excluded.append({**row,'reason':reason})
    differences = [{'name':c['name'],'earned':c['earned'],'credited':c['credited'],'difference':round(c['earned']-c['credited'],2)}
                   for c in p['credits']['categories'] if c['earned']-c['credited']>0.001]
    recorded = round(sum(c['credits'] for c in passed),2)
    totals = {'recordedPassed':recorded,'routeEarned':p['credits']['earned'],'credited':p['credits']['credited'],
              'routeDifference':round(sum(c['credits'] for c in excluded),2), 'categoryDifference':round(sum(c['difference'] for c in differences),2),
              'remaining':p['credits']['remaining'],'required':p['credits']['total']}
    result = {'totals':totals,'excluded':excluded,'categoryDifferences':differences,'pendingAllocation':audit['unassignedCourses'],
              'historyComplete':audit['dataQuality']['historyComplete'],'sources':audit['sources']}
    if include_trials:
        program = next(x for x in academic.catalog()['majors'] if x['id']==p['student']['major'])
        trials = []
        for lang in audit['languages']:
            accepted = {c['id'] for c in passed if c['id'] in catalog and catalog[c['id']]['meta'].get('language') in (None,lang['id'])}
            categories = planning.category_totals(program,catalog,accepted)
            hypothetical = round(sum(c['credited'] for c in categories),2)
            trials.append({'id':lang['id'],'name':lang['name'],'credited':hypothetical,'delta':round(hypothetical-totals['credited'],2),
                           'remaining':round(sum(c['remaining'] for c in categories),2),
                           'changedCourses':[{**c,'enters':c['id'] in accepted} for c in passed if c['id'] in (accepted ^ counted)]})
        result.update({'currentLanguage':audit['preferences']['language'],'languageTrials':trials})
    return result
