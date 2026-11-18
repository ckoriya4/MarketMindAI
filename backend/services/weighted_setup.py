"""Weighted live OI setup. Scores measure rule agreement, never probability of profit."""
import json
import math
import sqlite3
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from threading import Lock
from fastapi import APIRouter,HTTPException,Query
from . import oi_signal as shared
from .option_chain import get_dynamic_option_chain

router=APIRouter();lock=Lock();cache={}
DB=Path(__file__).resolve().parents[1]/'data'/'weighted-setups.sqlite3'
WEIGHTS=(3,2,1)

def weights_for(spot,listed):
    strikes=sorted(set(listed));atm=min(strikes,key=lambda s:(abs(s-spot),-s))
    gaps=[b-a for a,b in zip(strikes,strikes[1:]) if b>a]
    if not gaps:raise HTTPException(503,'Strike interval unavailable')
    step=min(gaps)
    puts=[atm-i*step for i in range(3)];calls=[atm+i*step for i in range(3)]
    if not set(puts+calls).issubset(strikes):raise HTTPException(503,'Required ATM strikes are missing')
    return atm,step,puts,calls

def weighted_values(legs,base):
    details=[];totals={'PE':0,'CE':0}
    for leg in legs:
        delta=leg['oi']-base[leg['key']]
        value=delta*leg['weight'];totals[leg['type']]+=value
        details.append(dict(leg,change_oi=delta,weighted_change=value))
    return totals['PE'],totals['CE'],details

def record(db,scope,observed,atm,legs):
    db.execute('CREATE TABLE IF NOT EXISTS weighted_samples (scope TEXT,time INTEGER,segment INTEGER,atm REAL,selection TEXT,base TEXT,a REAL,b REAL,cross_time INTEGER,cross_direction INTEGER,PRIMARY KEY(scope,time))')
    selection=json.dumps([(l['key'],l['weight']) for l in legs])
    last=db.execute('SELECT time,segment,selection,base,a,b,cross_time,cross_direction FROM weighted_samples WHERE scope=? ORDER BY time DESC LIMIT 1',(scope,)).fetchone()
    if last and observed<last[0]:raise HTTPException(503,'Waiting for a newer OI snapshot')
    if last and observed==last[0]:
        if selection!=last[2]:raise HTTPException(503,'Waiting for new ATM basket timestamps')
        a,b,details=weighted_values(legs,json.loads(last[3]))
        # Do not mutate a stored point when the minimum provider timestamp has not advanced.
        return dict(a=last[4],b=last[5],segment=last[1],baseline_time=db.execute('SELECT MIN(time) FROM weighted_samples WHERE scope=? AND segment=?',(scope,last[1])).fetchone()[0],cross_time=last[6],cross_direction=last[7],details=None,observations=db.execute('SELECT COUNT(*) FROM weighted_samples WHERE scope=? AND segment=?',(scope,last[1])).fetchone()[0])
    changed=not last or selection!=last[2]
    segment=1 if not last else last[1]+int(changed)
    base={l['key']:l['oi'] for l in legs} if changed else json.loads(last[3])
    a,b,details=weighted_values(legs,base)
    cross_time,cross_direction=(None,0) if changed else (last[6],last[7])
    if not changed:
        previous_sign=db.execute('SELECT a,b FROM weighted_samples WHERE scope=? AND segment=? AND a!=b ORDER BY time DESC LIMIT 1',(scope,segment)).fetchone()
        before=previous_sign[0]-previous_sign[1] if previous_sign else 0;after=a-b
        if before<0<after:cross_time,cross_direction=observed,1
        elif before>0>after:cross_time,cross_direction=observed,-1
    db.execute('INSERT INTO weighted_samples VALUES (?,?,?,?,?,?,?,?,?,?)',(scope,observed,segment,atm,selection,json.dumps(base),a,b,cross_time,cross_direction));db.commit()
    baseline=db.execute('SELECT MIN(time),COUNT(*) FROM weighted_samples WHERE scope=? AND segment=?',(scope,segment)).fetchone()
    return dict(a=a,b=b,segment=segment,baseline_time=baseline[0],observations=baseline[1],cross_time=cross_time,cross_direction=cross_direction,details=details)

def ema(values,period):
    value=values[0];alpha=2/(period+1)
    for p in values[1:]:value+=alpha*(p-value)
    return value

def candle_conditions(candles,now):
    for candle in candles:
        if not isinstance(candle.get('date'),datetime) or candle['date'].tzinfo is None:
            raise HTTPException(503,'Candle timestamps must include timezone')
        if any(not isinstance(candle.get(k),(int,float)) or isinstance(candle[k],bool) or not math.isfinite(candle[k]) for k in ('high','low','close','volume')) or candle['volume']<0:
            raise HTTPException(503,'Invalid futures candle data')
    completed=[c for c in candles if c['date'].timestamp()+60<=now.timestamp()]
    completed.sort(key=lambda c:c['date'])
    today=[c for c in completed if c['date'].astimezone(shared.IST).date()==now.date()]
    if len(completed)<21 or not today:raise HTTPException(503,'Waiting for actual completed futures candles')
    last=today[-1]
    if now.timestamp()-(last['date'].timestamp()+60)>180:raise HTTPException(503,'Futures candles are stale')
    volume=sum(c.get('volume',0) for c in today)
    if volume<=0:raise HTTPException(503,'Futures VWAP volume unavailable')
    vwap=sum((c['high']+c['low']+c['close'])/3*c.get('volume',0) for c in today)/volume
    closes=[c['close'] for c in completed]
    return dict(price=last['close'],vwap=vwap,ema9=ema(closes,9),ema21=ema(closes,21),candle_time=int(last['date'].timestamp()))

