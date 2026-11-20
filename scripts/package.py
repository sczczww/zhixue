"""Package only the independent project, excluding local state and credentials."""
import hashlib
import argparse
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

root=Path(__file__).resolve().parents[1]
out=root.parent/'deliverables'
out.mkdir(exist_ok=True)
args=argparse.ArgumentParser(description=__doc__)
edition=args.add_mutually_exclusive_group()
edition.add_argument('--campus',action='store_true',help='输出可单独分享的校园模块版')
edition.add_argument('--independent',action='store_true',help='输出更新后的知学独立工作台')
options=args.parse_args()
campus=options.campus
archive_name='知学-B1-完整项目.zip'
if campus: archive_name='知学-B1-校园模块版.zip'
if options.independent: archive_name='知学-B1-独立工作台.zip'
archive=out/archive_name
# Ship sources, known reference documents and example screenshots only. Do not
# descend into user environments, local databases, inspection or design-review files.
patterns=('*.bat','README.md','.env.example','.gitignore','requirements*.txt','run.py','Dockerfile','.dockerignore','web/*.css','web/*.html','web/*.js','web/*.svg',
          'server/*.py','scripts/*.py','scripts/*.ps1','tests/test_*.py','tests/evaluate_*.py',
          'docs/validation.json','docs/support-validation.json','docs/screenshots/*.png',
          'data/b1-requirements.json','data/curriculum.json','data/sources/*人才培养方案.pdf',
          'data/sources/附件1：任务清单-真实需求(1).xlsx',
          'web/vendor/echarts/echarts.common.min.js','web/vendor/echarts/LICENSE','web/vendor/echarts/NOTICE',
          'web/vendor/echarts/LICENSE-d3','web/vendor/echarts/source.json','web/media/study-desk.webp',
          'web/media/study-desk.webp.json','web/media/course-arts.webp','web/media/course-arts.webp.json',
          'web/media/course-science.webp','web/media/course-science.webp.json')
files={f for pattern in patterns for f in root.glob(pattern) if f.is_file() and not f.is_symlink()}
with ZipFile(archive,'w',ZIP_DEFLATED) as z:
    for file in sorted(files):
        z.write(file,Path('zhixue')/file.relative_to(root))
with ZipFile(archive) as z:
    if z.testzip() is not None:raise RuntimeError('压缩包校验失败')
    assert 'zhixue/run.py' in z.namelist()
    assert {'zhixue/start.bat','zhixue/web/index.html','zhixue/web/independent.js',
            'zhixue/web/independent.css','zhixue/web/media/study-desk.webp',
            'zhixue/web/plan-evidence.js','zhixue/web/plan-evidence.css'} <= set(z.namelist())
    if campus:
        assert {'zhixue/start-campus.bat','zhixue/web/campus.html','zhixue/web/campus-module.html',
                'zhixue/web/campus-risk.js','zhixue/server/campus.py','zhixue/server/selection_risk.py',
                'zhixue/server/credit_accounting.py','zhixue/web/campus-portrait.js','zhixue/web/campus-registers.js',
                'zhixue/web/campus-trend.js','zhixue/web/vendor/echarts/echarts.common.min.js','zhixue/web/vendor/echarts/LICENSE',
                'zhixue/README.md'} <= set(z.namelist())
    assert not any('/var/' in p or '/.venv/' in p for p in z.namelist())
    assert not any(p.endswith(('.sqlite3','.sqlite','.db','-wal','-shm')) for p in z.namelist())
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
(archive.with_suffix('.sha256') if campus or options.independent else out/'SHA256.txt').write_text(digest+'  '+archive.name+'\n',encoding='utf-8')
print(str(archive));print(f'{archive.stat().st_size:,} bytes');print('SHA256 '+digest)
