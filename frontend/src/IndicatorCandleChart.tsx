
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
  macd: string;
  ma8: number | null;
  wma8: number | null;
  [key: string]: number | string | null;
}

interface Point {
  time: number;
  value: number;
  color?: string;
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
  "Volume"
];

const timeframeOptions = [
  { label: "1 Minute", value: "1m" },
  { label: "3 Minutes", value: "3m" },
  { label: "5 Minutes", value: "5m" },
  { label: "15 Minutes", value: "15m" },
  { label: "1 Hour", value: "1H" },
  { label: "1 Day", value: "1D" }
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
  Volume: "volume"
};

const colors: Record<string, string> = {
  ma8: "#00e5a0",
  wma8: "#ff4fd8",
  ema9: "#00a6ff",
  ema21: "#f5b82e",
  ema50: "#da7dff",
  ema200: "#f58052",
  vwap: "#e8ddff",
  bb_upper: "#7ca5bc",
  bb_middle: "#7ca5bc",
  bb_lower: "#7ca5bc",
  rsi14: "#c477ff",
  atr14: "#ffb765",
  macd_line: "#00b6ff",
  macd_signal: "#ffbb44",
  volume: "#26a69a"
};

const normalizeTimeframe = (value: string) => {
  const normalized = value.toLowerCase();

  if (normalized === "1hour" || normalized === "1h") return "1H";
  if (normalized === "1d") return "1D";

  return normalized;
};

