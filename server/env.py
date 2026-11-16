"""Load key-value pairs from a local .env file into the process environment.

Only used on the operator's own machine: .env is listed in .gitignore, so the
model key never enters the repository. Values already present in the real
environment win, which keeps deployment settings authoritative.
"""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ENV_FILE=ROOT/'.env'
loaded=False

def _unquote(value):
    if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):
        return value[1:-1]
    return value

def load_env(path=None):
    """Read .env once. Missing file is not an error."""
    global loaded
    if loaded:
        return
    loaded=True
    target=Path(path) if path else ENV_FILE
    try:
        text=target.read_text(encoding='utf-8-sig')
    except (FileNotFoundError,OSError,UnicodeDecodeError):
        return
    import os
    for raw in text.splitlines():
        line=raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        if line.startswith('export '):
            line=line[7:].lstrip()
        name,_,value=line.partition('=')
        name=name.strip()
        if not name or not name.replace('_','').isalnum():
            continue
        value=_unquote(value.strip())
        os.environ.setdefault(name,value)
