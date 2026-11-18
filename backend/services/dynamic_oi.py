"""Directional near-ATM OI baskets, with separate delta baselines for each ATM segment."""
import json
import sqlite3
from pathlib import Path
import math
import time
from datetime import date, datetime, timezone
from fastapi import HTTPException
from kiteconnect.exceptions import TokenException
from . import oi_signal as shared
from .market_session import session_bounds

_cache={}


def strike_selection(spot, listed, side_count=4, itm_count=0):
    if side_count not in (3,4) or itm_count not in (0,1):
        raise HTTPException(422,'Choose 3 or 4 strikes per side, and 0 or 1 extra ITM strike.')
    if not math.isfinite(spot) or spot<=0:
        raise HTTPException(503,'A valid underlying spot quote is required.')
    available=sorted({int(s) for s in listed})
    if len(available)<3:
        raise HTTPException(503,'Not enough listed strikes to determine the strike interval.')
    near=sorted(sorted(available,key=lambda s:abs(s-spot))[:12])
    gaps=[b-a for a,b in zip(near,near[1:]) if b>a]
    step=min(gaps)
    # Nearest actually listed strike; midpoint ties choose the higher strike.
    anchor=min(available,key=lambda s:(abs(s-spot),-s))
    side_count=3;itm_count=0
    puts=[anchor-i*step for i in range(3)]
    calls=[anchor+i*step for i in range(3)]
    if itm_count:
        puts=[anchor+step]+puts
        calls=[anchor-step]+calls
    if not set(puts+calls).issubset(available):
        raise HTTPException(503,'The requested near-ATM strikes are not all listed for this expiry.')
    return {'anchor':anchor,'step':step,'put_strikes':puts,'call_strikes':calls,'weights':[1,1,1],'aggregation':'plain-sum'}


def plain_total(selection, side, values):
    strikes=selection['put_strikes'] if side=='PE' else selection['call_strikes']
    return sum(values[(strike,side)] for strike in strikes)


def prepare_db():
    path=Path(__file__).resolve().parents[1]/'data'/'direct-sum-oi-graph.sqlite3'
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=15)
    db.execute('''CREATE TABLE IF NOT EXISTS dynamic_oi_samples (
        scope TEXT, time INTEGER, segment INTEGER, atm INTEGER, step INTEGER,
        put_oi INTEGER, call_oi INTEGER, put_change INTEGER, call_change INTEGER,
        selection TEXT, PRIMARY KEY(scope,time))''')
    db.execute('CREATE TABLE IF NOT EXISTS dynamic_oi_origins (scope TEXT, time INTEGER, source TEXT, spot REAL, PRIMARY KEY(scope,time))')
    return db


def record_sample(db, scope, observed, selection, put_oi, call_oi):
    encoded=json.dumps(selection,sort_keys=True)
    last=db.execute('SELECT time,segment,selection FROM dynamic_oi_samples WHERE scope=? ORDER BY time DESC LIMIT 1',(scope,)).fetchone()
    if last and observed<=last[0]:
        if encoded!=last[2]:
            raise HTTPException(503,'ATM changed; waiting for the next complete provider timestamp before starting the new basket.')
        return
    changed=last is None or encoded!=last[2]
    segment=1 if last is None else last[1]+1 if changed else last[1]
    if changed:
        put_base,call_base=put_oi,call_oi
    else:
        baseline=db.execute('SELECT put_oi,call_oi FROM dynamic_oi_samples WHERE scope=? AND segment=? ORDER BY time LIMIT 1',(scope,segment)).fetchone()
        put_base,call_base=baseline
    db.execute('INSERT INTO dynamic_oi_samples VALUES (?,?,?,?,?,?,?,?,?,?)',
               (scope,observed,segment,selection['anchor'],selection['step'],put_oi,call_oi,
                put_oi-put_base,call_oi-call_base,encoded))
    db.commit()


