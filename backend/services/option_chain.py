
"""Actual listed option contracts and Kite quote snapshots; no simulated option values."""

import math
import time
import logging

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

from fastapi import HTTPException

from . import oi_signal as shared
from .previous_oi import previous_baselines
from .database import get_db_connection


# Legacy chart-service import compatibility only.
# This service never reads these values.
DEFAULT_SPOTS = {
    'NIFTY': 23095.30,
    'BANKNIFTY': 49112.60,
    'FINNIFTY': 21450.00
}

# Actual Kite index quote instruments.
INDEX = {
    'NIFTY': 'NSE:NIFTY 50',
    'BANKNIFTY': 'NSE:NIFTY BANK',
    'FINNIFTY': 'NSE:NIFTY FIN SERVICE',
    'MIDCPNIFTY': 'NSE:NIFTY MID SELECT',
    'NIFTYNXT50': 'NSE:NIFTY NEXT 50',
    'SENSEX': 'BSE:SENSEX',
    'BANKEX': 'BSE:BANKEX'
}

# Exchange where each symbol's listed options are traded.
OPTION_EXCHANGE = {
    'NIFTY': 'NFO',
    'BANKNIFTY': 'NFO',
    'FINNIFTY': 'NFO',
    'MIDCPNIFTY': 'NFO',
    'NIFTYNXT50': 'NFO',
    'SENSEX': 'BFO',
    'BANKEX': 'BFO'
}

IST = timezone(timedelta(hours=5, minutes=30))

_lock = Lock()
_cache = {}

# Separate daily cache for exchanges other than the shared NFO cache.
# shared.instruments() in oi_signal.py deliberately loads NFO only.
_instrument_cache = {}
_instrument_cache_lock = Lock()

DB = Path(__file__).resolve().parents[1] / 'data' / 'option-oi-baselines.sqlite3'


