"""Four-sector OI, full-session timeline, exact combined sum and historical reconstruction."""
import hashlib,json,math,sqlite3,threading,time
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,date,timedelta
from fastapi import APIRouter
from . import oi_signal as shared
from .stock_option_data import collector
from .market_session import session_bounds
router=APIRouter();DB=Path(__file__).resolve().parents[1]/'data'/'sector-session-v3.sqlite3'
SECTORS=('Financial Services','Information Technology','Oil, Gas & Consumable Fuels','FMCG')
job_lock=threading.Lock();jobs={}
def sector_name(value):
    import re
    text=re.sub(r'[^a-z0-9]+',' ',value.casefold().replace('&','and')).strip()
    return {'financial services':SECTORS[0],'information technology':SECTORS[1],
        'oil gas and consumable fuels':SECTORS[2],'oil gas consumable fuels':SECTORS[2],
        'fast moving consumer goods':SECTORS[3],'fmcg':SECTORS[3]}.get(text)
@contextmanager
def connect():
    DB.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(DB,timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS config (scope TEXT PRIMARY KEY,payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS raw (scope TEXT,time INTEGER,sector TEXT,call REAL,put REAL,origin TEXT,PRIMARY KEY(scope,time,sector))')
    db.execute('CREATE TABLE IF NOT EXISTS contract_history (scope TEXT,token INTEGER,payload TEXT,PRIMARY KEY(scope,token))')
    try:
        yield db
        db.commit()
    finally:db.close()

def combine(values):
    complete=all(name in values and all(values[name].get(k) is not None for k in ('call','put')) for name in SECTORS)
    return {k:sum(values[name][k] for name in SECTORS) if complete else None for k in ('call','put','total')}
def derive(rows):
    baselines={};points={}
    for ts,name,call,put,origin in sorted(rows):
        if name not in baselines:baselines[name]=(ts,call,put)
        b=baselines[name];c,p=call-b[1],put-b[2]
        points.setdefault(ts,{})[name]=dict(call=c,put=p,total=c+p)
    result=[]
    for ts,values in sorted(points.items()):
        for name in SECTORS:values.setdefault(name,dict(call=None,put=None,total=None))
        values['Combined']=combine(values);result.append(dict(time=ts,values=values))
    return result,{name:b[0] for name,b in baselines.items()}

def absolute_points(rows):
    points={}
    for ts,name,call,put,origin in rows:
        points.setdefault(ts,{})[name]=dict(call=call,put=put,total=call+put)
    result=[]
    for ts,values in sorted(points.items()):
        for name in SECTORS:values.setdefault(name,dict(call=None,put=None,total=None))
        values['Combined']=combine(values)
        result.append(dict(time=ts,values=values))
    return result


def put_raw(db,scope,ts,name,call,put,origin):
    old=db.execute('SELECT origin FROM raw WHERE scope=? AND time=? AND sector=?',(scope,ts,name)).fetchone()
    if old and old[0]=='live' and origin!='live':return
    db.execute('INSERT OR REPLACE INTO raw VALUES (?,?,?,?,?,?)',(scope,ts,name,call,put,origin))

def minute_oi(records,day,now):
    result={};bounds=session_bounds(day,derivatives=True)
    for r in records:
        dt=r.get('date');oi=r.get('oi')
        if not isinstance(dt,datetime):continue
        if dt.tzinfo is None:dt=dt.replace(tzinfo=shared.IST)
        ts=int(dt.timestamp())
        if bounds['open']<=ts<bounds['close'] and ts+60<=now and isinstance(oi,(int,float)) and not isinstance(oi,bool) and math.isfinite(oi) and oi>=0:result[ts]=oi
    return result

def rebuild(scope,config):
    try:
        day=date.fromisoformat(config['day']);bounds=session_bounds(day,derivatives=True)
        end=min(time.time(),bounds['close']);start=datetime.fromtimestamp(bounds['open'],shared.IST);finish=datetime.fromtimestamp(end,shared.IST)
        kite=shared.kite_client()
        with shared.lock:listed=shared.instruments(kite,day)
        groups={name:[] for name in SECTORS}
        members=config['members'];expiry=date.fromisoformat(config['expiry'])
        for r in listed:
            name=members.get(r.get('name'))
            if name and r.get('instrument_type') in ('CE','PE') and shared.expiry_date(r['expiry'])==expiry:groups[name].append(r)
        total=sum(map(len,groups.values()));done=0;errors=0
        jobs[scope]=dict(status='running',contracts_done=0,contracts_total=total,started=time.time())
        for name,contracts in groups.items():
            symbols={r['name'] for r in contracts}
            expected={s for s,n in members.items() if n==name}
            if not contracts or symbols!=expected:
                errors+=1;continue
            sums={};common=None;failed=False
            for contract in contracts:
                token=contract['instrument_token']
                with connect() as db:
                    saved=db.execute('SELECT payload FROM contract_history WHERE scope=? AND token=?',(scope,token)).fetchone()
                if saved:history={int(k):v for k,v in json.loads(saved[0]).items()}
                else:
                    try:
                        time.sleep(1.05) # <= one historical call/sec in this worker.
                        history=minute_oi(kite.historical_data(token,start,finish,'minute',oi=True),day,end)
                        if history:
                            with connect() as db:db.execute('INSERT OR REPLACE INTO contract_history VALUES (?,?,?)',(scope,token,json.dumps(history)))
                    except Exception:history={}
                done+=1;jobs[scope].update(contracts_done=done,sector=name)
                if not history:failed=True;errors+=1;continue
                common=set(history) if common is None else common.intersection(history)
                side='call' if contract['instrument_type']=='CE' else 'put'
                for ts,oi in history.items():sums.setdefault(ts,dict(call=0,put=0))[side]+=oi
            # Require every listed contract at exactly the same completed minute.
            if not failed and common:
                with connect() as db:
                    for ts in sorted(common):put_raw(db,scope,ts+60,name,sums[ts]['call'],sums[ts]['put'],'historical-minute')
        jobs[scope].update(status='partial' if errors else 'complete',failed_contracts=errors,finished=time.time(),note='Exact complete historical baskets only. Missing contract-minute OI stays blank. Cached history ends at the initial backfill request.')
    except Exception:
        jobs[scope]=dict(status='unavailable',finished=time.time(),note='Historical reconstruction unavailable. Check Kite historical/OI access; live data remains.')

def schedule(scope,config):
    with job_lock:
        previous=jobs.get(scope)
        if previous and (previous.get('status') in ('queued','running','complete') or time.time()-previous.get('finished',time.time())<900):return
        jobs[scope]=dict(status='queued')
        threading.Thread(target=rebuild,args=(scope,config),daemon=True,name='sector-history').start()

@router.get('/api/market/option-oi-status')
def option_oi_status():return collector.read()

@router.get('/api/market/sector-oi')
def sector_oi():
    state=collector.read();now=datetime.now(shared.IST);companies={s:r for s,r in state.get('companies',{}).items() if sector_name(r.get('sector',''))}
    bounds=session_bounds(now.date(),derivatives=True);scope=None;config=None;points=[];absolute=[];times={}
    with connect() as db:
        if companies and state.get('expiry'):
            config=dict(day=now.date().isoformat(),expiry=state['expiry'],universe=state.get('universe_id'),members={s:sector_name(r['sector']) for s,r in sorted(companies.items())})
            encoded=json.dumps(config,sort_keys=True);scope=hashlib.sha256(encoded.encode()).hexdigest()[:24]
            db.execute('INSERT OR REPLACE INTO config VALUES (?,?)',(scope,encoded))
            observed=int(state.get('fetched_at') or 0)
            if bounds['open']<=observed<=bounds['close'] and now.date()==datetime.fromtimestamp(observed,shared.IST).date():
                for name in SECTORS:
                    group=[r for r in companies.values() if sector_name(r.get('sector',''))==name]
                    if group and all(r.get('call') is not None and r.get('put') is not None for r in group):
                        put_raw(db,scope,observed//60*60,name,sum(r['call'] for r in group),sum(r['put'] for r in group),'live')
        else:
            row=db.execute('SELECT scope,payload FROM config ORDER BY rowid DESC LIMIT 1').fetchone()
            if row:scope,encoded=row;config=json.loads(encoded);bounds=session_bounds(date.fromisoformat(config['day']),derivatives=True)
        if scope:
            rows=db.execute('SELECT time,sector,call,put,origin FROM raw WHERE scope=? ORDER BY time',(scope,)).fetchall()
            points,times=derive(rows);absolute=absolute_points(rows)
    if scope and config:schedule(scope,config)
    coverage={}
    for name in SECTORS:
        group={s:r for s,r in companies.items() if sector_name(r.get('sector',''))==name}
        missing=[s for s,r in group.items() if r.get('call') is None or r.get('put') is None]
        coverage[name]=dict(expected=len(group),complete=len(group)-len(missing),missing=sorted(missing))
    from .sector_recording import recorder as sector_recorder
    return dict(recording=sector_recorder.status(),sector_coverage=coverage,status=state.get('status','starting'),error=state.get('error'),scope=scope,session=bounds,sectors=list(SECTORS),points=points,absolute_points=absolute,sector_company_counts={name:sum(sector_name(r.get('sector',''))==name for r in companies.values()) for name in SECTORS},source='kite',expiry=config['expiry'] if config else None,
        baseline_time=min(times.values()) if times else None,baseline_times=times,backfill=dict(jobs.get(scope,{'status':'waiting'})),
        contracts_total=state.get('contracts_total'),contracts_done=state.get('contracts_done'),company_count=len(companies),quoted_companies=sum(r.get('call') is not None and r.get('put') is not None for r in companies.values()),
        fetched_at=state.get('fetched_at'),collection_span_seconds=state.get('collection_span_seconds'),stage=state.get('stage'),
        definition='Combined is the exact sum of four sector changes at the same observation minute. Missing sector means unavailable, never zero. Each sector baseline is its earliest complete available basket.',
        warning='Full session axis does not guarantee complete historical coverage. Backfill may revise baselines; live baskets may include stale last-known OI.')
