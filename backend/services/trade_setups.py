"""Four descriptive option setup scores. Missing factors are never fabricated."""

import math
import time
from datetime import datetime
from threading import Lock

from fastapi import APIRouter, Query, HTTPException

from . import oi_signal as shared
from .option_chain import get_dynamic_option_chain
from .chart_service import get_chart_data
from .chart_indicators import enrich
from .option_model import suitability


router = APIRouter()
lock = Lock()
cache = {}

ACTIONS = ("CALL BUY", "PUT BUY", "CALL SELL", "PUT SELL")

# The requested raw weights total 110. These normalized weights preserve
# their relative importance while making the complete score exactly 100.
WEIGHTS = {
    "Trend / EMA50": 10.91,
    "Price structure breakout": 9.09,
    "Session VWAP": 9.09,
    "WMA8 + MA8 fast alignment": 7.27,
    "RSI14": 7.27,
    "MACD histogram": 6.36,
    "Direct-sum OI crossover": 10.91,
    "Direct-sum OI dominance": 7.27,
    "PCR": 6.36,
    "IV / Greeks / expiry suitability (model)": 9.09,
    "Executable bid/ask": 3.64,
    "Bid/ask spread <=1%": 3.64,
    "MFI14": 4.55,
    "PVT vs EMA9 signal": 4.55,
}

TOTAL_WEIGHT = 100.0
CHART_TIMEFRAME = "15m"
CANDLE_SECONDS = 15 * 60


