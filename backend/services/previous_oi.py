"""Asynchronous actual previous-session closing OI; never uses login-time snapshots."""
import sqlite3,time
from pathlib import Path
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from . import oi_signal as shared
DB=Path(__file__).resolve().parents[1]/'data'/'previous-close-oi.sqlite3'
_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='previous-close-oi')
_lock=Lock();_jobs={};_last_request=0.0

def connect():
 DB.parent.mkdir(parents=True,exist_ok=True)
 db=sqlite3.connect(DB,timeout=15)
 db.execute('CREATE TABLE IF NOT EXISTS previous_oi (day TEXT,contract TEXT,token INTEGER,baseline_day TEXT,oi INTEGER,status TEXT,updated REAL,PRIMARY KEY(day,contract,token))')
 return db

def historical(kite,token,start,end,oi):
 global _last_request
 delay=1.05-(time.monotonic()-_last_request)
 if delay>0:time.sleep(delay)
 _last_request=time.monotonic()
 return kite.historical_data(token,start,end,'day',oi=oi)

def record_day(value):
 if isinstance(value,str):return datetime.fromisoformat(value.replace('Z','+00:00')).date()
 return value.date()

def select_previous(records,previous):
 for row in reversed(records):
  oi=row.get('oi')
  if record_day(row['date'])==previous and isinstance(oi,(int,float)) and not isinstance(oi,bool) and oi>=0:
   return int(oi)
 return None

def fetch_batch(day,contracts):
 now=datetime.fromisoformat(day).replace(tzinfo=shared.IST)
 end=now-timedelta(seconds=1);start=now-timedelta(days=30)
 try:
  kite=shared.kite_client()
  sessions=historical(kite,256265,start,end,False)
  dates=[record_day(r['date']) for r in sessions if record_day(r['date'])<now.date()]
  if not dates:raise ValueError('No previous trading session')
  previous=max(dates)
  for key,token in contracts:
   oi=None;status='unavailable'
   try:
    records=historical(kite,token,datetime.combine(previous,datetime.min.time(),tzinfo=shared.IST),end,True)
    oi=select_previous(records,previous);status='ok' if oi is not None else 'unavailable'
   except Exception:pass
   with connect() as db:db.execute('INSERT OR REPLACE INTO previous_oi VALUES (?,?,?,?,?,?,?)',(day,key,token,previous.isoformat(),oi,status,time.time()))
 except Exception:
  with connect() as db:
   for key,token in contracts:db.execute('INSERT OR REPLACE INTO previous_oi VALUES (?,?,?,?,?,?,?)',(day,key,token,None,None,'unavailable',time.time()))

def previous_baselines(day,contracts):
 """Nonblocking request; return only verified previous-session baselines already loaded."""
 result={};pending=[]
 with _lock:
  with connect() as db:
   for key,token in contracts:
    row=db.execute('SELECT baseline_day,oi,status,updated FROM previous_oi WHERE day=? AND contract=? AND token=?',(day,key,token)).fetchone()
    if row and row[2]=='ok':result[key]=(row[1],row[0]);continue
    old=_jobs.get((day,key,token))
    if old and not old.done():continue
    if row and time.time()-row[3]<300:continue
    pending.append((key,token))
  if pending:
   job=_pool.submit(fetch_batch,day,pending)
   for key,token in pending:_jobs[(day,key,token)]=job
 return result
