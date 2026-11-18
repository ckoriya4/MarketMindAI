"""Live market-strip snapshots; observed mini-chart values only."""
import math
import time
from collections import deque
from datetime import datetime, timezone
from threading import Lock

from fastapi import APIRouter, HTTPException
from kiteconnect.exceptions import TokenException
from .oi_signal import IST, kite_client, provider_time
from .energy_service import mcx_quote

router = APIRouter()
_lock = Lock()
_cache = None
_cache_at = 0.0
_history = {}
INDEX_KEYS = {
    'NIFTY': ('NIFTY 50 (SPOT)', 'NSE:NIFTY 50'),
    'BANKNIFTY': ('BANK NIFTY', 'NSE:NIFTY BANK'),
    'SENSEX': ('SENSEX', 'BSE:SENSEX'),
    'VIX': ('INDIA VIX', 'NSE:INDIA VIX'),
}


def finite(value):
    return isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value)


def change_values(price, previous):
    if not finite(previous) or previous <= 0:
        return None, None
    change = price-previous
    return round(change,2), round(change/previous*100,2)


def atm_strike(price, step=50):
    return int(math.floor(price/step+0.5)*step)


def observations(key, value, observed):
    day=datetime.fromtimestamp(observed,IST).date().isoformat()
    old=_history.get(key)
    if old is None or old['day'] != day:
        old={'day':day,'points':deque(maxlen=120)}
        _history[key]=old
    points=old['points']
    if not points or observed>points[-1]['time']:
        points.append({'time':observed,'value':value})
    elif observed==points[-1]['time']:
        points[-1]={'time':observed,'value':value}
    return list(points)


def index_card(code, name, quote, received):
    price=quote.get('last_price')
    if not finite(price) or price<=0:
        return {'id':code,'name':name,'status':'unavailable','price':None,'history':[],
                'error':'Instrument quote missing; check exchange market-data permissions.'}
    supplied=quote.get('timestamp')
    try:
        ts=provider_time(supplied) if supplied is not None else None
    except (ValueError, TypeError, HTTPException):
        ts=None
    observed=ts if ts is not None else received
    status='stale' if ts is not None and not -5<=received-ts<=90 else 'ok'
    change,pct=change_values(price,quote.get('ohlc',{}).get('close'))
    return {'id':code,'name':name,'price':price,'change':change,'change_pct':pct,
            'currency':None,'status':status,'source':'Kite', 'quote_time':ts,
            'received_at':received,'time_kind':'exchange' if ts is not None else 'received',
            'history':observations(code,price,observed)}


@router.get('/api/market/overview')
def market_overview():
    global _cache,_cache_at
    with _lock:
        if _cache is not None and time.monotonic()-_cache_at<5:
            return _cache
        try:
            kite=kite_client()
            raw=kite.quote([key for name,key in INDEX_KEYS.values()])
        except TokenException:
            raise HTTPException(401,'Kite session expired. Update the backend access token and restart.') from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503,'Market quotes unavailable. Check Kite connectivity and NSE/BSE quote permissions.') from None
        received=int(time.time())
        cards=[index_card(code,name,raw.get(key,{}),received) for code,(name,key) in INDEX_KEYS.items()]
        crude=mcx_quote()
        price=crude.get('price')
        if finite(price) and price>0:
            ts=crude.get('quote_time')
            status='ok' if crude.get('status')=='fresh' and ts is not None and -5<=received-ts<=90 else 'stale'
            cards.append({'id':'CRUDE','name':'CRUDE OIL (MCX)','price':price,
                'change':crude.get('change'),'change_pct':crude.get('change_pct'),
                'currency':'INR','status':status,'source':'Kite / MCX',
                'symbol':crude.get('symbol'),'expiry':crude.get('expiry'),
                'quote_time':ts,'received_at':received,'time_kind':'exchange',
                'history':observations('CRUDE:'+str(crude.get('symbol')),price,ts or received)})
        else:
            cards.append({'id':'CRUDE','name':'CRUDE OIL (MCX)','price':None,
                          'status':'unavailable','history':[], 'error':crude.get('error','MCX quote unavailable')})
        nifty=next(card for card in cards if card['id']=='NIFTY')
        spot=nifty.get('price')
        atm={'strike':atm_strike(spot) if finite(spot) and spot>0 else None,
             'spot':spot,'step':50,'spot_change_pct':nifty.get('change_pct'),
             'status':nifty['status'],'quote_time':nifty.get('quote_time')}
        _cache={'source':'kite','cards':cards,'atm':atm,
                'fetched_at':datetime.now(timezone.utc).isoformat(),
                'status':'ok' if all(c['status']=='ok' for c in cards) else 'partial'}
        _cache_at=time.monotonic()
        return _cache
