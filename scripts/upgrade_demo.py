"""Add provenance-backed coverage to the original, intact demo cohort only.

Back up the SQLite database first, stop the service, then run this once.
User-imported students and existing declarations are never overwritten.
"""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import core, academic
from server.data_quality import set_coverage, previous_term


def upgrade():
    if not core.is_demo():
        raise RuntimeError('This migration is only for the fixed-seed demo database.')
    if core.TERM!='2026-2027-1':
        raise RuntimeError('This migration covers the original 2026-2027-1 demo only.')
    core.initialize()
    with core.connection() as db:
        entry=db.execute("SELECT detail FROM audit WHERE action='初始化模拟数据' ORDER BY id LIMIT 1").fetchone()
        detail=json.loads(entry['detail']) if entry else {}
        if detail.get('seed')!=1022 or detail.get('personalData') is not False:
            raise RuntimeError('No matching demo provenance; declare coverage manually after verification.')
        count=detail.get('students',0)
        if not isinstance(count,int) or not 1<=count<=144:raise RuntimeError('Unexpected demo cohort size.')
        first=['林','陈','李','张','周','徐','王','刘','郑','宋','许','吴']
        last=['知远','书宁','雨桐','一诺','景明','若溪','清越','嘉禾','云舒','言蹊','予安','星野']
        changed=0
        db.execute('BEGIN IMMEDIATE')
        try:
            for i in range(count):
                mid='CS' if i%2==0 else 'SE'
                cohort=2025 if i%6==5 else 2024
                sid=f'{cohort}{mid}{i+1:03d}'
                row=db.execute('SELECT * FROM students WHERE id=?',(sid,)).fetchone()
                if not row or row['name']!=first[i//12%12]+last[i%12] or row['major']!=mid or row['cohort']!=cohort:
                    raise RuntimeError('Demo identity changed; verify data coverage manually.')
                for kind,term in [('grades',previous_term(core.TERM)),('enrollment',core.TERM)]:
                    if not db.execute('SELECT 1 FROM data_coverage WHERE student_id=? AND kind=?',(sid,kind)).fetchone():
                        set_coverage(db,sid,kind,term,'complete','原固定种子1022模拟数据迁移；保留既有记录','demo-upgrade-2.1')
                        changed+=1
            result=academic.recompute(db)
            core.audit(db,'system','demo.upgrade.2.1',{'coverageAdded':changed,'recompute':result})
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK');raise
        print(json.dumps({'coverageAdded':changed,'recompute':result},ensure_ascii=False))


if __name__=='__main__':upgrade()
