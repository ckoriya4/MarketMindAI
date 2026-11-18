"""Local dashboard: official Kite browser login, server-side one-time exchange."""
import os,secrets,time,threading
from pathlib import Path
from urllib.parse import urlencode
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv,set_key
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException
BASE=Path(__file__).resolve().parents[1]
router=APIRouter();lock=threading.Lock();pending={};cached={}
COOKIE='kite_login_state'

def local(request):
    if request.client is None or request.client.host not in ('127.0.0.1','::1','localhost','testclient') or request.url.hostname not in ('127.0.0.1','localhost','testserver'):
        raise HTTPException(403,'This login integration is for your local dashboard only.')

def config():
    load_dotenv(BASE/'.env',override=True)
    key=os.getenv('KITE_API_KEY','').strip();secret=os.getenv('KITE_API_SECRET','').strip()
    if not key or not secret:raise HTTPException(503,'Set KITE_API_KEY and KITE_API_SECRET once in backend/.env. Register the callback URL in the Kite developer console.')
    return key,secret

def clean(response):
    response.headers['Cache-Control']='no-store';response.headers['Referrer-Policy']='no-referrer'
    return response

def finish(message):
    response=RedirectResponse('http://127.0.0.1:5173/?kite_login='+message,status_code=303)
    response.delete_cookie(COOKIE,path='/api/auth/kite')
    return clean(response)

@router.get('/api/auth/kite/login')
def login(request:Request):
    local(request);key,_=config();state=secrets.token_urlsafe(32)
    with lock:
        for value,created in list(pending.items()):
            if time.monotonic()-created>600:pending.pop(value,None)
        if len(pending)>=100:raise HTTPException(429,'Too many pending logins; retry later.')
        pending[state]=time.monotonic()
    # Official redirect_params is returned to the registered callback URL.
    query=urlencode(dict(v=3,api_key=key,redirect_params=urlencode(dict(state=state))))
    response=RedirectResponse('https://kite.zerodha.com/connect/login?'+query,status_code=303)
    response.set_cookie(COOKIE,state,max_age=600,httponly=True,samesite='lax',path='/api/auth/kite')
    return clean(response)

@router.get('/api/auth/kite/callback')
def callback(request:Request):
    local(request)
    params=dict(request.query_params)
    request.scope['query_string']=b'' # Avoid callback request_token in default Uvicorn access logs.
    state=params.get('state','');cookie=request.cookies.get(COOKIE,'')
    if not state or not cookie or not secrets.compare_digest(state,cookie):return finish('invalid_state')
    with lock:created=pending.pop(state,None)
    if created is None or time.monotonic()-created>600:return finish('expired_login')
    token=params.get('request_token','')
    if params.get('status')!='success' or not token or len(token)>512:return finish('cancelled')
    try:
        key,secret=config();kite=KiteConnect(api_key=key,timeout=12)
        session=kite.generate_session(token,api_secret=secret)
        access=session.get('access_token')
        if not isinstance(access,str) or not access:raise ValueError('Missing access token')
        # dotenv helper uses atomic replacement; never return/log secret material.
        with lock:
            set_key(str(BASE/'.env'),'KITE_ACCESS_TOKEN',access,quote_mode='always')
            try:os.chmod(BASE/'.env',0o600)
            except OSError:pass
            os.environ['KITE_ACCESS_TOKEN']=access
            cached.clear()
        return finish('success')
    except Exception:return finish('exchange_failed')

@router.get('/api/auth/kite/status')
def status(request:Request):
    local(request)
    try:key,_=config()
    except HTTPException:return clean_json(dict(state='setup_required'))
    token=os.getenv('KITE_ACCESS_TOKEN','').strip()
    if not token:return clean_json(dict(state='login_required'))
    with lock:
        if cached.get('token')==token and time.monotonic()-cached.get('at',0)<60:return clean_json(dict(state=cached['state']))
    try:
        kite=KiteConnect(api_key=key,timeout=8);kite.set_access_token(token);kite.profile();value='connected'
    except TokenException:value='login_required'
    except Exception:value='connection_unverified'
    with lock:cached.update(token=token,at=time.monotonic(),state=value)
    return clean_json(dict(state=value))

def clean_json(data):
    from fastapi.responses import JSONResponse
    return clean(JSONResponse(data))
