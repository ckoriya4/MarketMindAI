"""Backend-owned OI recording and historical minute-OI reconstruction."""
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from . import oi_signal as shared
from .dynamic_oi import prepare_db, dynamic_oi_signals, strike_selection, plain_total
from .market_session import session_bounds
from fastapi import HTTPException


def scope_for(day, profile, expiry):
    return f"directsum-v3:{day}:{profile['symbol']}:{expiry}:{profile['side']}:{profile['itm']}"


def parse_expiry(value):
    if not value:return None
    try:return date.fromisoformat(value).isoformat()
    except ValueError:
        try:return datetime.strptime(value,'%d-%b-%Y').date().isoformat()
        except ValueError:raise HTTPException(422,'Invalid expiry.') from None


def minute_map(records, day, now, require_oi=False):
    result={}
    for r in records:
        dt=r['date']
        if isinstance(dt,str):dt=datetime.fromisoformat(dt)
        if dt.tzinfo is None:dt=dt.replace(tzinfo=shared.IST)
        ts=int(dt.timestamp())
        if dt.astimezone(shared.IST).date()!=day or ts+60>now:continue
        value=r.get('oi') if require_oi else r.get('close')
        if not isinstance(value,(int,float)) or not math.isfinite(value) or require_oi and value<0:continue
        result[ts]=value
    return result


def rebuild_history(db, scope, historical):
    """Atomic merge; live observations win exact timestamp collisions."""
    db.execute('BEGIN IMMEDIATE')
    try:
        merged={p['time']:p for p in historical}
        existing=db.execute('SELECT time,put_oi,call_oi,selection FROM dynamic_oi_samples WHERE scope=? ORDER BY time',(scope,)).fetchall()
        for ts,p,c,selection in existing:
            origin=db.execute('SELECT source,spot FROM dynamic_oi_origins WHERE scope=? AND time=?',(scope,ts)).fetchone()
            if ts not in merged or not origin or origin[0]=='live':
                merged[ts]={'time':ts,'put_oi':p,'call_oi':c,'selection':json.loads(selection),
                            'source':origin[0] if origin else 'live','spot':origin[1] if origin else None}
        rows=[];origins=[];segment=0;previous=None;pb=cb=0
        for ts,p in sorted(merged.items()):
            selection=p['selection'];encoded=json.dumps(selection,sort_keys=True)
            if encoded!=previous:
                segment+=1;pb=p['put_oi'];cb=p['call_oi'];previous=encoded
            rows.append((scope,ts,segment,selection['anchor'],selection['step'],p['put_oi'],p['call_oi'],p['put_oi']-pb,p['call_oi']-cb,encoded))
            origins.append((scope,ts,p.get('source','historical-minute'),p.get('spot')))
        db.execute('DELETE FROM dynamic_oi_samples WHERE scope=?',(scope,))
        db.execute('DELETE FROM dynamic_oi_origins WHERE scope=?',(scope,))
        db.executemany('INSERT INTO dynamic_oi_samples VALUES (?,?,?,?,?,?,?,?,?,?)',rows)
        db.executemany('INSERT INTO dynamic_oi_origins VALUES (?,?,?,?)',origins)
        db.commit()
    except Exception:
        db.rollback();raise