def dynamic_oi_signals(symbol='NIFTY', expiry=None, side_count=4, itm_count=0, record_only=False):
    side_count=3;itm_count=0
    with shared.lock:
        today=datetime.now(shared.IST).date()
        key=(symbol,expiry or '',side_count,itm_count,today.isoformat())
        cached=_cache.get(key)
        if not record_only and cached and time.monotonic()-cached[0]<3:return cached[1]
        db=None
        try:
            kite=shared.kite_client()
            options=[i for i in shared.instruments(kite,today) if i.get('name')==symbol
                     and i.get('instrument_type') in ('CE','PE') and shared.expiry_date(i['expiry'])>=today]
            expiries=sorted({shared.expiry_date(i['expiry']) for i in options})
            if not expiries:raise HTTPException(503,'No current option expiries are available.')
            try:selected=date.fromisoformat(expiry) if expiry else expiries[0]
            except ValueError:
                try:selected=datetime.strptime(expiry,'%d-%b-%Y').date()
                except (ValueError,TypeError):raise HTTPException(422,'Invalid expiry date.') from None
            if selected not in expiries:raise HTTPException(422,'Select an expiry currently listed in Kite.')
            underlying=shared.INDEX[symbol][0]
            spot=kite.quote([underlying]).get(underlying,{}).get('last_price')
            if not isinstance(spot,(int,float)) or isinstance(spot,bool) or not math.isfinite(spot):
                raise HTTPException(503,'Underlying spot quote is unavailable.')
            expiry_options=[i for i in options if shared.expiry_date(i['expiry'])==selected]
            selection=strike_selection(spot,[i['strike'] for i in expiry_options],side_count,itm_count)
            wanted={(s,'PE') for s in selection['put_strikes']} | {(s,'CE') for s in selection['call_strikes']}
            contracts=[i for i in expiry_options if (int(i['strike']),i['instrument_type']) in wanted]
            if len(contracts)!=len(wanted) or {(int(i['strike']),i['instrument_type']) for i in contracts}!=wanted:
                raise HTTPException(503,'A selected PE/CE contract is missing. No partial OI sum was used.')
            raw=kite.quote([f"NFO:{i['tradingsymbol']}" for i in contracts])
            totals={'PE':0,'CE':0};timestamps=[]
            for contract in contracts:
                q=raw.get(f"NFO:{contract['tradingsymbol']}",{})
                oi=q.get('oi')
                if not isinstance(oi,(int,float)) or isinstance(oi,bool) or not math.isfinite(oi) or oi<0:
                    raise HTTPException(503,'A selected option OI quote is missing or invalid.')
                ts=shared.provider_time(q.get('timestamp'))
                if datetime.fromtimestamp(ts,shared.IST).date()!=today:
                    raise HTTPException(503,'Waiting for current-day option quotes.')
                totals[contract['instrument_type']]+=int(oi);timestamps.append(ts)
            now=time.time()
            if max(timestamps)>now+5:raise HTTPException(503,'Provider timestamps are ahead of backend time.')
            if max(timestamps)-min(timestamps)>30 or now-min(timestamps)>30:
                raise HTTPException(503,'Selected option quotes are stale/out of sync; waiting for a complete fresh basket.')
            bounds=session_bounds(today,derivatives=True)
            observed=min(timestamps)
            if not bounds['open']<=observed<=bounds['close']:
                raise HTTPException(503,'Waiting for regular-session option quotes.')
            scope=f'directsum-v3:{today}:{symbol}:{selected}:{side_count}:{itm_count}'
            db=prepare_db()
            record_sample(db,scope,observed,selection,totals['PE'],totals['CE'])
            db.execute('INSERT OR IGNORE INTO dynamic_oi_origins VALUES (?,?,?,?)',(scope,observed,'live',spot))
            db.commit()
            if record_only:
                return {'scope':scope,'expiry':selected.isoformat(),'quote_time':observed}
            rows=db.execute('SELECT time,segment,atm,step,put_oi,call_oi,put_change,call_change,selection FROM dynamic_oi_samples WHERE scope=? ORDER BY time',(scope,)).fetchall()
            points=[{'time':r[0],'segment':r[1],'atm':r[2],'step':r[3],'put_oi':r[4],
                     'call_oi':r[5],'put_change':r[6],'call_change':r[7]} for r in rows]
            latest=points[-1]
            current=[p for p in points if p['segment']==latest['segment']]
            result={'source':'kite','status':'fresh','selection_mode':'dynamic-direct-sum',
                'scope':scope,'symbol':symbol,'expiry':selected.isoformat(),'spot':spot,
                **selection,'strikes':sorted(set(selection['put_strikes']+selection['call_strikes'])),
                'contract_count':len(contracts),'side_strikes':side_count,'itm_strikes':itm_count,
                'points':points,'latest':latest,'baseline_time':current[0]['time'],
                'segment':latest['segment'],'segment_points':len(current),'observations':len(points),
                'session':bounds,'quote_time':latest['time'],'age_seconds':max(0,int(now-latest['time'])),
                'change_definition':'OI minus first accepted OI in the same ATM basket segment',
                'fetched_at':datetime.now(timezone.utc).isoformat()}
            _cache[key]=(time.monotonic(),result)
            return result
        except TokenException:
            raise HTTPException(401,'Kite access token expired. Update backend/.env and restart.') from None
        except HTTPException:raise
        except Exception:
            raise HTTPException(503,'Dynamic OI unavailable. Check Kite permissions/connectivity and backend/data access.') from None
        finally:
            if db is not None:db.close()