export default function IndicatorCandleChart({
  symbol = "NIFTY",
  timeframe,
  onIndicatorsUpdate,
  onStatusUpdate
}: {
  symbol?: string;
  timeframe: string;
  onIndicatorsUpdate: (ind: ChartStats | null) => void;
  onStatusUpdate: (message: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const scrollHost = useRef<HTMLDivElement>(null);
  const range = useRef<LogicalRange | null>(null);
  const chartKey = useRef("");

  // This selector remains unchanged.
  // NIFTY_FUT is retained as the optional NIFTY futures selection.
  const [instrument, setInstrument] = useState("NIFTY");

  // Use the selected Option Chain market for the spot chart.
  const effectiveInstrument =
    instrument === "NIFTY_FUT" && symbol.toUpperCase() === "NIFTY"
      ? "NIFTY_FUT"
      : symbol.toUpperCase();

  const [selectedTimeframe, setSelectedTimeframe] = useState(
    normalizeTimeframe(timeframe || "1m")
  );

  const [enabled, setEnabled] = useState([
    "MA8",
    "WMA8",
    "EMA9",
    "EMA21",
    "RSI",
    "MACD",
    "Volume"
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
  const [note, setNote] = useState("");

  // Keep timeframe synchronized if parent changes it.
  useEffect(() => {
    setSelectedTimeframe(normalizeTimeframe(timeframe || "1m"));
  }, [timeframe]);

  // Update quote freshness display every second.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const panes = enabled.filter(s =>
    ["RSI", "MACD", "ATR", "Volume"].includes(s)
  ).length;

  useEffect(() => {
    if (!host.current || !scrollHost.current) return;

    const key = `${effectiveInstrument}:${selectedTimeframe}`;

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

    // MA8 and WMA8: lines only, no trading signal.
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

    // Bollinger Bands.
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

    // RSI pane.
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

    // MACD pane.
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

    // ATR pane.
    if (enabled.includes("ATR")) {
      addLine("atr14", pane++);
    }

    // Volume pane.
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
    setNote("");
    onIndicatorsUpdate(null);

    onStatusUpdate("Loading Kite candles and indicators…");

    const load = async () => {
      controller = new AbortController();

      const currentController = controller;

      const timeout = setTimeout(
        () => currentController.abort(),
        15000
      );

      try {
        const params = new URLSearchParams({
          symbol: effectiveInstrument,
          timeframe: selectedTimeframe,
          count: "1000",
          session: "true"
        });

        const response = await fetch(
          apiUrl(`/api/chart/candles?${params.toString()}`),
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
          !data.candles?.length
        ) {
          throw new Error("Actual Kite candles required");
        }

        // Do not display another market's response.
        if (
          data.instrument &&
          String(data.instrument).toUpperCase() !==
          effectiveInstrument.toUpperCase()
        ) {
          throw new Error(
            `Received ${data.instrument} data while ${effectiveInstrument} is selected.`
          );
        }

        if (!active) return;

        setFeed({
          status: data.status,
          quoteTime: data.quote_time ?? null,
          key: data.quote_key || data.instrument,
          warmup: data.warmup_bars || 0,
          closed: !!data.last_candle_closed
        });

        // Live LTP price line.
        if (typeof data.indicators?.ltp === "number") {
          const options = {
            price: data.indicators.ltp,
            title:
              data.quote_status === "fresh"
                ? "Kite LTP"
                : "STALE / UNVERIFIED LTP",
            color:
              data.quote_status === "fresh"
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

        // Update every visible indicator line.
        for (const [key, series] of Object.entries(lines)) {
          series.setData(withSession(data[key] || []));
        }

        // MACD histogram.
        macdHistogram?.setData(
          withSession(
            (data.macd_histogram || []).map(
              (p: Point) => ({
                ...p,
                color:
                  p.value >= 0
                    ? "#00b895"
                    : "#ff4566"
              })
            )
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
            chart.timeScale().setVisibleLogicalRange(
              range.current
            );
          } else {
            scroll.showWindow(
              data.session
                ? Math.floor(
                  (bars[bars.length - 1].time -
                    data.session.open) / 60
                )
                : total - 1,
              60
            );
          }

          loaded = true;
        }

        const value: ChartStats = {
          ...data.indicators,
          instrument: data.instrument
        };

        setStats(value);
        onIndicatorsUpdate(value);
        setNote(data.vwap_note || "");

        onStatusUpdate(
          `${data.status === "fresh" ? "Kite data" : "STALE Kite data"} · ${data.status} · ${data.instrument} · ${bars.length} bars · last candle ${new Date(Number(bars[bars.length - 1].time) * 1000).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST · refresh 3s`
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
            `UNAVAILABLE / STALE · ${e instanceof Error
              ? e.message
              : "Chart failed"
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

        {/* Instrument selector - existing design preserved */}
        <select
          aria-label="Chart instrument"
          value={instrument}
          onChange={e => {
            range.current = null;
            setInstrument(e.target.value);
          }}
        >
          <option value="NIFTY">NIFTY 50 · spot</option>
          <option value="NIFTY_FUT">NIFTY · front futures</option>
        </select>

        {/* Timeframe selector */}
        <select
          aria-label="Chart timeframe"
          value={selectedTimeframe}
          onChange={e => {
            range.current = null;
            setSelectedTimeframe(e.target.value);
          }}
        >
          {timeframeOptions.map(option => (
            <option
              key={option.value}
              value={option.value}
            >
              {option.label}
            </option>
          ))}
        </select>

        {/* Indicator visibility */}
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

      {/* Kite feed status */}
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
            {isFresh
              ? "FRESH SNAPSHOT"
              : "STALE / UNVERIFIED"}

            <br />

            Quote:{" "}
            {feed.quoteTime
              ? new Date(
                feed.quoteTime * 1000
              ).toLocaleString(
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

      {/* Main chart */}
      <div
        className="indicator-candle-host"
        ref={host}
        style={{
          height: 300 + panes * 110
        }}
      />

      {/* Horizontal chart scrollbar */}
      <div
        className="chart-horizontal-scroll"
        ref={scrollHost}
        tabIndex={0}
        aria-label="Scroll candles and all indicator panes"
      />

      {/* Indicator values */}
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

      <div className="oi-caption">
        {note} · Indicators are computed from Kite OHLCV data.
        Refresh interval: 3 seconds. MACD 12/26/9 · RSI/ATR 14 ·
        Bollinger 20,2 · MA8 simple moving average · WMA8 weighted
        moving average.
      </div>
    </>
  );
}
