"""Kite OI snapshots with a fixed strike universe and persistent, observed history."""
import json
import os
import sqlite3
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException
from .market_session import session_bounds

BASE = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30))
DB = BASE / 'data' / 'oi-signals.sqlite3'
router = APIRouter()
lock = Lock()
_instruments = []
_instrument_day = None
_cache = {}
INDEX = {'NIFTY': ('NSE:NIFTY 50', 50), 'BANKNIFTY': ('NSE:NIFTY BANK', 100)}


def kite_client():
    load_dotenv(BASE / '.env', override=True)
    key = os.getenv('KITE_API_KEY', '').strip()
    token = os.getenv('KITE_ACCESS_TOKEN', '').strip()
    if not key or not token:
        raise HTTPException(503, 'Set KITE_API_KEY and KITE_ACCESS_TOKEN in backend/.env.')
    kite = KiteConnect(api_key=key, timeout=12)
    kite.set_access_token(token)
    return kite


def connection():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute('CREATE TABLE IF NOT EXISTS scopes (id TEXT PRIMARY KEY, config TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS samples (scope TEXT, time INTEGER, put_oi INTEGER, call_oi INTEGER, PRIMARY KEY(scope,time))')
    return db


def provider_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise HTTPException(503, 'Kite did not supply an option quote timestamp.')
    if value.tzinfo is None:
        value = value.replace(tzinfo=IST)
    return int(value.timestamp())


def instruments(kite, today):
    global _instruments, _instrument_day
    if _instrument_day != today:
        _instruments = kite.instruments('NFO')
        _instrument_day = today
    return _instruments


def expiry_date(value):
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else date.fromisoformat(str(value))


@router.get('/api/signals/oi')
def oi_signals(
    symbol: str = Query('NIFTY', pattern='^(NIFTY|BANKNIFTY)$'),
    expiry: str | None = Query(None),
    num_strikes: int = Query(7, ge=3, le=50),
    side_strikes: int = Query(4, ge=3, le=4),
    itm_strikes: int = Query(0, ge=0, le=1),
):
    # num_strikes is retained for old clients; the graph uses its own 3/4-per-side rule.
    from .session_recorder import recorder
    return recorder.read(symbol, expiry, side_strikes, itm_strikes)


def live_expiries():
    """Actual first four NIFTY expiries for the existing selector's four presets."""
    with lock:
        try:
            today = datetime.now(IST).date()
            kite = kite_client()
            values = sorted({expiry_date(i['expiry']) for i in instruments(kite, today)
                             if i.get('name') == 'NIFTY' and i.get('instrument_type') in ('CE', 'PE')
                             and expiry_date(i['expiry']) >= today})
            if not values:
                raise HTTPException(503, 'No current NIFTY option expiries found in Kite.')
            return [d.strftime('%d-%b-%Y').upper() for d in values[:4]]
        except HTTPException:
            raise
        except TokenException:
            raise HTTPException(401, 'Kite session expired.') from None
        except Exception:
            raise HTTPException(503, 'Cannot load option expiries from Kite.') from None


@router.get('/api/signals/collector/status')
def collector_status():
    from .session_recorder import recorder
    return recorder.status()
