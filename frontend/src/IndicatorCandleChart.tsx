
import { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  LineStyle
} from "lightweight-charts";

import type {
  Time,
  UTCTimestamp,
  LogicalRange,
  ISeriesApi
} from "lightweight-charts";

import { apiUrl } from "./config/api";
import { sessionData } from "./marketSession";
import { attachChartScrollbar } from "./chartScrollbar.js";
import "./IndicatorCandleChart.css";

export interface ChartStats {
  ltp: number;
  change: number | null;
  change_pct: number | null;
  ema9: number | null;
  ema21: number | null;
  vwap: number | null;
  rsi14: number | null;
  mfi14?: number | null;
  pvt?: number | null;

  // Previous PVT values for real crossover detection.
  pvt_previous?: number | null;
  pvt_signal_line?: number | null;
  pvt_signal_line_previous?: number | null;

  // Separate 15-minute trend values.
  trend15_ema9?: number | null;
  trend15_ema21?: number | null;

  macd: string;
  ma8: number | null;
  wma8: number | null;

  [key: string]: number | string | null | undefined;
}

interface Point {
  time: number;
  value: number;
  color?: string;
}

interface IndicatorCandleChartProps {
  symbol?: string;
  timeframe: string;
  expiry?: string;
  atmStrike?: number | null;
  availableStrikes?: number[];
  selectedStrike?: number | null;
  onStrikeChange?: (strike: number) => void;
  optionType?: "CE" | "PE";
  onOptionTypeChange?: (type: "CE" | "PE") => void;
  onIndicatorsUpdate: (ind: ChartStats | null) => void;
  onStatusUpdate: (message: string) => void;
}

const overlays = [
  "MA8",
  "WMA8",
  "EMA9",
  "EMA21",
  "EMA50",
  "EMA200",
  "Bollinger",
  "VWAP",
  "RSI",
  "MACD",
  "ATR",
  "MFI",
  "PVT",
  "Volume"
];

const fields: Record<string, string> = {
  MA8: "ma8",
  WMA8: "wma8",
  EMA9: "ema9",
  EMA21: "ema21",
  EMA50: "ema50",
  EMA200: "ema200",
  VWAP: "vwap",
  RSI: "rsi14",
  ATR: "atr14",
  MFI: "mfi14",
  PVT: "pvt",
  Volume: "volume"
};

const colors: Record<string, string> = {
  ma8: "#085740ff",
  wma8: "#b50842ff",
  ema9: "#00a6ff",
  ema21: "#f5b82e",
  ema50: "#da7dff",
  ema200: "#f58052",
  vwap: "#4a0cceff",
  bb_upper: "#3ada9dff",
  bb_middle: "#7db2d0ff",
  bb_lower: "#d1346eff",
  rsi14: "#9013f0ff",
  atr14: "#3e8ef0ff",
  macd_line: "#0e16fdff",
  macd_signal: "#f5a110ff",
  mfi14: "#e6a23c",
  pvt: "#19b7df",
  volume: "#19e6d2ff"
};

const normalizeTimeframe = (value: string) => {
  const normalized = value.toLowerCase();

  if (normalized === "1hour" || normalized === "1h") {
    return "1H";
  }

  if (normalized === "1d") {
    return "1D";
  }

  if (normalized === "1w" || normalized === "w") {
    return "W";
  }

  return normalized;
};

const getNumber = (value: unknown): number | null => {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value)
  ) {
    return null;
  }

  return value;
};

// Read MA8/WMA8 from the exact data points plotted by the chart,
// matching the timestamp of the latest candle.
const getIndicatorValueAtTime = (
  points: unknown,
  candleTime: number
): number | null => {
  if (!Array.isArray(points)) return null;

  const matchingPoint = [...points].reverse().find(
    (point): point is Point =>
      point !== null &&
      typeof point === "object" &&
      Number(point.time) === candleTime &&
      typeof point.value === "number" &&
      Number.isFinite(point.value)
  );

  return matchingPoint ? matchingPoint.value : null;
};

const getLastTwoValues = (
  points: unknown
): { previous: number | null; current: number | null } => {
  if (!Array.isArray(points)) {
    return {
      previous: null,
      current: null
    };
  }

  const validPoints = points.filter(
    (point): point is { time: number; value: number } =>
      point !== null &&
      typeof point === "object" &&
      typeof (point as Point).time === "number" &&
      typeof (point as Point).value === "number" &&
      Number.isFinite((point as Point).value)
  );

  if (validPoints.length < 2) {
    return {
      previous: null,
      current:
        validPoints.length === 1
          ? validPoints[0].value
          : null
    };
  }

  return {
    previous: validPoints[validPoints.length - 2].value,
    current: validPoints[validPoints.length - 1].value
  };
};

