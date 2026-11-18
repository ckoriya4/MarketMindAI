"""Live, rule-based panel values. Does not use the simulated option-chain service."""
import math
import time
from datetime import date, datetime, timezone
from threading import Lock

from fastapi import APIRouter, HTTPException, Query
from kiteconnect.exceptions import TokenException
from . import oi_signal
from .chart_service import get_chart_data

router = APIRouter()
_lock = Lock()
_cache = {}


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def selected_expiry(value, available):
    if not value:
        return available[0]
    try:
        result = date.fromisoformat(value)
    except ValueError:
        try:
            result = datetime.strptime(value, '%d-%b-%Y').date()
        except ValueError:
            raise HTTPException(422, 'Invalid expiry. Use YYYY-MM-DD or DD-Mon-YYYY.') from None
    if result not in available:
        raise HTTPException(422, 'Select an expiry currently available in Kite.')
    return result


def calculate_panel(spot, rows, indicators, completed, quote_time, expiry, strikes, now):
    """Pure calculations from a complete snapshot. Score is a documented heuristic."""
    calls = sum(row['oi'] for row in rows if row['type'] == 'CE')
    puts = sum(row['oi'] for row in rows if row['type'] == 'PE')
    if calls <= 0 or puts <= 0:
        raise HTTPException(503, 'Both call and put OI totals must be positive for confluence.')
    pcr = puts / calls
    support_rows = [r for r in rows if r['type'] == 'PE' and r['strike'] <= spot and r['oi'] > 0]
    resistance_rows = [r for r in rows if r['type'] == 'CE' and r['strike'] >= spot and r['oi'] > 0]
    if not support_rows or not resistance_rows:
        raise HTTPException(503, 'No valid support/resistance candidates in the selected strike range.')
    support = max(support_rows, key=lambda r: (r['oi'], -abs(spot-r['strike'])))['strike']
    resistance = max(resistance_rows, key=lambda r: (r['oi'], -abs(spot-r['strike'])))['strike']
    ema9, ema21 = indicators.get('ema9'), indicators.get('ema21')
    if not numeric(ema9) or not numeric(ema21):
        raise HTTPException(503, 'Kite candle indicators are unavailable.')
    ema_direction = 1 if spot > ema9 > ema21 else -1 if spot < ema9 < ema21 else 0
    action_direction = 1 if spot > completed['high'] else -1 if spot < completed['low'] else 0
    action = 'Above prior 5m high' if action_direction > 0 else 'Below prior 5m low' if action_direction < 0 else 'Inside prior 5m range'
    oi_direction = 1 if pcr > 1.1 else -1 if pcr < 0.9 else 0
    # Score = 50 + PCR(+-15) + EMA(+-15) + price breakout(+-10) + range position(+-10).
    range_position = max(-1, min(1, 2*(spot-support)/(resistance-support)-1)) if resistance > support else 0
    score = round(50 + 15*oi_direction + 15*ema_direction + 10*action_direction + 10*range_position)
    score = max(0, min(100, score))
    trend = 'Bullish' if score >= 65 else 'Bearish' if score <= 35 else 'Neutral / Rangebound'
    recommendation = 'BULLISH CONFLUENCE' if score >= 65 else 'BEARISH CONFLUENCE' if score <= 35 else 'WAIT (NO TRADE)'
    age = max(0, int(now-quote_time))
    fresh = age <= 30
    return {
        'source': 'kite', 'status': 'fresh' if fresh else 'stale', 'quote_time': quote_time,
        'fetched_at': datetime.now(timezone.utc).isoformat(), 'expiry': expiry,
        'strike_min': min(strikes), 'strike_max': max(strikes), 'contract_count': len(rows),
        'spot': spot, 'pcr': round(pcr, 3), 'total_call_oi': calls, 'total_put_oi': puts,
        'pcr_bias': 'Bullish' if oi_direction > 0 else 'Bearish' if oi_direction < 0 else 'Neutral',
        'support': support, 'resistance': resistance, 'score': score if fresh else None,
        'trend': trend if fresh else 'Unavailable',
        'recommendation': recommendation if fresh else 'WAIT — DATA STALE',
        'price_action': action if fresh else 'Data stale',
        'price_action_direction': action_direction if fresh else 0,
        'ema_direction': ema_direction, 'candle_time': completed['time'],
        'method': 'Rule-based PCR/EMA/price/range score; not an ML prediction',
    }


