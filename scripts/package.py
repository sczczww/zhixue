"""Package only the independent project, excluding local state and credentials."""
import hashlib
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED

root=Path(__file__).resolve().parents[1]
out=root.parent/'deliverables'
out.mkdir(exist_ok=True)
archive=out/'知学-B1-完整项目.zip'
ignored={'.venv','var','tmp','__pycache__','.git','node_modules'}
with ZipFile(archive,'w',ZIP_DEFLATED) as z:
    for file in sorted(root.rglob('*')):
        rel=file.relative_to(root)
        if file.is_file() and not any(p in ignored for p in rel.parts) and file.name!='.env' and file.suffix not in ('.pyc','.log','.sqlite3','.sqlite','.db','.wal','.shm') and not file.name.endswith(('-wal','-shm')):
            z.write(file,Path('zhixue')/rel)
with ZipFile(archive) as z:
    if z.testzip() is not None:raise RuntimeError('压缩包校验失败')
    assert 'zhixue/run.py' in z.namelist()
    assert not any('/var/' in p or '/.venv/' in p for p in z.namelist())
    assert not any(p.endswith(('.sqlite3','.sqlite','.db','-wal','-shm')) for p in z.namelist())
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
(out/'SHA256.txt').write_text(digest+'  '+archive.name+'\n',encoding='utf-8')
print(str(archive));print(f'{archive.stat().st_size:,} bytes');print('SHA256 '+digest)