def numeric(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def rule(name, passed, detail):
    return {
        "name": name,
        "weight": WEIGHTS[name],
        "passed": passed,
        "detail": detail,
    }


def score_card(action, checks, market_ready, execution, budget=None):
    known = round(
        sum(c["weight"] for c in checks if c["passed"] is not None), 2
    )
    earned = round(
        sum(c["weight"] for c in checks if c["passed"] is True), 2
    )
    excluded = [c["name"] for c in checks if c["passed"] is None]

    base_raw = earned / known * 100 if known > 0 else None
    base = round(base_raw, 2) if base_raw is not None else None

    loss = execution.get("max_loss")
    valid_loss = numeric(loss) and loss >= 0
    has_budget = numeric(budget) and budget > 0

    if has_budget and valid_loss:
        fit = min(1.0, budget / loss) if loss > 0 else 1.0
    else:
        fit = None

    adjusted = (
        round(base_raw * fit, 2)
        if base_raw is not None and fit is not None
        else base
    )

    reasons = []

    if not market_ready:
        reasons.append("Stale/incomplete essential market inputs")
    if known <= 0:
        reasons.append("No available checks")
    if not execution.get("valid"):
        reasons.append("Executable quote / protective hedge unavailable")
    if not valid_loss:
        reasons.append("Estimated maximum loss unavailable")
    if not has_budget:
        reasons.append("Set your maximum loss budget")
    elif valid_loss and loss > budget:
        reasons.append(
            "Estimated maximum loss exceeds your limit; minimum one-lot trade is blocked"
        )

    if fit is not None and fit < 0.70:
        reasons.append("Risk Fit is below the required 70% minimum")

    score = adjusted if market_ready else None
    hard_block = bool(reasons)

    ready = (
        not hard_block
        and score is not None
        and score >= 78
    )

    if ready:
        status = "TRADE READY — REVIEW"
    elif has_budget and valid_loss and loss > budget:
        status = "NO TRADE — LOSS LIMIT"
    elif fit is not None and fit < 0.70:
        status = "NO TRADE — RISK FIT BELOW 70%"
    elif hard_block or score is None or score < 65:
        status = "NO TRADE"
    else:
        status = "WATCH ONLY"

    return {
        "action": action,
        "score": score,
        "base_score": base if market_ready else None,
        "risk_fit_pct": round(fit * 100, 2) if fit is not None else None,
        "matched_weight": earned,
        "known_weight": known,
        "missing_weight": max(0.0, round(TOTAL_WEIGHT - known, 2)),
        "excluded_checks": excluded,
        "partial": bool(excluded),
        "checks": checks,
        "status": status,
        "color": (
            "green" if ready
            else "yellow" if not hard_block and score is not None and score >= 65
            else "red"
        ),
        "blockers": reasons,
        "execution": execution,
        "profit_probability": None,
    }


def oi_context(data, now):
    """Rebuild the continuous direct-sum OI series used by the OI graph."""
    if data.get("weights") != [1, 1, 1]:
        raise ValueError(
            "Direct-sum OI data required; install direct-sum recorder update"
        )
    if not data.get("points"):
        raise ValueError("OI history empty")

    minutes = {}
    segment = None
    offset_a = offset_b = last_a = last_b = base_a = base_b = 0

    for point in sorted(data["points"], key=lambda p: p["time"]):
        if point["segment"] != segment:
            offset_a, offset_b = last_a, last_b
            base_a = point["put_change"]
            base_b = point["call_change"]
            segment = point["segment"]

        last_a = offset_a + point["put_change"] - base_a
        last_b = offset_b + point["call_change"] - base_b

        minute = int(point["time"] // 60 * 60)
        minutes[minute] = {
            "time": minute,
            "segment": segment,
            "a": last_a,
            "b": last_b,
        }

    previous = None
    sign = 0
    cross = 0
    cross_time = None

    for point in sorted(minutes.values(), key=lambda p: p["time"]):
        # Only completed one-minute observations may confirm a crossover.
        if point["time"] + 60 > now:
            continue

        if (
            previous is None
            or point["segment"] != previous["segment"]
            or point["time"] - previous["time"] > 60
        ):
            sign = 0

        current = (point["a"] > point["b"]) - (point["a"] < point["b"])

        if current and sign and current != sign:
            cross = current
            cross_time = point["time"]

        if current:
            sign = current

        previous = point

    dominance = (last_a > last_b) - (last_a < last_b)

    if previous is None or previous["segment"] != segment:
        cross = 0
        cross_time = None

    eligible = (
        cross_time is not None
        and 0 <= now - (cross_time + 60) <= 300
        and cross == dominance
    )

    return {
        "direction": dominance,
        "cross_direction": cross if eligible else 0,
        "cross_time": cross_time,
        "a": last_a,  # Put OI change
        "b": last_b,  # Call OI change
        "put_change": last_a,
        "call_change": last_b,
    }


def execution_plan(action, atm, step, contracts, quotes):
    option_type = "CE" if action.startswith("CALL") else "PE"
    is_sell = action.endswith("SELL")
    strike_direction = 1 if option_type == "CE" else -1

    strikes = (
        [atm + strike_direction * step, atm + strike_direction * 2 * step]
        if is_sell
        else [atm]
    )

    legs = []
    spreads = []
    net_credit = 0.0
    lot_size = None
    valid = True

    for index, strike in enumerate(strikes):
        contract = contracts.get((strike, option_type))

        if not contract:
            return {
                "valid": False,
                "legs": [],
                "max_loss": None,
                "reason": "Selected listed contract missing",
            }

        side = "SELL" if is_sell and index == 0 else "BUY"
        quote_key = "NFO:" + contract["tradingsymbol"]
        quote = quotes.get(quote_key, {})
        depth = quote.get("depth", {})

        bid = (depth.get("buy") or [{}])[0].get("price")
        ask = (depth.get("sell") or [{}])[0].get("price")

        book_ok = numeric(bid) and numeric(ask) and 0 < bid <= ask

        if not book_ok:
            valid = False
            price = None
            spreads.append(None)
        else:
            price = bid if side == "SELL" else ask
            net_credit += price if side == "SELL" else -price
            midpoint = (ask + bid) / 2
            spreads.append((ask - bid) / midpoint * 100 if midpoint > 0 else None)

        current_lot = contract.get("lot_size")
        if (
            not numeric(current_lot)
            or current_lot <= 0
            or (lot_size is not None and lot_size != current_lot)
        ):
            valid = False

        lot_size = current_lot if lot_size is None else lot_size

        legs.append({
            "side": side,
            "type": option_type,
            "strike": strike,
            "symbol": contract["tradingsymbol"],
            "price": price,
        })

    if is_sell and not 0 < net_credit < step:
        valid = False

    max_loss = (
        round((step - net_credit) * lot_size, 2)
        if valid and is_sell and lot_size
        else round(-net_credit * lot_size, 2)
        if valid and not is_sell and lot_size
        else None
    )

    all_spreads_available = bool(spreads) and all(
        value is not None for value in spreads
    )

    return {
        "valid": valid,
        "legs": legs,
        "lot_size": lot_size,
        "max_loss": max_loss,
        "max_loss_basis": (
            "One lot, full premium at risk for buys; defined-width hedge loss "
            "for sells. Excludes charges/slippage."
        ),
        "premium_credit": round(net_credit, 2) if is_sell and valid else None,
        "spread_pct": max(spreads) if all_spreads_available else None,
    }


@router.get("/api/signals/trade-setups")
def setups(
    expiry: str | None = Query(None),
    risk_budget: float | None = Query(None, gt=0),
):
    with lock:
        cache_key = (expiry, risk_budget)
        cached = cache.get(cache_key)

        if cached and time.monotonic() - cached[0] < 10:
            return cached[1]

        try:
            now = datetime.now(shared.IST)
            epoch = now.timestamp()

            chain = get_dynamic_option_chain("NIFTY", expiry, 3)

            # Use the same 15-minute timeframe as the main chart.
            chart = get_chart_data(
                symbol="NIFTY_FUT",
                timeframe=CHART_TIMEFRAME,
                count=500,
                session=False,
            )

            if (
                chart.get("source") != "kite"
                or chart.get("symbol") != "NIFTY_FUT"
            ):
                raise HTTPException(
                    503,
                    "Actual NIFTY futures candles required for setup scoring.",
                )

            candles = [
                candle
                for candle in chart["candles"]
                if candle["time"] + CANDLE_SECONDS <= epoch
            ]

            if len(candles) < 55:
                raise HTTPException(
                    503,
                    "Insufficient completed 15-minute candles for EMA50 and setup indicators.",
                )

            computed = enrich(
                {
                    "candles": candles,
                    "timeframe": CHART_TIMEFRAME,
                    "indicators": {},
                },
                volume_supported=True,
            )

            indicators = computed["indicators"]
            last = candles[-1]
            prior = candles[-6:-1]

            chart_age = epoch - (last["time"] + CANDLE_SECONDS)
            spot_quote_time = chain.get("spot_quote_at")

            market_ready = (
                chain.get("status") == "fresh"
                and numeric(spot_quote_time)
                and -5 <= epoch - spot_quote_time <= 90
                and 0 <= chart_age <= CANDLE_SECONDS
                and datetime.fromtimestamp(last["time"], shared.IST).date()
                == now.date()
            )

            oi = None
            oi_error = None

            try:
                from .session_recorder import recorder

                oi_data = recorder.read(
                    "NIFTY",
                    chain["selected_expiry"],
                    3,
                    0,
                )

                oi_quote_time = oi_data.get("quote_time")

                if (
                    oi_data.get("status") != "fresh"
                    or not numeric(oi_quote_time)
                    or not -5 <= epoch - oi_quote_time <= 30
                ):
                    raise ValueError("Direct-sum OI snapshots are stale")

                oi = oi_context(oi_data, epoch)

            except Exception:
                oi_error = (
                    "Continuous direct-sum OI history unavailable, stale, "
                    "or incompatible"
                )

            atm = chain["atm_strike"]
            rows = chain["strikes"]
            ladder = sorted({float(row["strike"]) for row in rows})
            gaps = [
                right - left
                for left, right in zip(ladder, ladder[1:])
                if right > left
            ]

            if not gaps:
                raise HTTPException(
                    503,
                    "Option strike interval unavailable.",
                )

            step = min(gaps)

            kite = shared.kite_client()
            selected_expiry = datetime.strptime(
                chain["selected_expiry"], "%d-%b-%Y"
            ).date()

            with shared.lock:
                listed = shared.instruments(kite, now.date())

            contracts = {
                (float(row["strike"]), row["instrument_type"]): row
                for row in listed
                if (
                    row.get("name") == "NIFTY"
                    and row.get("instrument_type") in ("CE", "PE")
                    and shared.expiry_date(row["expiry"]) == selected_expiry
                )
            }

            wanted = {
                (atm, "CE"),
                (atm, "PE"),
                (atm + step, "CE"),
                (atm + 2 * step, "CE"),
                (atm - step, "PE"),
                (atm - 2 * step, "PE"),
            }

            quote_symbols = [
                "NFO:" + contracts[key]["tradingsymbol"]
                for key in wanted
                if key in contracts
            ]

            raw_quotes = kite.quote(quote_symbols) if quote_symbols else {}

            if len(raw_quotes) != len(wanted):
                market_ready = False

            for quote in raw_quotes.values():
                try:
                    quote_time = shared.provider_time(quote.get("timestamp"))
                    if not numeric(quote_time) or not -5 <= epoch - quote_time <= 90:
                        market_ready = False
                except Exception:
                    market_ready = False

            historical_volatility = None

            try:
                daily = get_chart_data(
                    symbol="NIFTY",
                    timeframe="1D",
                    count=60,
                    session=False,
                )

                daily_closes = [
                    candle["close"]
                    for candle in daily["candles"]
                    if (
                        datetime.fromtimestamp(
                            candle["time"], shared.IST
                        ).date() < now.date()
                        and numeric(candle.get("close"))
                        and candle["close"] > 0
                    )
                ]

                if daily.get("source") == "kite" and len(daily_closes) >= 21:
                    returns = [
                        math.log(right / left)
                        for left, right in zip(
                            daily_closes[-21:-1],
                            daily_closes[-20:],
                        )
                    ]
                    mean_return = sum(returns) / len(returns)
                    historical_volatility = math.sqrt(
                        sum((value - mean_return) ** 2 for value in returns)
                        / (len(returns) - 1)
                        * 252
                    )

            except Exception:
                pass

            price = last["close"]
            ema50 = indicators.get("ema50")
            ma8 = indicators.get("ma8")
            wma8 = indicators.get("wma8")
            vwap = indicators.get("vwap")
            rsi = indicators.get("rsi14")
            macd_histogram = indicators.get("macd_histogram")
            mfi = indicators.get("mfi14")
            pvt = indicators.get("pvt")
            pvt_signal_line = indicators.get("pvt_signal_line")
            pcr = chain.get("pcr")

            cards = []

            for action in ACTIONS:
                bullish = action in ("CALL BUY", "PUT SELL")
                direction = 1 if bullish else -1

                execution = execution_plan(
                    action,
                    atm,
                    step,
                    contracts,
                    raw_quotes,
                )

                suitable, model_detail = suitability(
                    action,
                    execution,
                    contracts,
                    raw_quotes,
                    chain.get("spot", chain.get("spot_price", 0)),
                    selected_expiry,
                    now,
                    historical_volatility,
                )

                # EMA50 directional trend.
                ema50_pass = (
                    price > ema50 if bullish else price < ema50
                ) if numeric(ema50) else None

                # Breakout against the previous five completed candles.
                if len(prior) == 5:
                    breakout_pass = (
                        price > max(candle["high"] for candle in prior)
                        if bullish
                        else price < min(candle["low"] for candle in prior)
                    )
                else:
                    breakout_pass = None

                # Session VWAP from actual NIFTY futures traded volume.
                vwap_pass = (
                    price > vwap if bullish else price < vwap
                ) if numeric(vwap) else None

                # Fast alignment: WMA8 above/below MA8 and price on the
                # same side of WMA8.
                fast_alignment = (
                    wma8 > ma8 and price > wma8
                    if bullish
                    else wma8 < ma8 and price < wma8
                ) if numeric(wma8) and numeric(ma8) else None

                # Directional momentum ranges.
                rsi_pass = (
                    52 < rsi < 68 if bullish else 32 < rsi < 48
                ) if numeric(rsi) else None

                macd_pass = (
                    macd_histogram > 0
                    if bullish
                    else macd_histogram < 0
                ) if numeric(macd_histogram) else None

                oi_cross_pass = (
                    oi["cross_direction"] == direction
                    if oi is not None
                    else None
                )

                # Use the requested 1.3x direct-sum dominance threshold.
                if oi is None:
                    oi_dominance_pass = None
                elif bullish:
                    oi_dominance_pass = (
                        oi["put_change"] > oi["call_change"] * 1.3
                    )
                else:
                    oi_dominance_pass = (
                        oi["call_change"] > oi["put_change"] * 1.3
                    )

                pcr_pass = (
                    pcr > 1.15 if bullish else pcr < 0.85
                ) if numeric(pcr) else None

                # MFI is direction-specific: 50–70 for bullish momentum,
                # 30–50 for bearish momentum. Actual volume is required.
                mfi_pass = (
                    50 < mfi < 70 if bullish else 30 < mfi < 50
                ) if numeric(mfi) else None

                # PVT above its EMA9 signal line supports bullish direction;
                # below it supports bearish direction.
                pvt_pass = (
                    pvt > pvt_signal_line
                    if bullish
                    else pvt < pvt_signal_line
                ) if numeric(pvt) and numeric(pvt_signal_line) else None

                checks = [
                    rule(
                        "Trend / EMA50",
                        ema50_pass,
                        "Completed 15-minute NIFTY futures close vs EMA50",
                    ),
                    rule(
                        "Price structure breakout",
                        breakout_pass,
                        "Close beyond the previous five completed 15-minute bars",
                    ),
                    rule(
                        "Session VWAP",
                        vwap_pass,
                        "NIFTY futures session VWAP from actual traded volume",
                    ),
                    rule(
                        "WMA8 + MA8 fast alignment",
                        fast_alignment,
                        "Bullish: WMA8 > MA8 and price > WMA8; bearish: WMA8 < MA8 and price < WMA8",
                    ),
                    rule(
                        "RSI14",
                        rsi_pass,
                        "Bullish range 52–68; bearish range 32–48",
                    ),
                    rule(
                        "MACD histogram",
                        macd_pass,
                        "Bullish above zero; bearish below zero (MACD 12/26/9)",
                    ),
                    rule(
                        "Direct-sum OI crossover",
                        oi_cross_pass,
                        oi_error or "Confirmed same-basket direct-sum crossover within five minutes",
                    ),
                    rule(
                        "Direct-sum OI dominance",
                        oi_dominance_pass,
                        oi_error or "Put OI change > Call OI change × 1.3 for bullish; reverse for bearish",
                    ),
                    rule(
                        "PCR",
                        pcr_pass,
                        "Selected expiry and ±3 strike range; bullish >1.15, bearish <0.85",
                    ),
                    rule(
                        "IV / Greeks / expiry suitability (model)",
                        suitable,
                        model_detail,
                    ),
                    rule(
                        "Executable bid/ask",
                        execution.get("valid"),
                        "BUY at ask / SELL at bid; SELL setups require a protective hedge",
                    ),
                    rule(
                        "Bid/ask spread <=1%",
                        (
                            execution.get("spread_pct") <= 1
                            if numeric(execution.get("spread_pct"))
                            else None
                        ),
                        "Maximum quoted leg spread must be 1% or less",
                    ),
                    rule(
                        "MFI14",
                        mfi_pass,
                        "Actual-volume MFI14; bullish range 50–70, bearish range 30–50",
                    ),
                    rule(
                        "PVT vs EMA9 signal",
                        pvt_pass,
                        "PVT above EMA9 for bullish direction; below EMA9 for bearish direction",
                    ),
                ]

                cards.append(
                    score_card(
                        action,
                        checks,
                        market_ready,
                        execution,
                        risk_budget,
                    )
                )

            result = {
                "source": "kite",
                "status": "fresh" if market_ready else "stale",
                "expiry": chain["selected_expiry"],
                "quote_time": chain.get("spot_quote_at"),
                "fetched_at": int(epoch),
                "indicator_instrument": chart.get(
                    "instrument", "NIFTY futures"
                ),
                "cards": cards,
                "note": (
                    "Weights are normalized to 100 while preserving the "
                    "relative proportions of the requested 110 raw points. "
                    "Base score = matched available points / available points "
                    "× 100. Missing checks are excluded and coverage is shown. "
                    "Displayed score = base score × Risk Fit when a valid "
                    "budget and one-lot maximum loss are available. Risk Fit "
                    "below 70%, maximum loss above budget, stale essential "
                    "data, or invalid execution blocks a trade. Scores are "
                    "setup agreement, not profit probability."
                ),
            }

            cache[cache_key] = (time.monotonic(), result)
            return result

        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                503,
                "Trade setup inputs unavailable. Check actual Kite quotes, "
                "15-minute futures history, OI recorder, and option contracts.",
            ) from None
