"""Kite OHLCV chart data for an individually selected listed option contract.

All candles, prices and traded volumes come from Kite. No synthetic data is used.
"""

import logging
import math
import time
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import HTTPException
from kiteconnect.exceptions import TokenException

from . import oi_signal as shared
from .chart_service import (
    INTERVALS,
    normalize_records,
    quote_metadata,
    weekly,
)
from .chart_indicators import enrich
from .market_session import intraday_session
from .option_chain import OPTION_EXCHANGE, listed


IST = timezone(timedelta(hours=5, minutes=30))
_cache = {}
_history_cache = {}
_lock = Lock()


def _parse_expiry(value):
    if not value:
        raise HTTPException(422, "An option expiry is required.")

    if hasattr(value, "date"):
        return value.date() if isinstance(value, datetime) else value

    text = str(value).strip().upper()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    raise HTTPException(
        422,
        "Expiry must use YYYY-MM-DD or DD-MMM-YYYY format."
    )


def _step_seconds(timeframe):
    return {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1H": 3600,
        "1D": 86400,
        "W": 604800,
    }[timeframe]


def get_option_chart_data(
    symbol="NIFTY",
    expiry=None,
    strike=None,
    option_type="CE",
    timeframe="15m",
    count=1000,
    session=True,
):
    """Return actual Kite candles and indicators for one listed option."""

    symbol = str(symbol).strip().upper()
    option_type = str(option_type).strip().upper()

    if symbol not in OPTION_EXCHANGE:
        raise HTTPException(422, "Unsupported option-chain market.")

    if option_type not in ("CE", "PE"):
        raise HTTPException(422, "option_type must be CE or PE.")

    if timeframe not in INTERVALS:
        raise HTTPException(422, "Unsupported chart timeframe.")

    if not isinstance(strike, (int, float)) or isinstance(strike, bool) or not math.isfinite(strike) or strike <= 0:
        raise HTTPException(422, "A valid option strike is required.")

    if not 20 <= int(count) <= 1000:
        raise HTTPException(422, "count must be between 20 and 1000.")

    selected_expiry = _parse_expiry(expiry)
    strike = float(strike)
    exchange = OPTION_EXCHANGE[symbol]

    with _lock:
        now = datetime.now(IST)
        cache_key = (
            symbol,
            selected_expiry.isoformat(),
            strike,
            option_type,
            timeframe,
            int(count),
            bool(session),
        )

        cached = _cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 3:
            return cached[1]

        try:
            kite = shared.kite_client()
            contracts = listed(kite, symbol, now)

            matches = [
                row for row in contracts
                if (
                    shared.expiry_date(row["expiry"]) == selected_expiry
                    and row.get("instrument_type") == option_type
                    and math.isclose(
                        float(row.get("strike", 0)),
                        strike,
                        rel_tol=0,
                        abs_tol=0.0001,
                    )
                )
            ]

            if not matches:
                raise HTTPException(
                    404,
                    f"No listed {symbol} {strike:g} {option_type} contract "
                    f"for expiry {selected_expiry.isoformat()}.",
                )

            contract = matches[0]
            token = contract.get("instrument_token")
            tradingsymbol = contract.get("tradingsymbol")
            contract_exchange = contract.get("exchange") or exchange

            if not token or not tradingsymbol:
                raise HTTPException(
                    503,
                    "Kite did not return a valid instrument token for this option.",
                )

            quote_key = f"{contract_exchange}:{tradingsymbol}"
            history_key = (int(token), timeframe)
            previous = _history_cache.get(history_key)

            full_reload = (
                previous is None
                or not previous.get("candles")
                or time.monotonic() - previous["loaded"] >= 1800
            )

            if full_reload:
                lookback_days = (
                    1900 if timeframe == "W"
                    else 400 if timeframe == "1D"
                    else 55
                )
                start = now - timedelta(days=lookback_days)
                existing = {}
                loaded_at = time.monotonic()
            else:
                step = _step_seconds(timeframe)
                existing = {
                    candle["time"]: candle
                    for candle in previous["candles"]
                }
                start = datetime.fromtimestamp(
                    previous["candles"][-1]["time"] - 2 * step,
                    IST,
                )
                loaded_at = previous["loaded"]

            records = []
            # Kite intraday requests are deliberately kept below 60 days.
            while start < now:
                end = min(
                    now,
                    start + timedelta(
                        days=55 if timeframe not in ("1D", "W") else 900
                    ),
                )
                records.extend(
                    kite.historical_data(
                        int(token),
                        start,
                        end,
                        INTERVALS[timeframe],
                    )
                )
                if end <= start:
                    break
                start = end

            incoming = normalize_records(records)
            if not incoming and not existing:
                raise HTTPException(
                    503,
                    "Kite returned no historical candles for the selected option contract.",
                )

            existing.update({candle["time"]: candle for candle in incoming})
            raw_candles = [
                existing[timestamp]
                for timestamp in sorted(existing)
                if timestamp <= now.timestamp()
            ]

            if not raw_candles:
                raise HTTPException(503, "No valid Kite candles are available.")

            _history_cache[history_key] = {
                "candles": raw_candles,
                "loaded": loaded_at,
            }

            candles = weekly(raw_candles) if timeframe == "W" else raw_candles

            quote_response = kite.quote([quote_key])
            quote = quote_response.get(quote_key, {})
            ltp = quote.get("last_price")

            if (
                not isinstance(ltp, (int, float))
                or isinstance(ltp, bool)
                or not math.isfinite(ltp)
                or ltp <= 0
            ):
                raise HTTPException(
                    503,
                    f"Kite live quote is unavailable for {quote_key}.",
                )

            previous_close = (quote.get("ohlc") or {}).get("close")
            valid_previous_close = (
                isinstance(previous_close, (int, float))
                and not isinstance(previous_close, bool)
                and math.isfinite(previous_close)
                and previous_close > 0
            )
            change = ltp - previous_close if valid_previous_close else None

            instrument_label = (
                f"{symbol} {strike:g} {option_type} · "
                f"{selected_expiry.strftime('%d-%b-%Y').upper()} · {contract_exchange}"
            )

            full = {
                "symbol": symbol,
                "timeframe": timeframe,
                "source": "kite",
                "data_mode": "Actual Kite option-contract OHLCV + live quote",
                "instrument": instrument_label,
                "instrument_token": int(token),
                "quote_key": quote_key,
                "option_contract": {
                    "symbol": symbol,
                    "exchange": contract_exchange,
                    "tradingsymbol": tradingsymbol,
                    "expiry": selected_expiry.isoformat(),
                    "strike": strike,
                    "option_type": option_type,
                },
                "selected_expiry": selected_expiry.strftime("%d-%b-%Y").upper(),
                "selected_strike": strike,
                "selected_option_type": option_type,
                "candles": candles,
                "indicators": {
                    "ltp": float(ltp),
                    "change": round(change, 2) if change is not None else None,
                    "change_pct": (
                        round(change / previous_close * 100, 2)
                        if change is not None else None
                    ),
                },
                "fetched_at": now.isoformat(),
            }

            # Listed CE/PE contracts have actual traded volume.
            # enrich() still reports unavailable volume-derived fields
            # when Kite's returned candles contain no positive volume.
            full = enrich(full, volume_supported=True)
            full.update(quote_metadata(quote, candles, now, timeframe))

            indicators = full["indicators"]
            full["latest_tick"] = dict(
                candles[-1],
                ema9=indicators.get("ema9"),
                ema21=indicators.get("ema21"),
                ma8=indicators.get("ma8"),
                wma8=indicators.get("wma8"),
                ma_wma_signal=indicators.get("ma_wma_signal"),
            )
            full["warmup_bars"] = len(candles)
            full["comparison_note"] = (
                "All chart prices and volume are from the selected listed option contract. "
                "Indicators are calculated from its own Kite OHLCV candles."
            )

            result = intraday_session(
                full,
                count=int(count),
                enabled=bool(session),
            )

            _cache[cache_key] = (time.monotonic(), result)
            return result

        except TokenException:
            raise HTTPException(
                401,
                "Kite session expired. Login again and restart the backend.",
            ) from None
        except HTTPException:
            raise
        except Exception as exc:
            logging.exception(
                "Option chart fetch failed: %s %s %s %s",
                symbol,
                selected_expiry,
                strike,
                option_type,
            )
            raise HTTPException(
                503,
                "Actual Kite option-chart data unavailable. Check contract listing, "
                "Kite historical access, quote access and connectivity.",
            ) from None
