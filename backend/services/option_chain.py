
"""Actual listed option contracts and Kite quote snapshots; no simulated option values."""

import math
import sqlite3
import time
import logging

from datetime import datetime, date, timezone, timedelta
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

INDEX = {
    'NIFTY': 'NSE:NIFTY 50',
    'BANKNIFTY': 'NSE:NIFTY BANK',
    'FINNIFTY': 'NSE:NIFTY FIN SERVICE'
}

IST = timezone(timedelta(hours=5, minutes=30))

_lock = Lock()
_cache = {}

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


def listed(kite, symbol, now):
    if symbol not in INDEX:
        raise HTTPException(
            422,
            'Supported underlyings: NIFTY, BANKNIFTY, FINNIFTY.'
        )

    # Reuse the same daily instrument dump as the OI recorder.
    with shared.lock:
        data = shared.instruments(kite, now.date())

    rows = [
        r for r in data
        if r.get('name') == symbol
        and r.get('instrument_type') in ('CE', 'PE')
        and shared.expiry_date(r['expiry']) >= now.date()
    ]

    if not rows:
        raise HTTPException(
            503,
            'No currently listed options returned by Kite.'
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
                for r in listed(kite, symbol, now)
            })
        ]

    except HTTPException:
        raise

    except Exception:
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
    """
    Save actual Kite CE/PE quote snapshots to PostgreSQL.

    Saves:
    - Symbol
    - Expiry
    - Strike
    - CE / PE
    - LTP
    - OI
    - OI change
    - Volume
    - Actual quote timestamp

    Missing values are not generated.
    """

    records = []

    for r in rows:

        if shared.expiry_date(r['expiry']) != expiry:
            continue

        strike = float(r['strike'])
        option_type = r['instrument_type']

        if option_type not in ('CE', 'PE'):
            continue

        key = 'NFO:' + r['tradingsymbol']
        q = raw.get(key, {})

        oi = q.get('oi')
        ltp = q.get('last_price')
        volume = q.get('volume')
        ts = quote_time(q)

        # Save only valid actual Kite quotes.
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
        with get_db_connection() as conn:

            conn.executemany(
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

    paired = {}

    for r in rows:

        if shared.expiry_date(r['expiry']) == expiry:

            paired.setdefault(
                float(r['strike']), {}
            )[r['instrument_type']] = (
                'NFO:' + r['tradingsymbol']
            )

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
                if oi is not None and base
                else None
            )

            pct = (
                round(change / base[0] * 100, 2)
                if change is not None and base[0] > 0
                else None
            )

            item.update({
                prefix + '_ltp':
                    float(ltp) if valid else None,

                prefix + '_oi':
                    oi,

                prefix + '_oi_formatted':
                    fmt(oi),

                prefix + '_oi_chg':
                    change,

                prefix + '_oi_chg_formatted':
                    fmt(change),

                prefix + '_oi_pct_chg':
                    pct,

                prefix + '_quote_time':
                    ts,

                prefix + '_baseline_at':
                    base[1] if base else None,

                prefix + '_oi_baseline_status':
                    'ok' if base else 'loading / unavailable'
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

    # OI concentrations, constrained to displayed expiry/range.
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

    # Descriptive OI balance on a 0..100 scale.
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
            key=lambda v: datetime.strptime(
                v, '%d-%b-%Y'
            )
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
    # live ATM must use actual index spot.

    symbol = symbol.upper()
    num_strikes = int(num_strikes)

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

            spotraw = kite.quote(
                [INDEX[symbol]]
            ).get(INDEX[symbol], {})

            spot = spotraw.get('last_price')
            spot_ts = quote_time(spotraw)

            if (
                not numeric(spot)
                or spot <= 0
                or spot_ts is None
            ):
                raise HTTPException(
                    503,
                    'Live index spot/timestamp unavailable.'
                )

            ladder = sorted({
                float(r['strike'])
                for r in rows
                if shared.expiry_date(r['expiry']) == exp
            })

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

            keys = [
                'NFO:' + r['tradingsymbol']
                for r in rows
                if shared.expiry_date(r['expiry']) == exp
                and float(r['strike']) in chosen
            ]

            raw = kite.quote(keys)

            today_raw = {
                k: q
                for k, q in raw.items()
                if quote_time(q) is not None
                and datetime.fromtimestamp(
                    quote_time(q), IST
                ).date() == now.date()
            }

            contracts = [
                (
                    'NFO:' + r['tradingsymbol'],
                    r['instrument_token']
                )
                for r in rows
                if 'NFO:' + r['tradingsymbol'] in keys
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

            # Save actual option-chain snapshots to PostgreSQL.
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
                'Kite option chain request failed'
            )

            raise HTTPException(
                503,
                'Kite option chain unavailable. Check token, connectivity and market-data access.'
            ) from None
