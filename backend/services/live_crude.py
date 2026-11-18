"""MCX quotes independently of slow EIA daily downloads. No simulated ticks."""
import math,sqlite3,time
from pathlib import Path
from datetime import datetime,timedelta
from threading import Lock
from fastapi import APIRouter
from . import oi_signal as shared
from .energy_service import official_prices
router=APIRouter();lock=Lock();cached=None;cached_at=0;contract=None;contract_day=None;histories={}
DB=Path(__file__).resolve().parents[1]/'data'/'mcx-crude-quotes.sqlite3'

def valid(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and v>0

def merge_points(history,observed,quote_time,price):
    values={int(p['time']):float(p['value']) for p in history+observed if int(p['time'])<=quote_time and valid(p.get('value'))}
    values[quote_time]=float(price)
    return [dict(time=t,value=values[t]) for t in sorted(values)]

def save_quote(symbol,ts,price):
    day=datetime.fromtimestamp(ts,shared.IST).date()
    start=int(datetime.combine(day,datetime.min.time(),tzinfo=shared.IST).timestamp());end=start+86400
    DB.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DB,timeout=15) as db:
        db.execute('CREATE TABLE IF NOT EXISTS quotes (symbol TEXT,time INTEGER,price REAL,PRIMARY KEY(symbol,time))')
        db.execute('INSERT OR REPLACE INTO quotes VALUES (?,?,?)',(symbol,ts,price))
        return [dict(time=t,value=p) for t,p in db.execute('SELECT time,price FROM quotes WHERE symbol=? AND time>=? AND time<? ORDER BY time',(symbol,start,end))]

def historical_points(kite,item,ts):
    day=datetime.fromtimestamp(ts,shared.IST).date();key=(item['tradingsymbol'],day.isoformat())
    old=histories.get(key)
    if old and time.monotonic()-old['at']<300:return old['points'],old['error']
    points=[];error=None
    try:
        end=datetime.fromtimestamp(ts,shared.IST);start=datetime.combine(day,datetime.min.time(),tzinfo=shared.IST)
        for r in kite.historical_data(item['instrument_token'],start,end,'5minute'):
            dt=r['date'];dt=dt.replace(tzinfo=shared.IST) if dt.tzinfo is None else dt
            # Historical close is known at bar-end, not its opening timestamp.
            closed=int(dt.timestamp())+300
            if dt.astimezone(shared.IST).date()==day and closed<=ts and valid(r.get('close')):points.append(dict(time=closed,value=r['close']))
    except Exception:error='Historical access unavailable; showing persisted actual quote observations.'
    histories[key]=dict(at=time.monotonic(),points=points,error=error)
    return points,error

@router.get('/api/energy/crude/daily')
def daily():return official_prices()

@router.get('/api/energy/crude/live')
def live():
    global cached,cached_at,contract,contract_day
    with lock:
        if cached and time.monotonic()-cached_at<5:return cached
        try:
            now=datetime.now(shared.IST);kite=shared.kite_client()
            if contract_day!=now.date():
                listed=[r for r in kite.instruments('MCX') if r.get('name')=='CRUDEOIL' and r.get('instrument_type')=='FUT' and shared.expiry_date(r['expiry'])>=now.date()]
                if not listed:raise ValueError('No MCX crude contract')
                contract=min(listed,key=lambda r:shared.expiry_date(r['expiry']));contract_day=now.date()
            key='MCX:'+contract['tradingsymbol'];q=kite.quote([key]).get(key,{})
            price=q.get('last_price')
            if not valid(price):raise ValueError('Missing MCX price')
            ts=shared.provider_time(q.get('timestamp'))
            if ts>now.timestamp()+5:raise ValueError('Quote time ahead of server')
            observed=save_quote(contract['tradingsymbol'],ts,price)
            history,note=historical_points(kite,contract,ts)
            points=merge_points(history,observed,ts,price)
            close=q.get('ohlc',{}).get('close');change=price-close if valid(close) else None
            age=max(0,int(time.time()-ts))
            result=dict(status='fresh' if age<=90 else 'stale',symbol=contract['tradingsymbol'],price=price,
                quote_time=ts,age_seconds=age,fetched_at=int(time.time()),expiry=str(contract['expiry']),source='Kite / MCX',
                change=round(change,2) if change is not None else None,change_pct=round(change/close*100,2) if change is not None else None,
                history=points,history_date=datetime.fromtimestamp(ts,shared.IST).date().isoformat(),history_error=note,
                history_mode='Completed 5m closes + actual persisted live quotes',poll_seconds=5)
        except Exception:
            result=dict(cached or {},status='unavailable',error='MCX refresh failed: check active Kite session, MCX quote access and backend/data write permissions.',request_failed_at=int(time.time()))
        cached=result;cached_at=time.monotonic();return result