def numeric(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def fmt(value):
    return (
        '—'
        if value is None
        else f'{value/1e7:.2f}Cr'
        if abs(value) >= 1e7
        else f'{value/1e5:.1f}L'
    )


def expiry_label(d):
    return d.strftime('%d-%b-%Y').upper()


def parse_expiry(value, values):
    if not values:
        raise HTTPException(
            503,
            'No upcoming listed option expiries returned by Kite.'
        )

    if not value:
        return values[0]

    for d in values:
        if value.strip().upper() in (
            d.isoformat(),
            expiry_label(d)
        ):
            return d

    raise HTTPException(
        422,
        'Expiry is not listed for this underlying. Refresh the expiry selector.'
    )


def exchange_instruments(kite, exchange, today):
    """Load one exchange instrument dump per day."""

    if exchange == 'NFO':
        # Preserve the existing shared NFO instrument cache.
        with shared.lock:
            return shared.instruments(kite, today)

    with _instrument_cache_lock:
        cached = _instrument_cache.get(exchange)

        if cached and cached['date'] == today:
            return cached['rows']

        try:
            data = kite.instruments(exchange)

            if not isinstance(data, list):
                raise ValueError('Invalid instrument dump')

            _instrument_cache[exchange] = {
                'date': today,
                'rows': data
            }

            return data

        except Exception:
            logging.exception(
                'Failed to load %s instruments from Kite',
                exchange
            )
            raise HTTPException(
                503,
                f'Cannot load actual Kite {exchange} instruments.'
            ) from None


def listed(kite, symbol, now):
    if symbol not in INDEX:
        raise HTTPException(
            422,
            'Supported markets: NIFTY, BANKNIFTY, FINNIFTY, '
            'MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX.'
        )

    exchange = OPTION_EXCHANGE[symbol]
    data = exchange_instruments(kite, exchange, now.date())

    rows = [
        r for r in data
        if r.get('name') == symbol
        and r.get('instrument_type') in ('CE', 'PE')
        and r.get('expiry')
        and shared.expiry_date(r['expiry']) >= now.date()
    ]

    if not rows:
        raise HTTPException(
            503,
            f'No currently listed {exchange} CE/PE contracts '
            f'returned by Kite for {symbol}.'
        )

    return rows


def get_upcoming_expiries(symbol='NIFTY'):
    try:
        now = datetime.now(IST)
        kite = shared.kite_client()

        return [
            expiry_label(d)
            for d in sorted({
                shared.expiry_date(r['expiry'])
                for r in listed(kite, symbol.upper(), now)
            })
        ]

    except HTTPException:
        raise

    except Exception:
        logging.exception('Unable to load listed option expiries')
        raise HTTPException(
            503,
            'Cannot load actual listed expiries from Kite.'
        ) from None


def quote_time(q):
    try:
        return shared.provider_time(q.get('timestamp'))

    except (HTTPException, ValueError, TypeError):
        return None


# ---------------------------------------------------------
# POSTGRESQL OPTION CHAIN HISTORY
# ---------------------------------------------------------

def save_option_chain_history(symbol, expiry, rows, raw, baseline):
    """Save actual Kite CE/PE quote snapshots to PostgreSQL."""

    records = []
    exchange = OPTION_EXCHANGE[symbol]

    for r in rows:
        if shared.expiry_date(r['expiry']) != expiry:
            continue

        strike = float(r['strike'])
        option_type = r['instrument_type']

        if option_type not in ('CE', 'PE'):
            continue

        contract_exchange = r.get('exchange') or exchange
        key = contract_exchange + ':' + r['tradingsymbol']
        q = raw.get(key, {})

        oi = q.get('oi')
        ltp = q.get('last_price')
        volume = q.get('volume')
        ts = quote_time(q)

        # Save only records with a real provider timestamp and valid values.
        if not (
            numeric(oi)
            and oi >= 0
            and numeric(ltp)
            and ltp >= 0
            and ts is not None
        ):
            continue

        base = baseline.get(key)
        oi_change = None

        if base and numeric(base[0]):
            oi_change = int(oi) - int(base[0])

        volume = (
            int(volume)
            if numeric(volume) and volume >= 0
            else None
        )

        quote_datetime = datetime.fromtimestamp(ts, IST)

        records.append((
            symbol,
            expiry,
            strike,
            option_type,
            float(ltp),
            int(oi),
            oi_change,
            volume,
            quote_datetime
        ))

    if not records:
        return 0

    try:
        # FIX:
        # executemany() is called on cursor, not connection.
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO option_chain_history (
                        symbol,
                        expiry,
                        strike,
                        option_type,
                        ltp,
                        oi,
                        oi_change,
                        volume,
                        recorded_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """,
                    records
                )

        return len(records)

    except Exception:
        logging.exception(
            'Failed to save option chain history to PostgreSQL'
        )
        return 0


# ---------------------------------------------------------
# BUILD OPTION CHAIN
# ---------------------------------------------------------

def build_chain(
    symbol,
    expiry,
    rows,
    spot,
    raw,
    baseline,
    now,
    num_strikes
):

    exchange = OPTION_EXCHANGE[symbol]
    paired = {}

    for r in rows:
        if shared.expiry_date(r['expiry']) == expiry:
            contract_exchange = r.get('exchange') or exchange
            paired.setdefault(float(r['strike']), {})[
                r['instrument_type']
            ] = contract_exchange + ':' + r['tradingsymbol']

    ladder = sorted(
        k for k, v in paired.items()
        if 'CE' in v and 'PE' in v
    )

    if not ladder:
        raise HTTPException(
            503,
            'No paired CE/PE strikes for selected expiry.'
        )

    atm = min(
        ladder,
        key=lambda k: (abs(k - spot), -k)
    )

    idx = ladder.index(atm)

    selected = ladder[
        max(0, idx - num_strikes):
        idx + num_strikes + 1
    ]

    results = []
    times = []
    missing = []

    for strike in selected:
        item = dict(
            strike=strike,
            is_atm=strike == atm,
            is_support=False,
            is_resistance=False
        )

        for typ, prefix in [
            ('CE', 'call'),
            ('PE', 'put')
        ]:
            key = paired[strike][typ]
            q = raw.get(key, {})

            oi = q.get('oi')
            ltp = q.get('last_price')
            ts = quote_time(q)
            volume = q.get('volume')

            valid = (
                numeric(oi)
                and oi >= 0
                and numeric(ltp)
                and ltp >= 0
                and ts is not None
            )

            if ts is not None:
                times.append(ts)

            if not valid:
                missing.append(key)

            oi = int(oi) if valid else None
            base = baseline.get(key)

            change = (
                oi - base[0]
                if oi is not None and base and numeric(base[0])
                else None
            )

            pct = (
                round(change / base[0] * 100, 2)
                if change is not None
                and numeric(base[0])
                and base[0] > 0
                else None
            )

            item.update({
                prefix + '_ltp': float(ltp) if valid else None,
                prefix + '_oi': oi,
                prefix + '_oi_formatted': fmt(oi),
                prefix + '_oi_chg': change,
                prefix + '_oi_chg_formatted': fmt(change),
                prefix + '_oi_pct_chg': pct,
                prefix + '_quote_time': ts,
                prefix + '_volume': (
                    int(volume)
                    if numeric(volume) and volume >= 0
                    else None
                ),
                prefix + '_baseline_at': base[1] if base else None,
                prefix + '_oi_baseline_status': (
                    'ok' if base else 'loading / unavailable'
                )
            })

        c = item['call_oi']
        p = item['put_oi']

        item['strike_pcr'] = (
            round(p / c, 2)
            if c is not None and c > 0 and p is not None
            else None
        )

        results.append(item)

    complete = not missing

    tc = (
        sum(r['call_oi'] for r in results)
        if complete
        else None
    )

    tp = (
        sum(r['put_oi'] for r in results)
        if complete
        else None
    )

    pcr = (
        round(tp / tc, 2)
        if tc is not None and tc > 0
        else None
    )

    maxoi = max(
        [
            r[p + '_oi'] or 0
            for r in results
            for p in ('call', 'put')
        ] + [1]
    )

    for r in results:
        r['call_bar_pct'] = round(
            (r['call_oi'] or 0) / maxoi * 100,
            1
        )
        r['put_bar_pct'] = round(
            (r['put_oi'] or 0) / maxoi * 100,
            1
        )

    resistance = [
        r for r in results
        if r['strike'] >= spot
        and (r['call_oi'] or 0) > 0
    ]

    support = [
        r for r in results
        if r['strike'] <= spot
        and (r['put_oi'] or 0) > 0
    ]

    rr = (
        max(
            resistance,
            key=lambda r: (
                r['call_oi'],
                -abs(r['strike'] - spot)
            )
        )
        if complete and resistance
        else None
    )

    ss = (
        max(
            support,
            key=lambda r: (
                r['put_oi'],
                -abs(r['strike'] - spot)
            )
        )
        if complete and support
        else None
    )

    if rr:
        rr['is_resistance'] = True

    if ss:
        ss['is_support'] = True

    fresh = (
        complete
        and bool(times)
        and all(
            -5 <= now.timestamp() - t <= 90
            for t in times
        )
    )

    status = (
        'partial'
        if not complete
        else 'fresh'
        if fresh
        else 'stale'
    )

    score = (
        round(100 * tp / (tp + tc))
        if fresh and tp + tc > 0
        else None
    )

    trend = (
        'Put OI dominant'
        if score is not None and score > 50
        else 'Call OI dominant'
        if score is not None and score < 50
        else 'Balanced'
        if score is not None
        else 'Unavailable / stale'
    )

    return dict(
        symbol=symbol,
        spot_price=round(spot, 2),
        atm_strike=atm,
        selected_expiry=expiry_label(expiry),

        available_expiries=sorted(
            {
                expiry_label(shared.expiry_date(r['expiry']))
                for r in rows
            },
            key=lambda v: datetime.strptime(v, '%d-%b-%Y')
        ),

        days_to_expiry=(expiry - now.date()).days,

        total_call_oi=fmt(tc),
        total_put_oi=fmt(tp),
        pcr=pcr,

        pcr_bias=(
            'Bullish'
            if pcr is not None and pcr > 1.12
            else 'Bearish'
            if pcr is not None and pcr < 0.88
            else 'Neutral'
            if pcr is not None
            else 'Unavailable'
        ),

        resistance_strike=rr['strike'] if rr else None,
        resistance_oi=fmt(rr['call_oi'] if rr else None),
        support_strike=ss['strike'] if ss else None,
        support_oi=fmt(ss['put_oi'] if ss else None),

        ab_score=dict(
            score=score,
            trend=trend,
            recommendation='OBSERVE' if fresh else 'WAIT — DATA UNAVAILABLE',
            color='amber'
        ),

        strikes=results,
        timestamp=now.isoformat(),
        data_mode='Kite · ' + status,
        status=status,
        source='kite',

        oldest_quote_at=min(times) if times else None,
        missing_contracts=missing,

        oi_change_basis=(
            'Previous actual trading-session daily closing OI from Kite history; '
            'unavailable until verified'
        ),

        level_scope=(
            'Displayed strikes, selected expiry. '
            'R1=max CE OI at/above spot; S1=max PE OI at/below spot.'
        ),

        score_method=(
            '100 × total put OI / (total put OI + total call OI). '
            'Descriptive OI balance, not AI confidence.'
        )
    )


# ---------------------------------------------------------
# MAIN OPTION CHAIN SERVICE
# ---------------------------------------------------------

def get_dynamic_option_chain(
    symbol='NIFTY',
    expiry=None,
    num_strikes=7,
    custom_spot=None
):
    # Legacy argument intentionally ignored:
    # live ATM must use actual Kite index spot.

    symbol = symbol.strip().upper()
    num_strikes = int(num_strikes)

    if symbol not in INDEX:
        raise HTTPException(
            422,
            'Supported markets: NIFTY, BANKNIFTY, FINNIFTY, '
            'MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX.'
        )

    if not 3 <= num_strikes <= 50:
        raise HTTPException(
            422,
            'Strike range must be 3..50 per side.'
        )

    with _lock:
        now = datetime.now(IST)
        cachekey = (symbol, expiry, num_strikes)
        cached = _cache.get(cachekey)

        if cached and time.monotonic() - cached[0] < 5:
            return cached[1]

        try:
            kite = shared.kite_client()
            rows = listed(kite, symbol, now)

            exp = parse_expiry(
                expiry,
                sorted({
                    shared.expiry_date(r['expiry'])
                    for r in rows
                })
            )

            spot_key = INDEX[symbol]
            spotraw = kite.quote([spot_key]).get(spot_key, {})

            spot = spotraw.get('last_price')
            spot_ts = quote_time(spotraw)

            if (
                not numeric(spot)
                or spot <= 0
                or spot_ts is None
            ):
                raise HTTPException(
                    503,
                    f'Live {symbol} index spot/timestamp unavailable from Kite.'
                )

            ladder = sorted({
                float(r['strike'])
                for r in rows
                if shared.expiry_date(r['expiry']) == exp
            })

            if not ladder:
                raise HTTPException(
                    503,
                    'No strikes available for selected expiry.'
                )

            atm = min(
                ladder,
                key=lambda k: (abs(k - spot), -k)
            )

            i = ladder.index(atm)

            chosen = set(
                ladder[
                    max(0, i - num_strikes):
                    i + num_strikes + 1
                ]
            )

            exchange = OPTION_EXCHANGE[symbol]

            keys = [
                (r.get('exchange') or exchange) + ':' + r['tradingsymbol']
                for r in rows
                if shared.expiry_date(r['expiry']) == exp
                and float(r['strike']) in chosen
            ]

            if not keys:
                raise HTTPException(
                    503,
                    'No option contracts found for selected strikes.'
                )

            raw = kite.quote(keys)

            contracts = [
                (
                    (r.get('exchange') or exchange) + ':' + r['tradingsymbol'],
                    r['instrument_token']
                )
                for r in rows
                if shared.expiry_date(r['expiry']) == exp
                and float(r['strike']) in chosen
                and (r.get('exchange') or exchange) + ':' + r['tradingsymbol'] in keys
            ]

            baseline = previous_baselines(
                now.date().isoformat(),
                contracts
            )

            result = build_chain(
                symbol,
                exp,
                rows,
                spot,
                raw,
                baseline,
                now,
                num_strikes
            )

            saved_count = save_option_chain_history(
                symbol,
                exp,
                rows,
                raw,
                baseline
            )

            result['postgres_saved_contracts'] = saved_count
            result['oi_baselines_ready'] = len(baseline)
            result['oi_baselines_total'] = len(keys)
            result['spot_quote_at'] = spot_ts

            if not -5 <= now.timestamp() - spot_ts <= 90:
                result['status'] = 'stale'
                result['data_mode'] = 'Kite · stale index spot'

                result['ab_score'].update(
                    score=None,
                    trend='Stale spot',
                    recommendation='WAIT — DATA UNAVAILABLE'
                )

            _cache[cachekey] = (
                time.monotonic(),
                result
            )

            return result

        except HTTPException:
            raise

        except Exception:
            logging.exception(
                'Kite option chain request failed for %s',
                symbol
            )

            raise HTTPException(
                503,
                'Kite option chain unavailable. Check token, connectivity, '
                'instrument listings and market-data access.'
            ) from None