def evaluate(oi,ind,pcr,now):
    direction=1 if oi['a']>oi['b'] else -1 if oi['a']<oi['b'] else 0
    cross=bool(direction and oi['cross_direction']==direction and oi['cross_time'] and 0<=now-oi['cross_time']<=300)
    price,vwap,e9,e21=(ind[k] for k in ('price','vwap','ema9','ema21'))
    checks=[dict(name='Weighted OI crossover (last 5m)',passed=cross),
        dict(name='Futures close vs session VWAP',passed=price>vwap if direction==1 else price<vwap if direction==-1 else False),
        dict(name='Futures close / EMA 9 / EMA 21',passed=price>e9>e21 if direction==1 else price<e9<e21 if direction==-1 else False),
        dict(name='Selected-range PCR',passed=pcr>1.1 if direction==1 else pcr<.9 if direction==-1 else False)]
    count=sum(c['passed'] for c in checks);score=count*25
    # A setup requires the primary crossover; other matching rules alone cannot activate it.
    color='green' if cross and count==4 else 'yellow' if cross and count>=2 else 'red'
    side='CALL' if direction==1 else 'PUT' if direction==-1 else 'NONE'
    label=f'{side} SETUP — STRONG' if color=='green' else f'{side} WATCH — MODERATE' if color=='yellow' else 'NO TRADE — WAIT'
    return dict(direction=side,conditions=checks,matched=count,score=score,color=color,label=label,probability_of_profit=None)

@router.get('/api/signals/weighted-setup')
def weighted_setup(expiry: str|None=Query(None)):
    with lock:
        key=expiry or '';previous=cache.get(key)
        if previous and time.monotonic()-previous[0]<5:return previous[1]
        try:
            now=datetime.now(shared.IST)
            chain=get_dynamic_option_chain(symbol='NIFTY',expiry=expiry,num_strikes=3)
            if chain['status']!='fresh':raise HTTPException(503,'Live chain is stale/incomplete; no active setup')
            atm,step,puts,calls=weights_for(chain['spot_price'],[r['strike'] for r in chain['strikes']])
            rows={r['strike']:r for r in chain['strikes']};legs=[];timestamps=[chain['spot_quote_at']]
            for typ,strikes,prefix in [('PE',puts,'put'),('CE',calls,'call')]:
                for strike,weight in zip(strikes,WEIGHTS):
                    r=rows[strike];oi=r[prefix+'_oi'];ts=r[prefix+'_quote_time']
                    if oi is None or ts is None:raise HTTPException(503,'Incomplete weighted OI basket')
                    legs.append(dict(key=f'{strike}:{typ}',strike=strike,type=typ,weight=weight,oi=oi));timestamps.append(ts)
            if any(not -5<=now.timestamp()-ts<=30 for ts in timestamps) or max(timestamps)-min(timestamps)>30:
                raise HTTPException(503,'Spot and selected option timestamps are stale/out of sync')
            kite=shared.kite_client()
            with shared.lock: instruments=shared.instruments(kite,now.date())
            futures=sorted([r for r in instruments if r.get('name')=='NIFTY' and r.get('instrument_type')=='FUT' and shared.expiry_date(r['expiry'])>=now.date()],key=lambda r:shared.expiry_date(r['expiry']))
            if not futures:raise HTTPException(503,'No NIFTY futures instrument for volume-based VWAP')
            future=futures[0]
            candles=kite.historical_data(future['instrument_token'],now-timedelta(days=5),now,'minute')
            ind=candle_conditions(candles,now)
            DB.parent.mkdir(parents=True,exist_ok=True)
            scope=f"weighted-v1:{now.date()}:NIFTY:{chain['selected_expiry']}:3,2,1"
            with sqlite3.connect(DB,timeout=15) as db:
                oi=record(db,scope,min(timestamps),atm,legs)
            outcome=evaluate(oi,ind,chain['pcr'],now.timestamp())
            result=dict(source='kite',status='fresh',symbol='NIFTY',expiry=chain['selected_expiry'],spot=chain['spot_price'],atm=atm,step=step,
                put_strikes=puts,call_strikes=calls,weights=list(WEIGHTS),pcr=chain['pcr'],oi=oi,indicators=ind,
                indicator_instrument=future['tradingsymbol'],quote_time=min(timestamps),fetched_at=now.isoformat(),
                **outcome,method='Setup score = matched rules / 4 × 100; not win probability. OI baseline resets whenever the ATM basket changes.')
            cache[key]=(time.monotonic(),result);return result
        except HTTPException:raise
        except Exception:raise HTTPException(503,'Weighted setup unavailable. Check Kite token, quotes/history access and backend/data permissions.') from None