export default function IndicatorCandleChart({
  symbol = "NIFTY",
  timeframe,
  expiry = "",
  atmStrike = null,
  availableStrikes = [],
  selectedStrike = null,
  onStrikeChange,
  optionType = "CE",
  onOptionTypeChange,
  onIndicatorsUpdate,
  onStatusUpdate
}: IndicatorCandleChartProps) {
  const host = useRef<HTMLDivElement>(null);
  const scrollHost = useRef<HTMLDivElement>(null);
  const range = useRef<LogicalRange | null>(null);
  const chartKey = useRef("");

  const marketSymbol = symbol.toUpperCase();

  const [instrument, setInstrument] = useState(
    marketSymbol === "NIFTY" ? "NIFTY_FUT" : marketSymbol
  );

  const effectiveInstrument =
    instrument === "NIFTY_FUT" && marketSymbol === "NIFTY"
      ? "NIFTY_FUT"
      : marketSymbol;

  const [selectedTimeframe, setSelectedTimeframe] = useState(
    normalizeTimeframe(timeframe || "15m")
  );

  const [enabled, setEnabled] = useState([
    "MA8",
    "WMA8",
    "MACD",
    "VWAP",
    "Volume",
    "MFI",
    "PVT"
  ]);

  const [feed, setFeed] = useState<{
    status: string;
    quoteTime: number | null;
    key: string;
    warmup: number;
    closed: boolean;
  } | null>(null);

  const [now, setNow] = useState(Date.now());
  const [stats, setStats] = useState<ChartStats | null>(null);

  const panes = enabled.filter(s =>
    ["RSI", "MACD", "ATR", "MFI", "PVT", "Volume"].includes(s)
  ).length;

  const validStrikes = availableStrikes
    .filter((strike): strike is number =>
      typeof strike === "number" && Number.isFinite(strike)
    )
    .sort((a, b) => a - b);

  const chartStrike =
    selectedStrike ??
    (atmStrike != null && validStrikes.includes(atmStrike)
      ? atmStrike
      : null);

  const isOptionChart = chartStrike !== null;

  useEffect(() => {
    setInstrument(
      marketSymbol === "NIFTY" ? "NIFTY_FUT" : marketSymbol
    );

    range.current = null;
  }, [marketSymbol]);

  useEffect(() => {
    setSelectedTimeframe(
      normalizeTimeframe(timeframe || "15m")
    );
  }, [timeframe]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  // Reset chart data when the selected contract changes.
  useEffect(() => {
    range.current = null;
    setStats(null);
    setFeed(null);
    onIndicatorsUpdate(null);
  }, [
    marketSymbol,
    expiry,
    chartStrike,
    optionType,
    onIndicatorsUpdate
  ]);

  useEffect(() => {
    if (!host.current || !scrollHost.current) return;

    const key = [
      effectiveInstrument,
      selectedTimeframe,
      expiry,
      chartStrike ?? "",
      optionType
    ].join(":");

    if (chartKey.current !== key) {
      range.current = null;
      chartKey.current = key;
    }

    const chart = createChart(host.current, {
      autoSize: true,

      layout: {
        background: {
          type: ColorType.Solid,
          color: "#06121e"
        },
        textColor: "#9cb0c6",
        fontSize: 10
      },

      grid: {
        vertLines: { color: "#12283a" },
        horzLines: { color: "#12283a" }
      },

      rightPriceScale: {
        borderColor: "#1b3447"
      },

      timeScale: {
        timeVisible: true,
        borderColor: "#1b3447",

        tickMarkFormatter: (t: Time) =>
          new Date(Number(t) * 1000).toLocaleTimeString(
            "en-IN",
            {
              timeZone: "Asia/Kolkata",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false
            }
          )
      },

      localization: {
        timeFormatter: (t: Time) =>
          new Date(Number(t) * 1000).toLocaleString(
            "en-IN",
            { timeZone: "Asia/Kolkata" }
          )
      }
    });

    const candles = chart.addSeries(
      CandlestickSeries,
      {
        upColor: "#00d6a3",
        downColor: "#ff4566",
        wickUpColor: "#00d6a3",
        wickDownColor: "#ff4566",
        borderVisible: false,
        priceLineVisible: false
      }
    );

    let quoteLine:
      ReturnType<typeof candles.createPriceLine> | undefined;

    const lines: Record<string, ISeriesApi<"Line">> = {};

    const addLine = (key: string, pane = 0) => {
      const series = chart.addSeries(
        LineSeries,
        {
          title: key.toUpperCase(),
          color: colors[key] || "#aabbcc",
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: true
        },
        pane
      );

      lines[key] = series;
      return series;
    };

    // MA8 and WMA8.
    for (const name of ["MA8", "WMA8"]) {
      if (enabled.includes(name)) {
        addLine(fields[name]);
      }
    }

    // EMA and VWAP overlays.
    for (const name of [
      "EMA9",
      "EMA21",
      "EMA50",
      "EMA200",
      "VWAP"
    ]) {
      if (enabled.includes(name)) {
        addLine(fields[name]);
      }
    }

    // Bollinger bands.
    if (enabled.includes("Bollinger")) {
      for (const key of [
        "bb_upper",
        "bb_middle",
        "bb_lower"
      ]) {
        addLine(key);
      }
    }

    let pane = 1;

    // RSI.
    if (enabled.includes("RSI")) {
      const rsi = addLine("rsi14", pane++);

      for (const level of [30, 50, 70]) {
        rsi.createPriceLine({
          price: level,
          color: level === 50 ? "#566778" : "#9970bb",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: String(level)
        });
      }

      rsi.applyOptions({
        autoscaleInfoProvider: () => ({
          priceRange: {
            minValue: 0,
            maxValue: 100
          }
        })
      });
    }

    // MACD.
    let macdHistogram: ISeriesApi<"Histogram"> | undefined;

    if (enabled.includes("MACD")) {
      addLine("macd_line", pane);
      addLine("macd_signal", pane);

      macdHistogram = chart.addSeries(
        HistogramSeries,
        {
          title: "MACD histogram",
          priceLineVisible: false
        },
        pane++
      );
    }

    // ATR.
    if (enabled.includes("ATR")) {
      addLine("atr14", pane++);
    }

    // MFI.
    if (enabled.includes("MFI")) {
      const mfi = addLine("mfi14", pane++);

      for (const level of [20, 50, 80]) {
        mfi.createPriceLine({
          price: level,
          color: level === 50 ? "#566778" : "#b58a42",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: String(level)
        });
      }

      mfi.applyOptions({
        autoscaleInfoProvider: () => ({
          priceRange: {
            minValue: 0,
            maxValue: 100
          }
        })
      });
    }

    // PVT.
    if (enabled.includes("PVT")) {
      addLine("pvt", pane++);
    }

    // Volume.
    const volume = enabled.includes("Volume")
      ? chart.addSeries(
        HistogramSeries,
        {
          title: "Volume",
          priceFormat: { type: "volume" },
          priceLineVisible: false,
          lastValueVisible: true
        },
        pane++
      )
      : undefined;

    chart.panes().forEach((p, i) => {
      p.setHeight(i === 0 ? 280 : 110);
    });

    const scroll = attachChartScrollbar(
      chart,
      scrollHost.current
    );

    let active = true;
    let loaded = false;

    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    setStats(null);
    setFeed(null);
    onIndicatorsUpdate(null);

    const contractLabel = isOptionChart
      ? `${marketSymbol} ${expiry} ${chartStrike} ${optionType}`
      : effectiveInstrument;

    onStatusUpdate(
      `Loading ${contractLabel} Kite candles and indicators…`
    );

    const load = async () => {
      controller = new AbortController();
      const currentController = controller;

      const timeout = setTimeout(
        () => currentController.abort(),
        15000
      );

      try {
        // Build request for the selected instrument.
        const params = new URLSearchParams({
          symbol: isOptionChart ? marketSymbol : effectiveInstrument,
          timeframe: selectedTimeframe,
          count: "1000",
          session: "true"
        });

        let endpoint = "/api/chart/candles";

        if (isOptionChart) {
          if (!expiry) {
            throw new Error("Select an option expiry first.");
          }

          endpoint = "/api/chart/option-candles";

          params.set("expiry", expiry);
          params.set("strike", String(chartStrike));
          params.set("option_type", optionType);
        }

        const response = await fetch(
          apiUrl(`${endpoint}?${params.toString()}`),
          { signal: currentController.signal }
        );

        const data = await response.json();

        if (!response.ok) {
          throw new Error(
            typeof data.detail === "string"
              ? data.detail
              : "Chart unavailable"
          );
        }

        if (
          data.source !== "kite" ||
          !Array.isArray(data.candles) ||
          data.candles.length === 0
        ) {
          throw new Error("Actual Kite candles required");
        }

        // Verify returned underlying.
        if (
          data.symbol &&
          String(data.symbol).toUpperCase() !==
          (isOptionChart
            ? marketSymbol
            : effectiveInstrument).toUpperCase()
        ) {
          throw new Error(
            `Received ${data.symbol} data while ${contractLabel} is selected.`
          );
        }

        // Verify exact returned option contract.
        if (isOptionChart) {
          const returnedStrike =
            Number(data.option_contract?.strike ?? data.selected_strike);

          const returnedType =
            String(
              data.option_contract?.option_type ??
              data.selected_option_type ??
              ""
            ).toUpperCase();

          if (
            returnedStrike !== chartStrike ||
            returnedType !== optionType
          ) {
            throw new Error(
              `Backend returned a different option contract. Expected ${chartStrike} ${optionType}.`
            );
          }
        }

        if (!active) return;

        const quoteStatus = data.quote_status || data.status;

        setFeed({
          status: quoteStatus,
          quoteTime: data.quote_time ?? null,
          key: data.quote_key || data.instrument,
          warmup: data.warmup_bars || 0,
          closed: !!data.last_candle_closed
        });

        // Live Kite LTP line.
        if (typeof data.indicators?.ltp === "number") {
          const options = {
            price: data.indicators.ltp,
            title:
              quoteStatus === "fresh"
                ? "Kite LTP"
                : "STALE / UNVERIFIED LTP",
            color:
              quoteStatus === "fresh"
                ? "#00d6a3"
                : "#8fa1b2",
            axisLabelVisible: true
          };

          if (quoteLine) {
            quoteLine.applyOptions(options);
          } else {
            quoteLine = candles.createPriceLine(options);
          }
        }

        const withSession = (points: Point[]) => {
          const typed = (points || []).map(p => ({
            ...p,
            time: p.time as UTCTimestamp
          }));

          return data.session
            ? sessionData(typed, data.session)
            : typed;
        };

        const bars = data.candles.map(
          (c: {
            time: number;
            open: number;
            high: number;
            low: number;
            close: number;
          }) => ({
            ...c,
            time: c.time as UTCTimestamp
          })
        );

        candles.setData(
          data.session
            ? sessionData(bars, data.session)
            : bars
        );

        // Indicator lines.
        for (const [lineKey, series] of Object.entries(lines)) {
          series.setData(
            withSession(data[lineKey] || [])
          );
        }

        // MACD histogram.
        macdHistogram?.setData(
          withSession(
            (data.macd_histogram || []).map((p: Point) => ({
              ...p,
              color: p.value >= 0 ? "#00b895" : "#ff4566"
            }))
          )
        );

        // Volume histogram.
        volume?.setData(
          withSession(
            (data.volume || []).map((p: Point) => ({
              ...p,
              color: p.color || "#26a69a"
            }))
          )
        );

        const total = data.session
          ? Math.floor(
            (data.session.close - data.session.open) / 60
          ) + 1
          : bars.length;

        scroll.setExtent(total);

        if (!loaded) {
          if (range.current) {
            chart.timeScale().setVisibleLogicalRange(range.current);
          } else {
            scroll.showWindow(
              data.session
                ? Math.floor(
                  (
                    bars[bars.length - 1].time -
                    data.session.open
                  ) / 60
                )
                : total - 1,
              60
            );
          }

          loaded = true;
        }

        // --------------------------------------------------
        // PVT PREVIOUS VALUES
        // Extract the last two actual PVT and PVT EMA9 points.
        // --------------------------------------------------

        const pvtPoints = getLastTwoValues(data.pvt);
        const pvtSignalPoints = getLastTwoValues(
          data.pvt_signal_line
        );

        const pvtPrevious =
          getNumber(data.indicators?.pvt_previous) ??
          pvtPoints.previous;

        const pvtSignalLinePrevious =
          getNumber(data.indicators?.pvt_signal_line_previous) ??
          pvtSignalPoints.previous;

        // --------------------------------------------------
        // SEPARATE 15-MINUTE TREND
        // Use the selected chart response if it is already 15m.
        // Otherwise fetch the same contract at 15m.
        // --------------------------------------------------

        let trend15Ema9: number | null = null;
        let trend15Ema21: number | null = null;

        if (selectedTimeframe.toLowerCase() === "15m") {
          trend15Ema9 = getNumber(data.indicators?.ema9);
          trend15Ema21 = getNumber(data.indicators?.ema21);
        } else {
          try {
            const trendParams = new URLSearchParams(params);
            trendParams.set("timeframe", "15m");

            const trendResponse = await fetch(
              apiUrl(`${endpoint}?${trendParams.toString()}`),
              { signal: currentController.signal }
            );

            if (trendResponse.ok) {
              const trendData = await trendResponse.json();

              const validTrendResponse =
                trendData.source === "kite" &&
                Array.isArray(trendData.candles) &&
                trendData.candles.length > 0;

              const sameUnderlying =
                !trendData.symbol ||
                String(trendData.symbol).toUpperCase() ===
                (isOptionChart
                  ? marketSymbol
                  : effectiveInstrument).toUpperCase();

              let sameOptionContract = true;

              if (isOptionChart) {
                const trendStrike = Number(
                  trendData.option_contract?.strike ??
                  trendData.selected_strike
                );

                const trendType = String(
                  trendData.option_contract?.option_type ??
                  trendData.selected_option_type ??
                  ""
                ).toUpperCase();

                sameOptionContract =
                  trendStrike === chartStrike &&
                  trendType === optionType;
              }

              if (
                validTrendResponse &&
                sameUnderlying &&
                sameOptionContract
              ) {
                trend15Ema9 = getNumber(
                  trendData.indicators?.ema9
                );

                trend15Ema21 = getNumber(
                  trendData.indicators?.ema21
                );
              }
            }
          } catch (trendError) {
            // The main chart remains usable if the separate
            // 15-minute request is unavailable.
            if (
              trendError instanceof Error &&
              trendError.name === "AbortError"
            ) {
              throw trendError;
            }

            trend15Ema9 = null;
            trend15Ema21 = null;
          }
        }

        if (!active) return;

        // Read the exact MA8/WMA8 points drawn on the chart and match
        // them to the latest candle timestamp. No separate calculation
        // or LTP value is used for the signal.
        const latestCandleTime = Number(
          bars[bars.length - 1]?.time
        );

        const chartMa8 = getIndicatorValueAtTime(
          data.ma8,
          latestCandleTime
        );

        const chartWma8 = getIndicatorValueAtTime(
          data.wma8,
          latestCandleTime
        );

        const value: ChartStats = {
          ...data.indicators,

          // These are exactly the values plotted by the chart overlays.
          ma8: chartMa8,
          wma8: chartWma8,

          instrument: data.instrument,

          // Previous PVT values for true crossover checks.
          pvt_previous: pvtPrevious,
          pvt_signal_line_previous: pvtSignalLinePrevious,

          // Current PVT EMA9 value.
          pvt_signal_line:
            getNumber(data.indicators?.pvt_signal_line) ??
            pvtSignalPoints.current,

          // Separate actual 15-minute EMA trend.
          trend15_ema9: trend15Ema9,
          trend15_ema21: trend15Ema21
        };

        setStats(value);
        onIndicatorsUpdate(value);

        onStatusUpdate(
          `${quoteStatus === "fresh" ? "Kite data" : "STALE Kite data"} · ${quoteStatus} · ${data.instrument} · ${bars.length} bars · last candle ${new Date(
            Number(bars[bars.length - 1].time) * 1000
          ).toLocaleString("en-IN", {
            timeZone: "Asia/Kolkata"
          })} IST · refresh 3s`
        );

      } catch (e) {
        if (active) {
          setStats(null);
          setFeed(null);

          quoteLine?.applyOptions({
            title: "STALE LTP",
            color: "#8fa1b2"
          });

          onIndicatorsUpdate(null);

          onStatusUpdate(
            `UNAVAILABLE / STALE · ${e instanceof Error ? e.message : "Chart failed"
            }`
          );
        }

      } finally {
        clearTimeout(timeout);

        if (active) {
          timer = setTimeout(load, 3000);
        }
      }
    };

    void load();

    return () => {
      active = false;

      range.current =
        chart.timeScale().getVisibleLogicalRange();

      clearTimeout(timer);
      controller?.abort();

      scroll.destroy();
      chart.remove();
    };
  }, [
    selectedTimeframe,
    effectiveInstrument,
    enabled,
    expiry,
    chartStrike,
    optionType,
    marketSymbol,
    isOptionChart,
    onIndicatorsUpdate,
    onStatusUpdate
  ]);

  const display = (key: string) =>
    typeof stats?.[key] === "number"
      ? (stats[key] as number).toFixed(2)
      : "—";

  const isFresh =
    feed?.status === "fresh" &&
    feed.quoteTime != null &&
    now / 1000 - feed.quoteTime <= 90;

  return (
    <>
      <div className="candle-indicator-controls">

        {/* Instrument selector remains unchanged. */}
        <select
          aria-label="Chart instrument"
          value={effectiveInstrument}
          onChange={e => {
            range.current = null;
            setInstrument(e.target.value);
          }}
        >
          <option value={marketSymbol}>
            {marketSymbol} · spot
          </option>

          {marketSymbol === "NIFTY" && (
            <option value="NIFTY_FUT">
              NIFTY · front futures
            </option>
          )}
        </select>

        {/* Strike selector. */}
        <select
          aria-label="Option strike price"
          value={chartStrike ?? ""}
          onChange={e => {
            const value = Number(e.target.value);

            if (Number.isFinite(value) && onStrikeChange) {
              range.current = null;
              onStrikeChange(value);
            }
          }}
          disabled={!validStrikes.length || !onStrikeChange}
        >
          {validStrikes.length ? (
            validStrikes.map(strike => (
              <option key={strike} value={strike}>
                {strike}
                {strike === atmStrike ? " · ATM" : ""}
              </option>
            ))
          ) : (
            <option value="">
              Waiting for strikes…
            </option>
          )}
        </select>

        {/* Option type selector. */}
        <select
          aria-label="Option type"
          value={optionType}
          onChange={e => {
            onOptionTypeChange?.(
              e.target.value as "CE" | "PE"
            );
          }}
        >
          <option value="CE">CE</option>
          <option value="PE">PE</option>
        </select>

        {/* Indicator visibility. */}
        <details>
          <summary>Indicators</summary>

          <div className="candle-indicator-menu">
            {overlays.map(name => (
              <label key={name}>
                <input
                  type="checkbox"
                  checked={enabled.includes(name)}
                  onChange={() =>
                    setEnabled(v =>
                      v.includes(name)
                        ? v.filter(n => n !== name)
                        : [...v, name]
                    )
                  }
                />

                <span
                  style={{
                    color:
                      name === "MA8"
                        ? colors.ma8
                        : name === "WMA8"
                          ? colors.wma8
                          : name === "MFI"
                            ? colors.mfi14
                            : name === "PVT"
                              ? colors.pvt
                              : undefined
                  }}
                >
                  {name}
                </span>
              </label>
            ))}
          </div>
        </details>
      </div>

      {/* Kite feed status. */}
      <div
        className="oi-caption"
        role="status"
        style={{
          color: isFresh ? "#00d6a3" : "#ffbb55"
        }}
      >
        {feed ? (
          <>
            KITE API · {feed.key} · {selectedTimeframe} ·{" "}
            {isFresh ? "FRESH SNAPSHOT" : "STALE / UNVERIFIED"}

            <br />

            Quote:{" "}
            {feed.quoteTime
              ? new Date(feed.quoteTime * 1000).toLocaleString(
                "en-IN",
                { timeZone: "Asia/Kolkata" }
              )
              : "Timestamp missing"
            } IST · {feed.warmup} warm-up bars · Latest candle{" "}
            {feed.closed ? "closed" : "forming"}
          </>
        ) : (
          "Waiting for verified Kite response…"
        )}
      </div>

      {/* Main chart. */}
      <div
        className="indicator-candle-host"
        ref={host}
        style={{
          height: 300 + panes * 110
        }}
      />

      {/* Horizontal chart scrollbar. */}
      <div
        className="chart-horizontal-scroll"
        ref={scrollHost}
        tabIndex={0}
        aria-label="Scroll candles and all indicator panes"
      />

      {/* Indicator values. */}
      <div className="candle-indicator-values">
        {[
          "ltp",
          "ma8",
          "wma8",
          "ema9",
          "ema21",
          "ema50",
          "ema200",
          "vwap",
          "rsi14",
          "macd_value",
          "macd_signal",
          "macd_histogram",
          "mfi14",
          "pvt",
          "atr14",
          "bb_upper",
          "bb_middle",
          "bb_lower",
          "volume"
        ].map(key => (
          <span key={key}>
            {key.replaceAll("_", " ").toUpperCase()}{" "}
            <b
              style={{
                color: colors[key] || "#d4e0eb"
              }}
            >
              {display(key)}
            </b>
          </span>
        ))}
      </div>
    </>
  );
}
