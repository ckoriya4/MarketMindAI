
"""Read actual saved option-chain history from PostgreSQL."""

from datetime import date, datetime
from fastapi import HTTPException

from .database import get_db_connection


IST_NAME = "Asia/Kolkata"


def _expiry_date(value):
    """Accept ISO dates or the existing DD-MMM-YYYY UI format."""
    if isinstance(value, date):
        return value

    if not value:
        return None

    value = str(value).strip()

    for fmt in ("%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(value.upper(), fmt).date()
        except ValueError:
            pass

    raise HTTPException(422, "Invalid expiry date.")


def _expiry_label(value):
    return value.strftime("%d-%b-%Y").upper()


def _fmt(value):
    if value is None:
        return "—"

    value = float(value)

    if abs(value) >= 10_000_000:
        return f"{value / 10_000_000:.2f}Cr"

    return f"{value / 100_000:.1f}L"


def get_option_history_dates(symbol):
    """Return dates that really have saved option-chain records."""

    symbol = symbol.strip().upper()

    try:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    (recorded_at AT TIME ZONE 'Asia/Kolkata')::date
                        AS history_date,
                    COUNT(*) AS record_count
                FROM option_chain_history
                WHERE symbol = %s
                GROUP BY 1
                ORDER BY 1 DESC
                """,
                (symbol,)
            ).fetchall()

        return {
            "symbol": symbol,
            "dates": [
                {
                    "date": row["history_date"].isoformat(),
                    "records": int(row["record_count"])
                }
                for row in rows
            ]
        }

    except Exception:
        raise HTTPException(
            503,
            "Cannot read option-chain history from PostgreSQL."
        ) from None


def get_historical_option_chain(
    symbol,
    history_date,
    expiry=None,
    num_strikes=7
):
    """
    Return the latest saved CE/PE record per strike for one date.

    This reads saved records only. It never generates missing prices or OI.
    """

    symbol = symbol.strip().upper()

    if symbol not in (
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "NIFTYNXT50",
        "SENSEX",
        "BANKEX"
    ):
        raise HTTPException(422, "Unsupported option-chain symbol.")

    try:
        selected_date = date.fromisoformat(str(history_date))
    except (TypeError, ValueError):
        raise HTTPException(
            422,
            "Date must use YYYY-MM-DD format."
        ) from None

    if not 3 <= int(num_strikes) <= 50:
        raise HTTPException(422, "Strike range must be 3..50.")

    selected_expiry = _expiry_date(expiry) if expiry else None

    try:
        with get_db_connection() as conn:

            # Fetch the latest saved record for each contract on this date.
            records = conn.execute(
                """
                SELECT DISTINCT ON (
                    expiry,
                    strike,
                    option_type
                )
                    expiry,
                    strike,
                    option_type,
                    ltp,
                    oi,
                    oi_change,
                    volume,
                    iv,
                    delta,
                    gamma,
                    theta,
                    vega,
                    recorded_at
                FROM option_chain_history
                WHERE symbol = %s
                  AND (recorded_at AT TIME ZONE 'Asia/Kolkata')::date = %s
                  AND (%s IS NULL OR expiry = %s)
                ORDER BY
                    expiry,
                    strike,
                    option_type,
                    recorded_at DESC
                """,
                (
                    symbol,
                    selected_date,
                    selected_expiry,
                    selected_expiry
                )
            ).fetchall()

            # Use a historical underlying quote only if one was saved.
            spot_symbols = {
                "NIFTY": ["NIFTY", "NIFTY 50", "NSE:NIFTY 50"],
                "BANKNIFTY": [
                    "BANKNIFTY",
                    "NIFTY BANK",
                    "NSE:NIFTY BANK"
                ],
                "FINNIFTY": [
                    "FINNIFTY",
                    "NIFTY FIN SERVICE",
                    "NSE:NIFTY FIN SERVICE"
                ],
                "MIDCPNIFTY": ["MIDCPNIFTY", "NIFTY MID SELECT"],
                "NIFTYNXT50": ["NIFTYNXT50", "NIFTY NEXT 50"],
                "SENSEX": ["SENSEX", "BSE:SENSEX"],
                "BANKEX": ["BANKEX", "BSE:BANKEX"]
            }

            spot_row = conn.execute(
                """
                SELECT ltp, recorded_at
                FROM market_quotes
                WHERE symbol = ANY(%s)
                  AND (recorded_at AT TIME ZONE 'Asia/Kolkata')::date = %s
                  AND ltp IS NOT NULL
                ORDER BY recorded_at DESC
                LIMIT 1
                """,
                (spot_symbols[symbol], selected_date)
            ).fetchone()

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            503,
            "Cannot load historical option-chain records."
        ) from None

    if not records:
        raise HTTPException(
            404,
            f"No saved option-chain records for {symbol} on "
            f"{selected_date.isoformat()}."
        )

    available_expiries = sorted({
        row["expiry"] for row in records
    })

    if not available_expiries:
        raise HTTPException(
            404,
            "No saved option expiries were found for this date."
        )

    actual_expiry = selected_expiry or available_expiries[0]

    if actual_expiry not in available_expiries:
        raise HTTPException(
            404,
            "No saved records for the selected expiry on this date."
        )

    records = [
        row for row in records
        if row["expiry"] == actual_expiry
    ]

    paired = {}

    for row in records:
        strike = float(row["strike"])
        option_type = row["option_type"]

        if option_type not in ("CE", "PE"):
            continue

        paired.setdefault(strike, {})[option_type] = row

    ladder = sorted(paired)

    if not ladder:
        raise HTTPException(
            404,
            "No CE/PE strike records are available for this expiry."
        )

    spot = (
        float(spot_row["ltp"])
        if spot_row and spot_row["ltp"] is not None
        else None
    )

    # Center by actual historical spot when available.
    # Otherwise use the middle of the stored strike ladder without
    # incorrectly marking any strike as ATM.
    center_index = (
        min(
            range(len(ladder)),
            key=lambda i: abs(ladder[i] - spot)
        )
        if spot is not None
        else len(ladder) // 2
    )

    start = max(0, center_index - int(num_strikes))
    end = center_index + int(num_strikes) + 1
    selected_strikes = ladder[start:end]

    def number(row, field):
        value = row.get(field)
        return float(value) if value is not None else None

    results = []
    missing = []
    timestamps = []

    for strike in selected_strikes:
        ce = paired[strike].get("CE")
        pe = paired[strike].get("PE")

        if ce is None:
            missing.append(f"{strike} CE")

        if pe is None:
            missing.append(f"{strike} PE")

        call_oi = number(ce, "oi") if ce else None
        put_oi = number(pe, "oi") if pe else None

        call_ltp = number(ce, "ltp") if ce else None
        put_ltp = number(pe, "ltp") if pe else None

        call_change = number(ce, "oi_change") if ce else None
        put_change = number(pe, "oi_change") if pe else None

        call_pct = None
        put_pct = None

        if call_oi is not None and call_change is not None:
            previous = call_oi - call_change
            if previous > 0:
                call_pct = round(call_change / previous * 100, 2)

        if put_oi is not None and put_change is not None:
            previous = put_oi - put_change
            if previous > 0:
                put_pct = round(put_change / previous * 100, 2)

        if ce and ce.get("recorded_at"):
            timestamps.append(ce["recorded_at"])

        if pe and pe.get("recorded_at"):
            timestamps.append(pe["recorded_at"])

        results.append({
            "strike": strike,
            "is_atm": spot is not None and strike == ladder[
                min(
                    range(len(ladder)),
                    key=lambda i: abs(ladder[i] - spot)
                )
            ],
            "is_resistance": False,
            "is_support": False,

            "call_ltp": call_ltp,
            "call_oi": call_oi,
            "call_oi_formatted": _fmt(call_oi),
            "call_oi_chg": call_change,
            "call_oi_chg_formatted": _fmt(call_change),
            "call_oi_pct_chg": call_pct,

            "put_ltp": put_ltp,
            "put_oi": put_oi,
            "put_oi_formatted": _fmt(put_oi),
            "put_oi_chg": put_change,
            "put_oi_chg_formatted": _fmt(put_change),
            "put_oi_pct_chg": put_pct,

            "strike_pcr": (
                round(put_oi / call_oi, 2)
                if call_oi is not None
                and call_oi > 0
                and put_oi is not None
                else None
            ),

            "call_bar_pct": 0.0,
            "put_bar_pct": 0.0
        })

    max_oi = max(
        [
            value
            for row in results
            for value in (row["call_oi"], row["put_oi"])
            if value is not None
        ] or [1]
    )

    for row in results:
        row["call_bar_pct"] = round(
            (row["call_oi"] or 0) / max_oi * 100, 1
        )
        row["put_bar_pct"] = round(
            (row["put_oi"] or 0) / max_oi * 100, 1
        )

    complete = not missing

    total_call = (
        sum(row["call_oi"] for row in results)
        if complete and all(row["call_oi"] is not None for row in results)
        else None
    )

    total_put = (
        sum(row["put_oi"] for row in results)
        if complete and all(row["put_oi"] is not None for row in results)
        else None
    )

    pcr = (
        round(total_put / total_call, 2)
        if total_call is not None
        and total_put is not None
        and total_call > 0
        else None
    )

    resistance = None
    support = None

    if complete and spot is not None:
        candidates = [
            row for row in results
            if row["strike"] >= spot and (row["call_oi"] or 0) > 0
        ]
        if candidates:
            resistance = max(candidates, key=lambda row: row["call_oi"])

        candidates = [
            row for row in results
            if row["strike"] <= spot and (row["put_oi"] or 0) > 0
        ]
        if candidates:
            support = max(candidates, key=lambda row: row["put_oi"])

    if resistance:
        resistance["is_resistance"] = True

    if support:
        support["is_support"] = True

    latest_timestamp = max(timestamps) if timestamps else None

    score = (
        round(100 * total_put / (total_put + total_call))
        if total_put is not None
        and total_call is not None
        and total_put + total_call > 0
        else None
    )

    return {
        "symbol": symbol,
        "spot_price": spot,
        "atm_strike": (
            ladder[center_index] if spot is not None else None
        ),
        "selected_expiry": _expiry_label(actual_expiry),
        "available_expiries": [
            _expiry_label(value) for value in available_expiries
        ],
        "days_to_expiry": (actual_expiry - selected_date).days,

        "total_call_oi": _fmt(total_call),
        "total_put_oi": _fmt(total_put),
        "pcr": pcr,
        "pcr_bias": (
            "Bullish" if pcr is not None and pcr > 1.12
            else "Bearish" if pcr is not None and pcr < 0.88
            else "Neutral" if pcr is not None
            else "Unavailable"
        ),

        "resistance_strike": (
            resistance["strike"] if resistance else None
        ),
        "resistance_oi": _fmt(
            resistance["call_oi"] if resistance else None
        ),
        "support_strike": support["strike"] if support else None,
        "support_oi": _fmt(
            support["put_oi"] if support else None
        ),

        "ab_score": {
            "score": score,
            "trend": (
                "Put OI dominant" if score is not None and score > 50
                else "Call OI dominant" if score is not None and score < 50
                else "Balanced" if score is not None
                else "Unavailable"
            ),
            "recommendation": "HISTORICAL DATA — NOT A LIVE SIGNAL",
            "color": "amber"
        },

        "strikes": results,
        "timestamp": (
            latest_timestamp.isoformat()
            if latest_timestamp else selected_date.isoformat()
        ),
        "data_mode": "PostgreSQL · historical saved records",
        "status": "historical" if complete else "partial historical",
        "source": "postgresql",
        "missing_contracts": missing,
        "level_scope": (
            "Levels are calculated only from stored strikes. "
            "ATM and support/resistance require a saved historical spot."
        ),
        "score_method": (
            "Descriptive OI balance calculated from stored selected strikes; "
            "not a live trading signal."
        )
    }
