
"""OHLCV-derived chart indicators; no synthetic prices or volume."""

from datetime import datetime, timezone, timedelta
import math

IST = timezone(timedelta(hours=5, minutes=30))


def ema(values, period):
    if not values:
        return []

    out = [values[0]]
    alpha = 2 / (period + 1)

    for v in values[1:]:
        out.append(out[-1] + alpha * (v - out[-1]))

    return out


def wilder(values, period):
    result = [None] * len(values)

    if len(values) < period:
        return result

    avg = sum(values[:period]) / period
    result[period - 1] = avg

    for i in range(period, len(values)):
        avg = (avg * (period - 1) + values[i]) / period
        result[i] = avg

    return result


def enrich(full, volume_supported=False):
    candles = full['candles']
    closes = [c['close'] for c in candles]
    n = len(candles)

    def series(values):
        return [
            {
                'time': c['time'],
                'value': round(v, 5)
            }
            for c, v in zip(candles, values)
            if v is not None and math.isfinite(v)
        ]

    def last(points):
        return points[-1]['value'] if points else None

    result = dict(full)
    ind = dict(full.get('indicators', {}))

    # --------------------------------------------------
    # EMA 9, 21, 50, 200
    # --------------------------------------------------

    for period in (9, 21, 50, 200):
        values = ema(closes, period)

        # Hide EMA until enough candles are available.
        result[f'ema{period}'] = series([
            v if i >= period - 1 else None
            for i, v in enumerate(values)
        ])

        ind[f'ema{period}'] = last(result[f'ema{period}'])

    # --------------------------------------------------
    # MA8 - Simple Moving Average
    # --------------------------------------------------

    ma8_values = [None] * n

    for i in range(7, n):
        window = closes[i - 7:i + 1]
        ma8_values[i] = sum(window) / 8

    result['ma8'] = series(ma8_values)
    ind['ma8'] = last(result['ma8'])

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

    result['wma8'] = series(wma8_values)
    ind['wma8'] = last(result['wma8'])

    # --------------------------------------------------
    # MA8 / WMA8 crossover signal
    # --------------------------------------------------

    ma_wma_signal = 'HOLD'

    valid_indices = [
        i for i in range(n)
        if ma8_values[i] is not None
        and wma8_values[i] is not None
    ]

    if len(valid_indices) >= 2:
        previous = valid_indices[-2]
        current = valid_indices[-1]

        previous_ma = ma8_values[previous]
        previous_wma = wma8_values[previous]

        current_ma = ma8_values[current]
        current_wma = wma8_values[current]

        # MA8 crosses above WMA8 = BUY
        if (
            previous_ma <= previous_wma
            and current_ma > current_wma
        ):
            ma_wma_signal = 'BUY'

        # MA8 crosses below WMA8 = SELL
        elif (
            previous_ma >= previous_wma
            and current_ma < current_wma
        ):
            ma_wma_signal = 'SELL'

    ind['ma_wma_signal'] = ma_wma_signal

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

    result['rsi14'] = series(rsi)
    ind['rsi14'] = last(result['rsi14'])

    # --------------------------------------------------
    # MACD 12 / 26 / 9
    # --------------------------------------------------

    
    # --------------------------------------------------
    # MACD 12 / 26 / 9
    # --------------------------------------------------

    fast = ema(closes, 12)
    slow = ema(closes, 26)

    # MACD line = EMA 12 - EMA 26
    macd = [
        f - s
        for f, s in zip(fast, slow)
    ]

    # Signal EMA must process the complete MACD series.
    # Do not start signal EMA only at index 25.
    sig = ema(macd, 9)

    # Hide MACD until the slow EMA has sufficient history.
    macd_values = [
        macd[i] if i >= 25 else None
        for i in range(n)
    ]

    # Hide signal until 9 MACD values are available
    # after the first valid slow EMA value.
    signal_values = [
        sig[i] if i >= 33 else None
        for i in range(n)
    ]

    histogram_values = [
        macd[i] - sig[i] if i >= 33 else None
        for i in range(n)
    ]

    result['macd_line'] = series(macd_values)

    result['macd_signal'] = series(signal_values)

    result['macd_histogram'] = series(histogram_values)

    ind['macd_value'] = last(result['macd_line'])

    ind['macd_signal'] = last(result['macd_signal'])

    ind['macd_histogram'] = last(result['macd_histogram'])

    ind['macd'] = (
        'Bullish'
        if ind['macd_histogram'] is not None
        and ind['macd_histogram'] > 0
        else 'Bearish'
        if ind['macd_histogram'] is not None
        and ind['macd_histogram'] < 0
        else 'Neutral'
        if ind['macd_histogram'] is not None
        else 'Unavailable'
    )


    # --------------------------------------------------
    # Bollinger Bands 20
    # --------------------------------------------------

    upper = []
    middle = []
    lower = []

    for i in range(n):
        values = closes[i - 19:i + 1] if i >= 19 else []

        mean = sum(values) / 20 if values else None

        sd = (
            math.sqrt(
                sum((p - mean) ** 2 for p in values) / 20
            )
            if values
            else None
        )

        middle.append(mean)
        upper.append(mean + 2 * sd if mean is not None else None)
        lower.append(mean - 2 * sd if mean is not None else None)

    for key, values in [
        ('bb_upper', upper),
        ('bb_middle', middle),
        ('bb_lower', lower)
    ]:
        result[key] = series(values)
        ind[key] = last(result[key])

    # --------------------------------------------------
    # ATR 14
    # --------------------------------------------------

    ranges = [
        max(
            candles[i]['high'] - candles[i]['low'],
            abs(candles[i]['high'] - closes[i - 1]),
            abs(candles[i]['low'] - closes[i - 1])
        )
        for i in range(1, n)
    ]

    result['atr14'] = series([
        None
    ] + wilder(ranges, 14))

    ind['atr14'] = last(result['atr14'])

    # --------------------------------------------------
    # VWAP
    # --------------------------------------------------

    vwap = []
    cumv = 0
    cump = 0
    day = None

    for c in candles:
        d = datetime.fromtimestamp(c['time'], IST).date()

        if day != d:
            cumv = 0
            cump = 0
            day = d

        vol = c.get('volume', 0)

        if (
            volume_supported
            and full['timeframe'] not in ('1D', 'W')
            and vol > 0
        ):
            cumv += vol

            cump += (
                (c['high'] + c['low'] + c['close']) / 3
            ) * vol

            vwap.append({
                'time': c['time'],
                'value': round(cump / cumv, 5)
            })

    result['vwap'] = vwap

    ind['vwap'] = (
        last(vwap)
        if vwap and vwap[-1]['time'] == candles[-1]['time']
        else None
    )

    # --------------------------------------------------
    # Volume
    # --------------------------------------------------

    result['volume'] = [
        dict(
            time=c['time'],
            value=c.get('volume', 0),
            color=(
                '#00b89580'
                if c['close'] >= c['open']
                else '#ff456680'
            )
        )
        for c in candles
    ] if volume_supported else []

    ind['volume'] = (
        candles[-1].get('volume', 0)
        if volume_supported and candles
        else None
    )

    result['volume_supported'] = volume_supported

    result['vwap_note'] = (
        'Actual futures session VWAP (typical price × volume)'
        if volume_supported and full['timeframe'] not in ('1D', 'W')
        else 'Session VWAP unavailable on daily/weekly bars'
        if volume_supported
        else 'NIFTY spot index has no traded volume; switch to NIFTY futures for VWAP/volume'
    )

    result['indicator_method'] = (
        'EMA seeded from first history close; '
        'MA8 simple moving average; '
        'WMA8 weighted moving average; '
        'RSI/ATR Wilder smoothing; '
        'MACD 12/26/9; '
        'Bollinger20 ±2 population SD. '
        'Values include latest provider candle, which may be forming.'
    )

    result['indicators'] = ind

    return result