class SessionRecorder:
    def __init__(self):
        self.stop_event=threading.Event()
        self.mutex=threading.RLock()
        self.targets={};self.jobs={};self.job_status={}
        self.thread=None;self.pool=None

    def db(self):
        db=prepare_db()
        db.execute('CREATE TABLE IF NOT EXISTS oi_recorder_targets (id TEXT PRIMARY KEY, config TEXT, scope TEXT, error TEXT)')
        return db

    def start(self):
        with self.mutex:
            if self.thread and self.thread.is_alive():return
            self.stop_event.clear()
            db=self.db()
            for key,config,scope,error in db.execute('SELECT id,config,scope,error FROM oi_recorder_targets'):
                self.targets[key]={'profile':json.loads(config),'scope':scope,'error':error}
            db.close()
            self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='oi-backfill')
            self.register('NIFTY',None,3,0)
            self.thread=threading.Thread(target=self.run,name='oi-session-recorder',daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=3)
        if self.pool:self.pool.shutdown(wait=False,cancel_futures=True)

    def register(self,symbol,expiry,side,itm):
        profile={'symbol':symbol,'expiry':parse_expiry(expiry),'side':3,'itm':0}
        key=json.dumps(profile,sort_keys=True)
        with self.mutex:
            if key not in self.targets:
                self.targets[key]={'profile':profile,'scope':None,'error':None}
                db=self.db();db.execute('INSERT OR IGNORE INTO oi_recorder_targets VALUES (?,?,?,?)',(key,key,None,None));db.commit();db.close()
        return key

    def state(self,key,scope=None,error=None):
        with self.mutex:
            target=self.targets[key]
            if scope:target['scope']=scope
            target['error']=error
            db=self.db();db.execute('UPDATE oi_recorder_targets SET scope=?,error=? WHERE id=?',(target['scope'],error,key));db.commit();db.close()

    def resolve(self,profile,day):
        with shared.lock:
            kite=shared.kite_client()
            available=sorted({shared.expiry_date(i['expiry']) for i in shared.instruments(kite,day)
                              if i.get('name')==profile['symbol'] and i.get('instrument_type') in ('CE','PE')
                              and shared.expiry_date(i['expiry'])>=day})
        selected=date.fromisoformat(profile['expiry']) if profile['expiry'] else available[0] if available else None
        if selected is None or selected not in available:raise ValueError('No valid current expiry for recording target')
        return scope_for(day,profile,selected),selected

    def queue_backfill(self,scope,profile):
        if os.getenv('OI_BACKFILL_ENABLED','true').lower() not in ('1','true','yes'):return
        with self.mutex:
            old=self.jobs.get(scope)
            if self.pool is None:return
            if old is not None and (not old.done() or self.job_status.get(scope,{}).get('status')=='complete' or time.time()-self.job_status.get(scope,{}).get('attempted_at',0)<900):return
            self.job_status[scope]={'status':'queued','attempted_at':time.time()}
            self.jobs[scope]=self.pool.submit(self.backfill,scope,dict(profile))

    def run(self):
        while not self.stop_event.is_set():
            now=datetime.now(shared.IST);day=now.date();bounds=session_bounds(day,derivatives=True)
            if day.weekday()<5 and now.timestamp()>=bounds['open']:
                with self.mutex:targets=[(k,dict(v['profile'])) for k,v in self.targets.items()]
                collected=set()
                for key,profile in targets:
                    if self.stop_event.is_set():break
                    try:
                        scope,selected=self.resolve(profile,day)
                        self.state(key,scope=scope)
                        if now.timestamp()>=bounds['open']+60:self.queue_backfill(scope,profile)
                        if now.timestamp()<=bounds['close'] and scope not in collected:
                            dynamic_oi_signals(profile['symbol'],selected.isoformat(),profile['side'],profile['itm'],record_only=True)
                            collected.add(scope)
                    except Exception as exc:
                        message=exc.detail if isinstance(exc,HTTPException) else 'Recorder cannot resolve/collect this target. Check token and quote permissions.'
                        self.state(key,error=message)
            try:interval=max(5,float(os.getenv('OI_COLLECT_INTERVAL_SECONDS','5')))
            except ValueError:interval=5
            self.stop_event.wait(interval)

    def historical_call(self,kite,token,start,end,oi=False):
        if self.stop_event.wait(1.0):raise RuntimeError('Backfill stopped')
        return kite.historical_data(token,start,end,'minute',oi=oi)

    def backfill(self,scope,profile):
        try:
            attempted=time.time()
            self.job_status[scope]={'status':'running','attempted_at':attempted}
            _,day_text,symbol,expiry_text,_,_=scope.split(':')
            day=date.fromisoformat(day_text);expiry=date.fromisoformat(expiry_text)
            bounds=session_bounds(day,derivatives=True)
            now=time.time();end_ts=min(now,bounds['close'])
            start=datetime.fromtimestamp(bounds['open'],shared.IST)
            end=datetime.fromtimestamp(end_ts,shared.IST)
            kite=shared.kite_client()
            with shared.lock:
                options=[i for i in shared.instruments(kite,day) if i.get('name')==symbol
                         and i.get('instrument_type') in ('PE','CE') and shared.expiry_date(i['expiry'])==expiry]
            underlying=shared.INDEX[symbol][0]
            token=kite.quote([underlying]).get(underlying,{}).get('instrument_token')
            if token is None:raise ValueError('Index token missing')
            spots=minute_map(self.historical_call(kite,token,start,end),day,now)
            spots={ts:value for ts,value in spots.items() if bounds['open']<=ts<bounds['close']}
            by_contract={(int(i['strike']),i['instrument_type']):i for i in options}
            windows={};required=set()
            for ts,spot in spots.items():
                selection=strike_selection(spot,[i['strike'] for i in options],profile['side'],profile['itm'])
                keys={(s,'PE') for s in selection['put_strikes']} | {(s,'CE') for s in selection['call_strikes']}
                if not keys.issubset(by_contract):continue
                windows[ts]=(selection,keys);required|=keys
            histories={}
            for index,key in enumerate(sorted(required)):
                if self.stop_event.is_set():raise RuntimeError('Backfill stopped')
                histories[key]=minute_map(self.historical_call(kite,by_contract[key]['instrument_token'],start,end,oi=True),day,now,require_oi=True)
                self.job_status[scope]={'status':'running','attempted_at':attempted,'contracts_done':index+1,'contracts_total':len(required)}
            samples=[]
            for ts,(selection,keys) in sorted(windows.items()):
                # Exact same-minute OI for every selected contract. Never forward-fill a missing leg.
                if not all(ts in histories[k] for k in keys):continue
                samples.append({'time':ts+60,'selection':selection,'spot':spots[ts],
                    'put_oi':int(plain_total(selection,'PE',{k:histories[k][ts] for k in keys})),
                    'call_oi':int(plain_total(selection,'CE',{k:histories[k][ts] for k in keys})),
                    'source':'historical-minute'})
            if samples:
                with shared.lock:
                    db=self.db()
                    try:rebuild_history(db,scope,samples)
                    finally:db.close()
            self.job_status[scope]={'status':'complete' if len(samples)==len(spots) and samples else 'partial',
                                    'attempted_at':attempted,'historical_minutes':len(samples),'candidate_minutes':len(spots),
                                    'note':'Historical observations are timestamped at minute close. Missing contract-minute OI stays blank.'}
        except Exception:
            self.job_status[scope]={'status':'unavailable','attempted_at':time.time(),'note':'Historical backfill unavailable. Check Kite historical/OI permissions; live recording continues.'}

    def status(self):
        with self.mutex:
            return {'running':bool(self.thread and self.thread.is_alive()),
                    'time':datetime.now(shared.IST).isoformat(),
                    'targets':[{'profile':dict(v['profile']),'scope':v['scope'],'last_error':v['error'],
                                'backfill':dict(self.job_status.get(v['scope'],{'status':'waiting'}))} for v in self.targets.values()]}

    def read(self,symbol,expiry,side,itm):
        key=self.register(symbol,expiry,side,itm)
        with self.mutex:target=dict(self.targets[key])
        scope=target['scope']
        if not scope:raise HTTPException(503,'Recorder is starting. Waiting for the current expiry/session. Keep backend running.')
        with shared.lock:
            db=self.db()
            try:
                rows=db.execute('SELECT time,segment,atm,step,put_oi,call_oi,put_change,call_change,selection FROM dynamic_oi_samples WHERE scope=? ORDER BY time',(scope,)).fetchall()
                origins={r[0]:(r[1],r[2]) for r in db.execute('SELECT time,source,spot FROM dynamic_oi_origins WHERE scope=?',(scope,))}
            finally:db.close()
        if not rows:raise HTTPException(503,target['error'] or 'No recorded OI yet. Background collection/backfill is in progress.')
        points=[{'time':r[0],'segment':r[1],'atm':r[2],'step':r[3],'put_oi':r[4],'call_oi':r[5],
                 'put_change':r[6],'call_change':r[7],'source':origins.get(r[0],('live',None))[0]} for r in rows]
        latest=points[-1];selection=json.loads(rows[-1][8]);current=[p for p in points if p['segment']==latest['segment']]
        _,day_text,_,expiry_text,_,_=scope.split(':');age=max(0,int(time.time()-latest['time']))
        return {'source':'kite','selection_mode':'dynamic-direct-sum','status':'fresh' if age<=30 and latest['source']=='live' else 'stale',
                'scope':scope,'symbol':symbol,'expiry':expiry_text,'spot':origins.get(latest['time'],('',None))[1],
                **selection,'strikes':sorted(set(selection['put_strikes']+selection['call_strikes'])),
                'contract_count':len(selection['put_strikes'])+len(selection['call_strikes']),
                'points':points,'latest':latest,'baseline_time':current[0]['time'],'segment':latest['segment'],
                'segment_points':len(current),'observations':len(points),'session':session_bounds(date.fromisoformat(day_text),derivatives=True),
                'quote_time':latest['time'],'age_seconds':age,'fetched_at':datetime.now(timezone.utc).isoformat(),
                'collector':{'running':bool(self.thread and self.thread.is_alive()),'last_error':target['error'],
                             'backfill':self.job_status.get(scope,{'status':'waiting'})},
                'history_source':'Saved live snapshots + available historical minute OI',
                'history_start':points[0]['time'],
                'historical_samples':sum(p['source']=='historical-minute' for p in points),
                'live_samples':sum(p['source']=='live' for p in points)}


recorder=SessionRecorder()