def freshness_details(result, timestamps, candle, now):
    """Expose measurement freshness; stale measurements never produce an active score."""
    ages=[max(0,int(now-ts)) for ts in timestamps]
    skew=max(timestamps)-min(timestamps)
    candle_age=max(0,int(now-(candle['time']+300)))
    stale_count=sum(age>30 for age in ages)
    reasons=[]
    if skew>30:reasons.append(f'Quote timestamp spread {skew}s')
    if stale_count:reasons.append(f'{stale_count}/{len(ages)} quotes older than 30s')
    if candle_age>600:reasons.append(f'Completed candle is {candle_age}s old')
    result=dict(result, quote_skew_seconds=skew, oldest_quote=min(timestamps),
                newest_quote=max(timestamps), stale_quote_count=stale_count,
                quote_count=len(timestamps), candle_age_seconds=candle_age,
                warning='; '.join(reasons))
    if reasons:
        result.update(status='stale',score=None,trend='Stale data',
                      recommendation='WAIT — DATA STALE',price_action='Data stale',price_action_direction=0)
    return result


@router.get('/api/signals/confluence')
def confluence(expiry: str | None = Query(None), num_strikes: int = Query(7, ge=3, le=50)):
    with _lock:
        today = datetime.now(oi_signal.IST).date()
        cache_key = (today.isoformat(), expiry or '', num_strikes)
        cached = _cache.get(cache_key)
        if cached and time.monotonic()-cached[0] < 10:
            return cached[1]
        try:
            # Share instrument cache/lock with the OI plot; do not hold it while loading candles.
            with oi_signal.lock:
                kite = oi_signal.kite_client()
                options = [i for i in oi_signal.instruments(kite, today)
                           if i.get('name') == 'NIFTY' and i.get('instrument_type') in ('CE', 'PE')
                           and oi_signal.expiry_date(i['expiry']) >= today]
                available = sorted({oi_signal.expiry_date(i['expiry']) for i in options})
                if not available:
                    raise HTTPException(503, 'No unexpired NIFTY option instruments available.')
                selected = selected_expiry(expiry, available)
                spot_quote = kite.quote(['NSE:NIFTY 50']).get('NSE:NIFTY 50', {})
                spot = spot_quote.get('last_price')
                if not numeric(spot) or spot <= 0:
                    raise HTTPException(503, 'NIFTY spot quote is unavailable.')
                anchor = int((spot+25)//50*50)
                strikes = [anchor+i*50 for i in range(-num_strikes, num_strikes+1)]
                contracts = [i for i in options if oi_signal.expiry_date(i['expiry']) == selected and float(i['strike']) in strikes]
                expected = {(s,t) for s in strikes for t in ('CE','PE')}
                if len(contracts) != len(expected) or {(int(i['strike']),i['instrument_type']) for i in contracts} != expected:
                    raise HTTPException(503, 'Missing option contracts in the selected expiry/strike range.')
                raw = kite.quote([f"NFO:{i['tradingsymbol']}" for i in contracts])
                rows, timestamps = [], []
                # Index packets may omit timestamp; option quote timestamps always define panel freshness.
                if spot_quote.get('timestamp') is not None:
                    timestamps.append(oi_signal.provider_time(spot_quote['timestamp']))
                for contract in contracts:
                    q = raw.get(f"NFO:{contract['tradingsymbol']}", {})
                    oi = q.get('oi')
                    if not numeric(oi) or oi < 0:
                        raise HTTPException(503, 'Incomplete live option OI snapshot. No sample totals substituted.')
                    timestamps.append(oi_signal.provider_time(q.get('timestamp')))
                    rows.append({'strike': int(contract['strike']), 'type': contract['instrument_type'], 'oi': oi})
                quote_dates = {datetime.fromtimestamp(ts,oi_signal.IST).date() for ts in timestamps}
                if len(quote_dates) != 1:
                    raise HTTPException(503, 'Quotes span different trading dates. Waiting for a complete snapshot.')
                quote_day = next(iter(quote_dates))
                if max(timestamps) > time.time()+5:
                    raise HTTPException(503, 'Provider timestamps are ahead of server time. Check the backend clock.')
                # Different update times do not imply missing data. Keep measurements, but gate signals below.
            chart = get_chart_data(symbol='NIFTY', timeframe='5m', count=65)
            if chart.get('source') != 'kite':
                raise HTTPException(503, 'Real Kite candles are required. Install the supplied live candle service.')
            now = time.time()
            completed = [c for c in chart.get('candles', []) if c['time']+300 <= now
                         and datetime.fromtimestamp(c['time'],oi_signal.IST).date() == quote_day]
            if not completed:
                raise HTTPException(503, 'No completed 5-minute candles match the quote trading date.')
            result = calculate_panel(spot, rows, chart.get('indicators',{}), completed[-1],
                                     min(timestamps), selected.isoformat(), strikes, now)
            result = freshness_details(result, timestamps, completed[-1], now)
            _cache[cache_key] = (time.monotonic(), result)
            return result
        except TokenException:
            raise HTTPException(401, 'Kite access token expired. Update backend/.env and restart.') from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, 'Live confluence unavailable. Check Kite quote/historical permissions and connectivity.') from None
