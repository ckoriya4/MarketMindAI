"""Regular session bounds in IST; configurable for exchange/special-session changes."""
import os
from datetime import datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def session_bounds(day, derivatives=False):
    opened = os.getenv('MARKET_OPEN_IST', '09:15')
    closed = os.getenv('FNO_CLOSE_IST', '15:40') if derivatives else os.getenv('SPOT_CLOSE_IST', '15:30')
    start = datetime.combine(day, time.fromisoformat(opened), tzinfo=IST)
    end = datetime.combine(day, time.fromisoformat(closed), tzinfo=IST)
    if end <= start:
        raise ValueError('Market close must be after market open')
    return {'date':day.isoformat(), 'open':int(start.timestamp()), 'close':int(end.timestamp()),
            'label':f'{opened}–{closed} IST', 'timezone':'Asia/Kolkata'}


def intraday_session(full, count=60, enabled=False):
    """Select all real bars in the most recent available regular trading session."""
    result = dict(full)
    if enabled and full['timeframe'] not in ('1D', 'W'):
        days = sorted({datetime.fromtimestamp(c['time'],IST).date() for c in full['candles']}, reverse=True)
        for day in days:
            bounds = session_bounds(day,derivatives=full.get('symbol')=='NIFTY_FUT')
            selected = [c for c in full['candles'] if bounds['open'] <= c['time'] < bounds['close']]
            if selected:
                times = {c['time'] for c in selected}
                for field in [k for k,v in full.items() if isinstance(v,list) and (not v or isinstance(v[0],dict) and 'time' in v[0])]:
                    result[field] = [c for c in full[field] if c['time'] in times]
                result['session'] = bounds
                return result
        raise ValueError('No regular-session candles available')
    for field in [k for k,v in full.items() if isinstance(v,list) and (not v or isinstance(v[0],dict) and 'time' in v[0])]:
        result[field] = full[field][-count:]
    result['session'] = None
    return result
