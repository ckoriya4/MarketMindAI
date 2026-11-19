
import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  LineSeries,
  type Time,
  type ISeriesApi,
  type UTCTimestamp
} from "lightweight-charts";
import { attachChartScrollbar } from "./chartScrollbar.js";

export interface CrudeChartPoint {
  time: number;
  value: number;
}

export default function CrudePriceChart({
  points,
  instrument,
  intraday,
  unavailable,
  followLatest = true
}: {
  points: CrudeChartPoint[];
  instrument: string;
  intraday: boolean;
  unavailable?: string;
  followLatest?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const scroll = useRef<HTMLDivElement>(null);

  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  const controller = useRef<ReturnType<typeof attachChartScrollbar> | null>(
    null
  );

  const previous = useRef("");

  useEffect(() => {
    if (!container.current || !scroll.current) return;

    const chart = createChart(container.current, {
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
        borderColor: "#1b3447",
        timeVisible: intraday,
        secondsVisible: false,

        ...(intraday
          ? {
            tickMarkFormatter: (t: Time) =>
              new Date(Number(t) * 1000).toLocaleTimeString("en-IN", {
                timeZone: "Asia/Kolkata",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false
              })
          }
          : {})
      },

      localization: {
        timeFormatter: (t: Time) =>
          new Date(Number(t) * 1000).toLocaleString("en-IN", {
            timeZone: intraday ? "Asia/Kolkata" : "UTC",
            ...(intraday
              ? {}
              : {
                year: "numeric",
                month: "short",
                day: "2-digit"
              })
          })
      }
    });

    chartRef.current = chart;

    seriesRef.current = chart.addSeries(LineSeries, {
      color: "#00d6a3",
      lineWidth: 2,
      priceFormat: {
        type: "price",
        precision: 2,
        minMove: 0.01
      },
      pointMarkersVisible: false,
      title: intraday ? "₹ / barrel" : "USD / barrel"
    });

    controller.current = attachChartScrollbar(chart, scroll.current);

    previous.current = "";

    return () => {
      controller.current?.destroy();
      controller.current = null;

      chart.remove();

      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [intraday]);

  useEffect(() => {
    if (!seriesRef.current) return;

    const unique = new Map(
      points
        .filter(
          (p) =>
            Number.isFinite(p.time) &&
            Number.isFinite(p.value)
        )
        .map((p) => [p.time, p.value])
    );

    const values = Array.from(
      unique,
      ([time, value]) => ({
        time: time as UTCTimestamp,
        value
      })
    ).sort((a, b) => a.time - b.time);

    seriesRef.current.setData(values);

    controller.current?.setExtent(values.length);

    const key = `${instrument}:${values.length
        ? new Date(values[0].time * 1000)
          .toISOString()
          .slice(0, 10)
        : "empty"
      }`;

    if (previous.current !== key) {
      if (values.length > 60) {
        controller.current?.showWindow(values.length - 1, 60);
      } else {
        chartRef.current?.timeScale().fitContent();
      }

      previous.current = key;
    } else if (intraday && followLatest) {
      chartRef.current?.timeScale().scrollToRealTime();
    }
  }, [points, instrument, intraday, followLatest]);

  return (
    <>
      <div className="energy-price-chart-wrap">
        <div
          className="energy-price-chart"
          ref={container}
        />

        {!points.length && (
          <div className="energy-chart-message">
            {unavailable || "Waiting for actual price history…"}
          </div>
        )}
      </div>

      <div
        className="chart-horizontal-scroll"
        ref={scroll}
        tabIndex={0}
        aria-label="Scroll crude oil chart horizontally"
      />

      <div className="muted tiny">
        {points.length === 1
          ? "First real quote recorded; a line appears after another quote."
          : points.length
            ? `${points.length} price observations · drag / zoom / scroll to inspect`
            : "No sample prices displayed."}
      </div>
    </>
  );
}
