
"""Kite historical candles only. Never substitutes generated prices."""

import time
import math

from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import HTTPException
from kiteconnect.exceptions import TokenException

from .oi_signal import kite_client
from . import oi_signal as shared
from .chart_indicators import enrich
from .market_session import intraday_session


IST = timezone(timedelta(hours=5, minutes=30))

INTERVALS = {
    '1m': 'minute',
    '3m': '3minute',
    '5m': '5minute',
    '15m': '15minute',
    '30m': '30minute',
    '1H': '60minute',
    '1D': 'day',
    'W': 'day'
}

_cache = {}
_history_cache = {}
_lock = Lock()


def calculate_ema(prices, period):
    values = [prices[0]]

    for p in prices[1:]:
        values.append(
            values[-1] + (p - values[-1]) * 2 / (period + 1)
        )

    return values


def calculate_rsi(prices, period=14):
    if len(prices) <= period:
        return None

    differences = [
        b - a
        for a, b in zip(prices, prices[1:])
    ]

    gain = sum(
        max(d, 0)
        for d in differences[:period]
    ) / period

    loss = sum(
        max(-d, 0)
        for d in differences[:period]
    ) / period

    for d in differences[period:]:
        gain = (
            gain * (period - 1) + max(d, 0)
        ) / period

        loss = (
            loss * (period - 1) + max(-d, 0)
        ) / period

    if gain == loss == 0:
        return 50.0

    return (
        round(100 - 100 / (1 + gain / loss), 2)
        if loss
        else 100.0
    )


def weekly(candles):
    groups = {}

    for c in candles:
        dt = datetime.fromtimestamp(c['time'], IST)

        monday = (
            dt - timedelta(days=dt.weekday())
        ).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        bucket = int(monday.timestamp())

        if bucket not in groups:
            groups[bucket] = dict(c, time=bucket)

        else:
            w = groups[bucket]

            w.update(
                high=max(w['high'], c['high']),
                low=min(w['low'], c['low']),
                close=c['close'],
                volume=w['volume'] + c['volume']
            )

    return list(groups.values())


def normalize_records(records):
    by_time = {}

    for r in records:
        dt = r.get('date')

        if not isinstance(dt, datetime):
            raise HTTPException(
                503,
                'Kite candle timestamp invalid'
            )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)

        values = {
            k: r.get(k)
            for k in ('open', 'high', 'low', 'close')
        }

        if any(
            not isinstance(v, (int, float))
            or isinstance(v, bool)
            or not math.isfinite(v)
            or v <= 0
            for v in values.values()
        ):
            raise HTTPException(
                503,
                'Kite returned invalid OHLC; no replacement price used'
            )

        if (
            values['high'] < max(
                values['open'],
                values['close'],
                values['low']
            )
            or values['low'] > min(
                values['open'],
                values['close']
            )
        ):
            raise HTTPException(
                503,
                'Inconsistent provider OHLC'
            )

        volume = r.get('volume', 0)

        if (
            not isinstance(volume, (int, float))
            or isinstance(volume, bool)
            or not math.isfinite(volume)
            or volume < 0
        ):
            raise HTTPException(
                503,
                'Invalid provider volume'
            )

        by_time[int(dt.timestamp())] = dict(
            values,
            time=int(dt.timestamp()),
            volume=volume
        )

    return [
        by_time[t]
        for t in sorted(by_time)
    ]


def quote_metadata(quote, candles, now, timeframe):
    raw = quote.get('timestamp')
    ts = None

    if raw is not None:
        try:
            ts = shared.provider_time(raw)
        except Exception:
            pass

    age = now.timestamp() - ts if ts is not None else None

    status = (
        'fresh'
        if age is not None and -5 <= age <= 90
        else 'unverified'
        if ts is None
        else 'stale'
    )

    last = candles[-1]['time']

    step = {
        '1m': 60,
        '3m': 180,
        '5m': 300,
        '15m': 900,
        '30m': 1800,
        '1H': 3600,
        '1D': 86400,
        'W': 604800
    }[timeframe]

    candle_recent = (
        0 <= now.timestamp() - last <= step + 120
    )

    return dict(
        quote_time=ts,
        quote_age_seconds=(
            max(0, int(age))
            if age is not None
            else None
        ),
        quote_status=status,
        status=(
            'fresh'
            if status == 'fresh' and candle_recent
            else 'stale'
        ),
        last_candle_time=last,
        last_candle_closed=(
            now.timestamp() >= last + step
        ),
        historical_candle_age_seconds=max(
            0,
            int(now.timestamp() - last)
        ),
        refresh_seconds=5,
        transport='Kite REST snapshots (5s polling), not WebSocket ticks',
        indicator_source=(
            'Calculated from actual Kite historical OHLCV; '
            'not fetched as Kite chart studies'
        )
    )


