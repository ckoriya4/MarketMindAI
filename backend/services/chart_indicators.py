
"""OHLCV-derived chart indicators; no synthetic prices or volume."""

from datetime import datetime, timedelta, timezone
import math

IST = timezone(timedelta(hours=5, minutes=30))


def ema(values, period):
    if not values:
        return []

    out = [values[0]]
    alpha = 2 / (period + 1)

    for value in values[1:]:
        out.append(
            out[-1] + (value - out[-1]) * alpha
        )

    return out


def wilder(values, period):
    result = [None] * len(values)

    if len(values) < period:
        return result

    avg = sum(values[:period]) / period
    result[period - 1] = avg

    for i in range(period, len(values)):
        avg = (
            avg * (period - 1) + values[i]
        ) / period

        result[i] = avg

    return result


def enrich(full, volume_supported=False):
    candles = full["candles"]
    closes = [c["close"] for c in candles]
    n = len(candles)

    volumes = [
        float(c.get("volume", 0) or 0)
        for c in candles
    ]

    has_volume_data = (
        volume_supported
        and any(volume > 0 for volume in volumes)
    )

    def series(values):
        return [
            {
                "time": c["time"],
                "value": round(v, 5)
            }
            for c, v in zip(candles, values)
            if (
                v is not None
                and isinstance(v, (int, float))
                and math.isfinite(v)
            )
        ]

    def last(points):
        return points[-1]["value"] if points else None

    result = dict(full)
    ind = dict(full.get("indicators", {}))

    # --------------------------------------------------
    # EMA 9, 21, 50, 200
    # --------------------------------------------------

    for period in (9, 21, 50, 200):
        values = ema(closes, period)

        result[f"ema{period}"] = series([
            value if i >= period - 1 else None
            for i, value in enumerate(values)
        ])

        ind[f"ema{period}"] = last(result[f"ema{period}"])

    # --------------------------------------------------
    # MA8 - Simple Moving Average
    # --------------------------------------------------

    ma8_values = [None] * n

    for i in range(7, n):
        window = closes[i - 7:i + 1]
        ma8_values[i] = sum(window) / 8

    result["ma8"] = series(ma8_values)
    ind["ma8"] = last(result["ma8"])

    # --------------------------------------------------
    # WMA8 - Weighted Moving Average
    # Latest candle weight = 8
    # Oldest candle weight = 1
    # Total weight = 36
    # --------------------------------------------------

    wma8_values = [None] * n

    weights = list(range(1, 9))
    weight_total = sum(weights)

    for i in range(7, n):
        window = closes[i - 7:i + 1]

        weighted_sum = sum(
            price * weight
            for price, weight in zip(window, weights)
        )

        wma8_values[i] = weighted_sum / weight_total

    result["wma8"] = series(wma8_values)
    ind["wma8"] = last(result["wma8"])

    # --------------------------------------------------
    # MA8 / WMA8 CROSSOVER SIGNAL
    # --------------------------------------------------

    ma_wma_signal = "HOLD"

    valid_indices = [
        i for i in range(n)
        if (
            ma8_values[i] is not None
            and wma8_values[i] is not None
        )
    ]

    if len(valid_indices) >= 2:
        previous = valid_indices[-2]
        current = valid_indices[-1]

        previous_ma = ma8_values[previous]
        previous_wma = wma8_values[previous]

        current_ma = ma8_values[current]
        current_wma = wma8_values[current]

        if (
            previous_ma <= previous_wma
            and current_ma > current_wma
        ):
            ma_wma_signal = "BUY"

        elif (
            previous_ma >= previous_wma
            and current_ma < current_wma
        ):
            ma_wma_signal = "SELL"

    ind["ma_wma_signal"] = ma_wma_signal

    # --------------------------------------------------
    # RSI 14
    # --------------------------------------------------

    gains = [
        max(closes[i] - closes[i - 1], 0)
        for i in range(1, n)
    ]

    losses = [
        max(closes[i - 1] - closes[i], 0)
        for i in range(1, n)
    ]

    g = wilder(gains, 14)
    l = wilder(losses, 14)

    rsi = [None] * n

    for i in range(len(g)):
        if g[i] is not None:
            rsi[i + 1] = (
                50 if g[i] == l[i] == 0
                else 100 if l[i] == 0
                else 100 - 100 / (1 + g[i] / l[i])
            )

    result["rsi14"] = series(rsi)
    ind["rsi14"] = last(result["rsi14"])

    # --------------------------------------------------
    # MACD 12 / 26 / 9
    # --------------------------------------------------

    fast = ema(closes, 12)
    slow = ema(closes, 26)

    macd = [
        f - s
        for f, s in zip(fast, slow)
    ]

    sig = ema(macd, 9)

    macd_values = [
        macd[i] if i >= 25 else None
        for i in range(n)
    ]

    signal_values = [
        sig[i] if i >= 33 else None
        for i in range(n)
    ]

    histogram_values = [
        macd[i] - sig[i] if i >= 33 else None
        for i in range(n)
    ]

    result["macd_line"] = series(macd_values)
    result["macd_signal"] = series(signal_values)
    result["macd_histogram"] = series(histogram_values)

    ind["macd_value"] = last(result["macd_line"])
    ind["macd_signal"] = last(result["macd_signal"])
    ind["macd_histogram"] = last(result["macd_histogram"])

    ind["macd"] = (
        "Bullish"
        if ind["macd_histogram"] is not None
        and ind["macd_histogram"] > 0
        else "Bearish"
        if ind["macd_histogram"] is not None
        and ind["macd_histogram"] < 0
        else "Neutral"
        if ind["macd_histogram"] is not None
        else "Unavailable"
    )

    # --------------------------------------------------
    # BOLLINGER BANDS 20
    # --------------------------------------------------

    upper = []
    middle = []
    lower = []

    for i in range(n):
        values = (
            closes[i - 19:i + 1]
            if i >= 19
            else []
        )

        mean = sum(values) / 20 if values else None

        sd = (
            math.sqrt(
                sum((p - mean) ** 2 for p in values) / 20
            )
            if values
            else None
        )

        middle.append(mean)
        upper.append(
            mean + 2 * sd if mean is not None else None
        )
        lower.append(
            mean - 2 * sd if mean is not None else None
        )

    for key, values in [
        ("bb_upper", upper),
        ("bb_middle", middle),
        ("bb_lower", lower)
    ]:
        result[key] = series(values)
        ind[key] = last(result[key])

    # --------------------------------------------------
    # ATR 14
    # --------------------------------------------------

    ranges = [
        max(
            candles[i]["high"] - candles[i]["low"],
            abs(candles[i]["high"] - closes[i - 1]),
            abs(candles[i]["low"] - closes[i - 1])
        )
        for i in range(1, n)
    ]

    result["atr14"] = series([
        None
    ] + wilder(ranges, 14))

    ind["atr14"] = last(result["atr14"])

    # --------------------------------------------------
    # VWAP - ACTUAL SESSION VOLUME ONLY
    # --------------------------------------------------

    vwap = []
    cumv = 0.0
    cump = 0.0
    current_day = None

    if (
        has_volume_data
        and full["timeframe"] not in ("1D", "W")
    ):
        for c in candles:
            day = datetime.fromtimestamp(
                c["time"], IST
            ).date()

            if current_day != day:
                cumv = 0.0
                cump = 0.0
                current_day = day

            volume = float(c.get("volume", 0) or 0)

            if volume <= 0:
                continue

            typical_price = (
                c["high"] + c["low"] + c["close"]
            ) / 3

            cumv += volume
            cump += typical_price * volume

            vwap.append({
                "time": c["time"],
                "value": round(cump / cumv, 5)
            })

    result["vwap"] = vwap
    ind["vwap"] = (
        last(vwap)
        if vwap and vwap[-1]["time"] == candles[-1]["time"]
        else None
    )

    # --------------------------------------------------
    # VOLUME
    # --------------------------------------------------

    result["volume"] = (
        [
            {
                "time": c["time"],
                "value": volumes[i],
                "color": (
                    "#00b89580"
                    if c["close"] >= c["open"]
                    else "#ff456680"
                )
            }
            for i, c in enumerate(candles)
        ]
        if volume_supported
        else []
    )

    ind["volume"] = (
        volumes[-1]
        if volume_supported and volumes
        else None
    )

    # --------------------------------------------------
    # MFI 14 - MONEY FLOW INDEX
    #
    # Typical Price = (High + Low + Close) / 3
    # Raw Money Flow = Typical Price × Actual Volume
    # --------------------------------------------------

    mfi_values = [None] * n

    if has_volume_data and n > 14:

        typical_prices = [
            (
                c["high"] + c["low"] + c["close"]
            ) / 3
            for c in candles
        ]

        positive_flow = [0.0] * n
        negative_flow = [0.0] * n

        for i in range(1, n):
            raw_money_flow = (
                typical_prices[i] * volumes[i]
            )

            if typical_prices[i] > typical_prices[i - 1]:
                positive_flow[i] = raw_money_flow

            elif typical_prices[i] < typical_prices[i - 1]:
                negative_flow[i] = raw_money_flow

        for i in range(14, n):

            start = i - 14 + 1

            positive_sum = sum(
                positive_flow[start:i + 1]
            )

            negative_sum = sum(
                negative_flow[start:i + 1]
            )

            if positive_sum == 0 and negative_sum == 0:
                mfi_values[i] = 50.0

            elif negative_sum == 0:
                mfi_values[i] = 100.0

            elif positive_sum == 0:
                mfi_values[i] = 0.0

            else:
                money_ratio = (
                    positive_sum / negative_sum
                )

                mfi_values[i] = (
                    100 - 100 / (1 + money_ratio)
                )

    result["mfi14"] = series(mfi_values)
    ind["mfi14"] = last(result["mfi14"])

    # --------------------------------------------------
    # PVT - PRICE VOLUME TREND
    #
    # PVT = Previous PVT +
    #       ((Close - Previous Close) / Previous Close)
    #       × Actual Volume
    #
    # Initial baseline is zero.
    # --------------------------------------------------

    pvt_values = [None] * n

    if has_volume_data and n:

        running_pvt = 0.0
        pvt_values[0] = 0.0

        for i in range(1, n):

            previous_close = closes[i - 1]

            if previous_close <= 0:
                pvt_values[i] = None
                continue

            price_change_ratio = (
                closes[i] - previous_close
            ) / previous_close

            running_pvt += (
                price_change_ratio * volumes[i]
            )

            pvt_values[i] = running_pvt

    result["pvt"] = series(pvt_values)
    ind["pvt"] = last(result["pvt"])

    # --------------------------------------------------
    # PVT EMA 9 - SIGNAL LINE
    #
    # Calculated only from actual PVT values derived from
    # actual traded volume. No synthetic volume is used.
    # --------------------------------------------------

    pvt_signal_line_values = [None] * n

    valid_pvt_values = (
        has_volume_data
        and n >= 9
        and all(
            value is not None
            and isinstance(value, (int, float))
            and math.isfinite(value)
            for value in pvt_values
        )
    )

    if valid_pvt_values:
        pvt_ema9 = ema(
            [float(value) for value in pvt_values],
            9
        )

        pvt_signal_line_values = [
            pvt_ema9[i] if i >= 8 else None
            for i in range(n)
        ]

    result["pvt_signal_line"] = series(
        pvt_signal_line_values
    )

    ind["pvt_signal_line"] = last(
        result["pvt_signal_line"]
    )

    # PVT above EMA9 = BUY
    # PVT below EMA9 = SELL
    # Equal values = NEUTRAL
    # Missing actual volume/history = UNAVAILABLE

    if (
        ind["pvt"] is not None
        and ind["pvt_signal_line"] is not None
    ):
        if ind["pvt"] > ind["pvt_signal_line"]:
            ind["pvt_signal"] = "BUY"

        elif ind["pvt"] < ind["pvt_signal_line"]:
            ind["pvt_signal"] = "SELL"

        else:
            ind["pvt_signal"] = "NEUTRAL"

    else:
        ind["pvt_signal"] = "UNAVAILABLE"

    # --------------------------------------------------
    # DATA AVAILABILITY
    # --------------------------------------------------

    result["volume_supported"] = volume_supported
    result["volume_data_available"] = has_volume_data

    if not volume_supported:
        volume_note = (
            "This instrument has no traded volume. "
            "Select a futures contract for Volume, VWAP, MFI and PVT."
        )

    elif not has_volume_data:
        volume_note = (
            "Kite supports traded volume for this instrument, "
            "but positive volume data is not present in these candles."
        )

    else:
        volume_note = (
            "Actual Kite contract traded volume is being used."
        )

    result["vwap_note"] = (
        "Actual session VWAP (typical price × traded volume)"
        if has_volume_data and full["timeframe"] not in ("1D", "W")
        else "Session VWAP is unavailable on daily/weekly bars."
        if has_volume_data
        else volume_note
    )

    result["mfi_note"] = (
        "MFI 14 calculated from actual traded volume."
        if has_volume_data
        else volume_note
    )

    result["pvt_note"] = (
        "PVT and PVT EMA9 calculated from actual traded volume."
        if has_volume_data and ind["pvt_signal_line"] is not None
        else volume_note
    )

    result["indicator_method"] = (
        "EMA seeded from first history close; "
        "MA8 simple moving average; "
        "WMA8 weighted moving average; "
        "RSI/ATR Wilder smoothing; "
        "MACD 12/26/9; "
        "Bollinger20 ±2 population SD; "
        "VWAP uses session typical price × actual volume; "
        "MFI uses 14-period positive/negative money flow; "
        "PVT uses close-to-close percentage change × actual volume; "
        "PVT signal uses EMA9 of PVT. "
        "Values include latest provider candle, which may be forming."
    )

    result["indicators"] = ind

    return result
