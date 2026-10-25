"""A scoped conversational agent with bounded tool rounds and human-applied drafts.

No model is allowed to invent a student's score or issue a counseling decision.
Without credentials the same tools are selected by a small, explicit intent router.
"""
import json
import re
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from .core import connection,current_user,require_admin,visible_student,curriculum,audit,TERM

router=APIRouter()
memory_key=''

def config():
    with connection() as db:
        row=db.execute("SELECT value FROM settings WHERE key='ai'").fetchone()
    return json.loads(row['value']) if row else {'mode':'local','baseUrl':'','model':''}

def ai_public():
    import os
    cfg=config()
    return {**cfg,'hasKey':bool(memory_key or os.getenv('ZHIXUE_API_KEY')),'note':'本地模式执行学情核对与行动规划流程；模型模式可读取工具结果并继续查询。行动草案需点击采纳才写入，数字核验不能替代人工复核。网页密钥仅存服务内存。'}

class AISettings(BaseModel):
    mode:str='local'
    baseUrl:str=''
    model:str=''
    apiKey:str|None=None

@router.get('/api/admin/ai')
def get_ai(user=Depends(current_user)):
    require_admin(user);return ai_public()

@router.put('/api/admin/ai')
def set_ai(body:AISettings,user=Depends(current_user)):
    global memory_key
    require_admin(user)
    if body.mode not in ('local','remote'):raise HTTPException(422,'模式须为local或remote')
    base=body.baseUrl.strip().rstrip('/')
    if base.endswith('/chat/completions'):base=base[:-17]
    if body.mode=='remote':
        parsed=urlsplit(base)
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password:
            raise HTTPException(422,'请填写有效模型服务地址')
        if not body.model.strip():raise HTTPException(422,'请填写模型名称')
    if body.apiKey is not None and body.apiKey.strip():memory_key=body.apiKey.strip()
    cfg={'mode':body.mode,'baseUrl':base,'model':body.model.strip()}
    with connection() as db:
        db.execute("INSERT INTO settings VALUES ('ai',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(cfg),))
        audit(db,user['id'],'修改助手配置',{'mode':body.mode,'model':body.model})
    return ai_public()

def model_request(messages,tools=None):
    import os
    cfg=config();key=memory_key or os.getenv('ZHIXUE_API_KEY','')
    if not key:raise ValueError('尚未配置API密钥')
    payload={'model':cfg['model'],'messages':messages,'temperature':0.1}
    if tools:payload.update({'tools':tools,'tool_choice':'auto'})
    with httpx.Client(timeout=18,follow_redirects=False) as client:
        response=client.post(cfg['baseUrl']+'/chat/completions',headers={'Authorization':'Bearer '+key},json=payload)
        response.raise_for_status()
    return response.json()['choices'][0]['message']

@router.post('/api/admin/ai/test')
def test_ai(user=Depends(current_user)):
    require_admin(user)
    if config()['mode']=='local':return {'ok':True,'mode':'local','message':'本地学情工具已就绪，无需模型连接。'}
    try:
        result=model_request([{'role':'user','content':'连接测试，请回复OK。'}])
        return {'ok':bool(result.get('content')),'mode':'remote','message':'模型服务已返回响应。'}
    except httpx.HTTPStatusError as exc:
        return {'ok':False,'mode':'remote','message':f'模型服务返回HTTP {exc.response.status_code}，请核对地址、模型和密钥。'}
    except Exception:
        return {'ok':False,'mode':'remote','message':'模型服务暂不可用，请检查配置和网络。'}

from .agent_runtime import (TOOLS, ensure_schema, run_turn, list_threads, get_thread, apply_proposal)


class Question(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    studentId: str | None = Field(default=None, max_length=80)
    threadId: str | None = Field(default=None, max_length=80)
    contextOverride: bool = False


@router.post('/api/assistant')
def ask(body: Question, user=Depends(current_user)):
    if not body.message.strip():
        raise HTTPException(422, '请填写要核对的问题')
    return run_turn(user, body.message.strip(), body.studentId, body.threadId,
                    config()['mode'] == 'remote', model_request, body.contextOverride)


@router.get('/api/assistant/threads')
def threads(user=Depends(current_user)):
    return list_threads(user)


@router.get('/api/assistant/threads/{thread_id}')
def thread(thread_id: str, user=Depends(current_user)):
    return get_thread(user, thread_id)


@router.post('/api/assistant/proposals/{proposal_id}/apply')
def apply(proposal_id: str, user=Depends(current_user)):
    return apply_proposal(user, proposal_id)