def get_chart_data(
    symbol='NIFTY',
    timeframe='5m',
    count=60,
    session=False
):
    if (
        symbol not in ('NIFTY', 'NIFTY_FUT')
        or timeframe not in INTERVALS
    ):
        raise HTTPException(
            422,
            'Supported symbols NIFTY/NIFTY_FUT and displayed timeframes only'
        )

    with _lock:
        key = (symbol, timeframe)
        cached = _cache.get(key)

        if cached and time.monotonic() - cached[0] < 5:
            full = cached[1]

        else:
            try:
                kite = kite_client()
                now = datetime.now(IST)

                token = 256265
                quote_key = 'NSE:NIFTY 50'
                instrument = 'NIFTY 50 · NSE spot'

                if symbol == 'NIFTY_FUT':
                    with shared.lock:
                        futures = sorted(
                            [
                                r
                                for r in shared.instruments(
                                    kite,
                                    now.date()
                                )
                                if (
                                    r.get('name') == 'NIFTY'
                                    and r.get('instrument_type') == 'FUT'
                                    and shared.expiry_date(
                                        r['expiry']
                                    ) >= now.date()
                                )
                            ],
                            key=lambda r: shared.expiry_date(
                                r['expiry']
                            )
                        )

                    if not futures:
                        raise HTTPException(
                            503,
                            'No listed NIFTY futures contract'
                        )

                    token = futures[0]['instrument_token']

                    quote_key = (
                        'NFO:' + futures[0]['tradingsymbol']
                    )

                    instrument = (
                        futures[0]['tradingsymbol']
                        + ' · NFO futures'
                    )

                days = (
                    1900
                    if timeframe == 'W'
                    else 400
                    if timeframe == '1D'
                    else 55
                )

                history_key = (token, timeframe)
                previous = _history_cache.get(history_key)

                full_reload = (
                    previous is None
                    or time.monotonic() - previous['loaded'] >= 1800
                )

                if full_reload:
                    start = now - timedelta(days=days)
                    existing = {}
                    loaded = time.monotonic()

                else:
                    step = (
                        86400
                        if timeframe in ('1D', 'W')
                        else {
                            '1m': 60,
                            '3m': 180,
                            '5m': 300,
                            '15m': 900,
                            '30m': 1800,
                            '1H': 3600
                        }[timeframe]
                    )

                    start = datetime.fromtimestamp(
                        previous['candles'][-1]['time'] - 2 * step,
                        IST
                    )

                    existing = {
                        c['time']: c
                        for c in previous['candles']
                    }

                    loaded = previous['loaded']

                records = []

                while start < now:
                    end = min(
                        now,
                        start + timedelta(
                            days=900
                            if timeframe in ('1D', 'W')
                            else 55
                        )
                    )

                    records.extend(
                        kite.historical_data(
                            token,
                            start,
                            end,
                            INTERVALS[timeframe]
                        )
                    )

                    start = end

                incoming = normalize_records(records)

                if not incoming:
                    raise HTTPException(
                        503,
                        'No current historical candles returned; keeping chart explicitly stale'
                    )

                existing.update({
                    c['time']: c
                    for c in incoming
                })

                raw = [
                    existing[t]
                    for t in sorted(existing)
                    if t <= now.timestamp()
                ]

                if not raw:
                    raise HTTPException(
                        503,
                        'No valid actual candles'
                    )

                _history_cache[history_key] = dict(
                    candles=raw,
                    loaded=loaded
                )

                candles = (
                    weekly(raw)
                    if timeframe == 'W'
                    else raw
                )

                quote = kite.quote(
                    [quote_key]
                ).get(quote_key, {})

                ltp = quote.get('last_price')
                close = quote.get('ohlc', {}).get('close')

                if (
                    not isinstance(ltp, (int, float))
                    or isinstance(ltp, bool)
                    or not math.isfinite(ltp)
                    or ltp <= 0
                ):
                    raise HTTPException(
                        503,
                        'Actual Kite LTP unavailable; no candle-close substitution'
                    )

                valid_close = (
                    isinstance(close, (int, float))
                    and not isinstance(close, bool)
                    and math.isfinite(close)
                    and close > 0
                )

                change = (
                    ltp - close
                    if valid_close
                    else None
                )

                full = dict(
                    symbol=symbol,
                    timeframe=timeframe,
                    source='kite',
                    data_mode=(
                        'Actual Kite historical OHLCV + separate Kite LTP'
                    ),
                    instrument=instrument,
                    instrument_token=token,
                    quote_key=quote_key,
                    candles=candles,
                    indicators=dict(
                        ltp=ltp,
                        change=(
                            round(change, 2)
                            if change is not None
                            else None
                        ),
                        change_pct=(
                            round(change / close * 100, 2)
                            if change is not None
                            else None
                        )
                    ),
                    fetched_at=datetime.now(IST).isoformat()
                )

                # Calculate all indicators, including MA8 and WMA8.
                full = enrich(
                    full,
                    volume_supported=symbol == 'NIFTY_FUT'
                )

                full.update(
                    quote_metadata(
                        quote,
                        candles,
                        datetime.now(IST),
                        timeframe
                    )
                )

                # Latest candle and latest indicator values.
                full['latest_tick'] = dict(
                    candles[-1],
                    ema9=full['indicators']['ema9'],
                    ema21=full['indicators']['ema21'],
                    ma8=full['indicators']['ma8'],
                    wma8=full['indicators']['wma8'],
                    ma_wma_signal=full['indicators']['ma_wma_signal']
                )

                full['warmup_bars'] = len(candles)

                full['comparison_note'] = (
                    'Compare the identical spot/futures contract, '
                    'timeframe, regular candles and indicator settings. '
                    'Seeding/warm-up, forming candles and data delivery '
                    'can differ from Kite UI.'
                )

                _cache[key] = (
                    time.monotonic(),
                    full
                )

            except TokenException:
                raise HTTPException(
                    401,
                    'Kite session expired. Update token and restart.'
                ) from None

            except HTTPException:
                raise

            except Exception:
                raise HTTPException(
                    503,
                    'Actual Kite chart data unavailable; verify token, historical-data access and network.'
                ) from None

        return intraday_session(
            full,
            count=count,
            enabled=session
        )
