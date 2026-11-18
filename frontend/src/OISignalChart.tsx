
import { oiDifferences } from "./oiDifference.js";
import { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  LineSeries,
  createSeriesMarkers,
  type ISeriesMarkersPluginApi,
  type Time,
  type ISeriesApi,
  type UTCTimestamp
} from "lightweight-charts";
import { sessionData } from "./marketSession";
import type { MarketSession } from "./marketSession";
import { attachChartScrollbar } from "./chartScrollbar.js";
import type { ChartScrollController } from "./chartScrollbar.js";
import { findCrossovers } from "./oiCrossovers.js";
import type { OICrossover } from "./oiCrossovers.js";
import { continuousChanges } from "./continuousOi.js";
import { makeSegments } from "./dynamicSeries";
import type { DynamicOIPoint } from "./dynamicSeries";

interface OIData {
  absolute_missing_points?: number;
  absolute_reference?: string;
  absolute_note?: string;
  session: MarketSession;
  observations: number;
  source: string;
  status: string;
  scope: string;
  expiry: string;
  anchor: number;
  step: number;
  put_strikes: number[];
  call_strikes: number[];
  contract_count: number;
  spot: number | null;
  quote_time: number;
  baseline_time: number;
  history_start?: number;
  historical_samples?: number;
  live_samples?: number;
  collector?: {
    running: boolean;
    last_error: string | null;
    backfill: {
      status: string;
      contracts_done?: number;
      contracts_total?: number;
      note?: string;
    };
  };
  latest: DynamicOIPoint;
  points: DynamicOIPoint[];
  segment: number;
  segment_points: number;
}

// Live OI snapshot passed to App.tsx for notification calculation.
export interface OILiveSnapshot {
  putOI: number;
  callOI: number;
  fresh: boolean;
  quoteTime: number;
  expiry: string;
}

type LineKey =
  | "put"
  | "call"
  | "average"
  | "absolutePut"
  | "absoluteCall";

interface AxisButton {
  key: LineKey;
  name: string;
  color: string;
  side: "left" | "right";
  y: number;
  value: number | null;
}

interface Pair {
  put: ISeriesApi<"Line">;
  call: ISeriesApi<"Line">;
  average: ISeriesApi<"Line">;
  atm: number;
  putMarkers?: ISeriesMarkersPluginApi<Time>;
  callMarkers?: ISeriesMarkersPluginApi<Time>;
}

const istTime = (t: number) =>
  new Date(t * 1000).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour12: false
  });

const number = (n: number) => n.toLocaleString("en-IN");

// numStrikes remains accepted for existing App.tsx.
// Wide table range does not control this near-ATM graph.
export default function OISignalChart({
  expiry,
  onOiUpdate,
}: {
  expiry: string;
  numStrikes: number;
  onOiUpdate?: (snapshot: OILiveSnapshot | null) => void;
}) {
  const el = useRef<HTMLDivElement>(null);
  const scrollEl = useRef<HTMLDivElement>(null);
  const chart = useRef<ReturnType<typeof createChart> | null>(null);
  const scrollbar = useRef<ChartScrollController | null>(null);

  const hoverAtm = useRef(new Map<number, number>());
  const pairs = useRef(new Map<number, Pair>());
  const absolutePut = useRef<ISeriesApi<"Line"> | null>(null);
  const absoluteCall = useRef<ISeriesApi<"Line"> | null>(null);

  const differenceAt = useRef(
    new Map<number, { put: number | null; call: number | null }>()
  );

  const rendered = useRef("");
  const fitted = useRef("");

  const [visible, setVisible] = useState<Record<LineKey, boolean>>({
    put: true,
    call: true,
    average: true,
    absolutePut: true,
    absoluteCall: true
  });

  const [axisButtons, setAxisButtons] = useState<AxisButton[]>([]);
  const lastAxisY = useRef(new Map<LineKey, number>());

  const toggleLine = (key: LineKey) =>
    setVisible(v => ({ ...v, [key]: !v[key] }));

  const [data, setData] = useState<OIData | null>(null);
  const [error, setError] = useState("");

  const [crossPixels, setCrossPixels] = useState<
    { x: number; y: number; direction: string; time: number }[]
  >([]);

  const [crosses, setCrosses] = useState<OICrossover[]>([]);
  const [mode, setMode] = useState<"total" | "change">("total");

  const [hover, setHover] = useState<{
    time: number;
    a: number;
    b: number;
    atm: number;
  } | null>(null);

  const [now, setNow] = useState(Date.now());

  // Initialize chart.
  useEffect(() => {
    if (!el.current || !scrollEl.current) return;

    const c = createChart(el.current, {
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
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: t => istTime(Number(t)),
        borderColor: "#1b3447"
      },
      localization: {
        timeFormatter: t => istTime(Number(t))
      },
      rightPriceScale: {
        borderColor: "#1b3447"
      }
    });

    chart.current = c;

    c.priceScale("left").applyOptions({
      visible: true,
      borderColor: "#a974ed"
    });

    absolutePut.current = c.addSeries(LineSeries, {
      color: "#bd83ff",
      lineWidth: 2,
      pointMarkersVisible: false,
      priceScaleId: "left",
      title: "Absolute Put",
      lastValueVisible: true,
      priceLineVisible: false,
      priceFormat: {
        type: "price",
        precision: 0,
        minMove: 1
      }
    });

    absoluteCall.current = c.addSeries(LineSeries, {
      color: "#00bfff",
      lineWidth: 2,
      pointMarkersVisible: false,
      priceScaleId: "left",
      title: "Absolute Call",
      lastValueVisible: true,
      priceLineVisible: false,
      priceFormat: {
        type: "price",
        precision: 0,
        minMove: 1
      }
    });

    scrollbar.current = attachChartScrollbar(c, scrollEl.current);

    c.subscribeCrosshairMove(p => {
      let found: {
        time: number;
        a: number;
        b: number;
        atm: number;
      } | null = null;

      for (const pair of pairs.current.values()) {
        const a = p.seriesData.get(pair.put);
        const b = p.seriesData.get(pair.call);

        if (p.time && a && b && "value" in a && "value" in b) {
          found = {
            time: Number(p.time),
            a: a.value,
            b: b.value,
            atm:
              hoverAtm.current.get(Number(p.time)) ?? pair.atm
          };
        }
      }

      setHover(found);
    });

    return () => {
      scrollbar.current?.destroy();
      scrollbar.current = null;
      pairs.current.clear();
      c.remove();
      chart.current = null;
    };
  }, []);

  // Fetch live OI data every 3 seconds.
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    absolutePut.current?.setData([]);
    absoluteCall.current?.setData([]);
    differenceAt.current.clear();

    setData(null);
    setError("");
    setHover(null);
    setCrosses([]);

    rendered.current = "";
    fitted.current = "";

    if (chart.current) {
      for (const pair of pairs.current.values()) {
        chart.current.removeSeries(pair.put);
        chart.current.removeSeries(pair.call);
        chart.current.removeSeries(pair.average);
      }
    }

    pairs.current.clear();

    const load = async () => {
      const current = new AbortController();
      controller = current;

      const timeout = setTimeout(() => current.abort(), 45000);

      try {
        const q = new URLSearchParams({
          symbol: "NIFTY",
          side_strikes: "3",
          itm_strikes: "0"
        });

        if (expiry) q.set("expiry", expiry);

        const response = await fetch(
          `http://127.0.0.1:8000/api/signals/oi?${q}`,
          { signal: current.signal }
        );

        const result = await response.json();

        if (!response.ok) {
          throw new Error(
            typeof result.detail === "string"
              ? result.detail
              : "OI request failed"
          );
        }

        if (
          result.selection_mode !== "dynamic-direct-sum" ||
          !result.session ||
          !Array.isArray(result.points) ||
          !result.points.length
        ) {
          throw new Error(
            "Install the matching dynamic OI backend files."
          );
        }

        if (active) {
          setData(result);
          setError("");
        }
      } catch (e) {
        if (active) {
          setError(
            e instanceof Error
              ? e.message
              : "Dynamic OI unavailable"
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
      clearTimeout(timer);
      controller?.abort();
    };
  }, [expiry]);

  // Update current time every second.
  useEffect(() => {
    const timer = setInterval(
      () => setNow(Date.now()),
      1000
    );

    return () => clearInterval(timer);
  }, []);

  // NEW: Send the exact live chart OI values to App.tsx.
  // No additional API request or polling timer is created.
  useEffect(() => {
    if (!data || error) {
      onOiUpdate?.(null);
      return;
    }

    const putOI = Number(data.latest.put_oi);
    const callOI = Number(data.latest.call_oi);

    const fresh =
      data.status === "fresh" &&
      Date.now() / 1000 - data.quote_time <= 30 &&
      Number.isFinite(putOI) &&
      Number.isFinite(callOI);

    onOiUpdate?.({
      putOI,
      callOI,
      fresh,
      quoteTime: data.quote_time,
      expiry: data.expiry
    });
  }, [data, error, now, onOiUpdate]);

  // Update chart series when new data arrives.
  useEffect(() => {
    const c = chart.current;

    if (!data || !c) return;

    const key = `${data.scope}:${mode}`;

    if (rendered.current !== key) {
      for (const pair of pairs.current.values()) {
        c.removeSeries(pair.put);
        c.removeSeries(pair.call);
        c.removeSeries(pair.average);
      }

      pairs.current.clear();
      rendered.current = key;
    }

    const changes = oiDifferences(data.points);

    differenceAt.current = new Map(
      changes.map(p => [
        p.time,
        { put: p.put, call: p.call }
      ])
    );

    absolutePut.current?.setData(
      sessionData(
        changes.map(p =>
          p.put == null
            ? { time: p.time as UTCTimestamp }
            : {
              time: p.time as UTCTimestamp,
              value: p.put
            }
        ),
        data.session
      )
    );

    absoluteCall.current?.setData(
      sessionData(
        changes.map(p =>
          p.call == null
            ? { time: p.time as UTCTimestamp }
            : {
              time: p.time as UTCTimestamp,
              value: p.call
            }
        ),
        data.session
      )
    );

    const linked = continuousChanges(data.points);

    hoverAtm.current = new Map(
      linked.map(p => [
        Math.floor(p.time / 60) * 60,
        p.atm
      ])
    );

    const groups = makeSegments(
      linked.map(p => ({ ...p, segment: 1 })),
      mode
    );

    const minuteSegments = new Map(
      linked.map(p => [
        Math.floor(p.time / 60) * 60,
        p.segment
      ])
    );

    const events = findCrossovers(
      groups.flatMap(g =>
        g.points.map(p => ({
          time: p.time,
          a: p.put,
          b: p.call,
          segment: minuteSegments.get(p.time) ?? 0
        }))
      ),
      Date.now() / 1000
    );

    setCrosses(events);

    const ids = new Set(groups.map(g => g.segment));

    for (const [id, pair] of pairs.current) {
      if (!ids.has(id)) {
        c.removeSeries(pair.put);
        c.removeSeries(pair.call);
        c.removeSeries(pair.average);
        pairs.current.delete(id);
      }
    }

    for (const group of groups) {
      let pair = pairs.current.get(group.segment);

      if (!pair) {
        const options = {
          lineWidth: 2 as const,
          pointMarkersVisible: false,
          priceFormat: {
            type: "price" as const,
            precision: 0,
            minMove: 1
          },
          lastValueVisible: false,
          priceLineVisible: false
        };

        pair = {
          put: c.addSeries(LineSeries, {
            ...options,
            color: "#00d6a3"
          }),
          call: c.addSeries(LineSeries, {
            ...options,
            color: "#ff4566"
          }),
          average: c.addSeries(LineSeries, {
            ...options,
            color: "#ffdd00"
          }),
          atm: group.atm
        };

        pair.putMarkers = createSeriesMarkers(pair.put, []);
        pair.callMarkers = createSeriesMarkers(pair.call, []);

        pairs.current.set(group.segment, pair);
      }

      pair.atm = group.atm;

      const current = true;

      pair.put.applyOptions({
        lastValueVisible: current,
        priceLineVisible: current,
        title: current
          ? mode === "total"
            ? "A · Put OI"
            : "A · Put ΔOI"
          : ""
      });

      pair.call.applyOptions({
        lastValueVisible: current,
        priceLineVisible: current,
        title: current
          ? mode === "total"
            ? "B · Call OI"
            : "B · Call ΔOI"
          : ""
      });

      pair.average.applyOptions({
        lastValueVisible: current,
        priceLineVisible: current,
        title: "Average · (A+B)/2"
      });

      pair.put.setData(
        sessionData(
          group.points.map(p => ({
            time: p.time as UTCTimestamp,
            value: p.put
          })),
          data.session
        )
      );

      pair.call.setData(
        sessionData(
          group.points.map(p => ({
            time: p.time as UTCTimestamp,
            value: p.call
          })),
          data.session
        )
      );

      pair.average.setData(
        sessionData(
          group.points.map(p => ({
            time: p.time as UTCTimestamp,
            value: (p.put + p.call) / 2
          })),
          data.session
        )
      );

      pair.putMarkers?.setMarkers(
        events
          .filter(e => e.direction === "CALL")
          .map(e => ({
            time: e.time as UTCTimestamp,
            position: "belowBar" as const,
            color: "#00d6a3",
            shape: "arrowUp" as const,
            text: "CALL cross"
          }))
      );

      pair.callMarkers?.setMarkers(
        events
          .filter(e => e.direction === "PUT")
          .map(e => ({
            time: e.time as UTCTimestamp,
            position: "aboveBar" as const,
            color: "#ff4566",
            shape: "arrowDown" as const,
            text: "PUT cross"
          }))
      );
    }

    scrollbar.current?.setExtent(
      Math.floor(
        (data.session.close - data.session.open) / 60
      ) + 1
    );

    if (fitted.current !== key) {
      scrollbar.current?.showWindow(
        Math.floor(
          (data.latest.time - data.session.open) / 60
        ),
        120
      );

      fitted.current = key;
    }

    setHover(null);
  }, [data, mode]);

  // Draw crossover intersections.
  useEffect(() => {
    const c = chart.current;
    const host = el.current;

    if (!c || !host) return;

    let frame = 0;

    const paint = () => {
      const pair = pairs.current.values().next()
        .value as Pair | undefined;

      if (!pair) {
        setCrossPixels([]);
        return;
      }

      const positions = crosses.flatMap(e => {
        const x0 = c.timeScale().timeToCoordinate(
          e.fromTime as UTCTimestamp
        );

        const x1 = c.timeScale().timeToCoordinate(
          e.time as UTCTimestamp
        );

        const value =
          e.fromA + (e.a - e.fromA) * e.fraction;

        const y = pair.put.priceToCoordinate(value);

        if (x0 == null || x1 == null || y == null) {
          return [];
        }

        const x =
          x0 +
          (x1 - x0) * e.fraction +
          c.priceScale("left").width();

        return x >= 0 &&
          x < host.clientWidth - 60 &&
          y >= 0 &&
          y < host.clientHeight - 22
          ? [{
            x,
            y,
            direction: e.direction,
            time: e.time
          }]
          : [];
      });

      setCrossPixels(positions);
    };

    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(paint);
    };

    c.timeScale().subscribeVisibleLogicalRangeChange(schedule);

    const observer = new ResizeObserver(schedule);
    observer.observe(host);

    host.addEventListener("pointermove", schedule);
    host.addEventListener("wheel", schedule);

    schedule();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();

      if (chart.current === c) {
        c.timeScale().unsubscribeVisibleLogicalRangeChange(schedule);
      }

      host.removeEventListener("pointermove", schedule);
      host.removeEventListener("wheel", schedule);
    };
  }, [crosses]);

  // Update axis labels and visibility.
  useEffect(() => {
    const c = chart.current;
    const host = el.current;

    if (!c || !host || !data) {
      setAxisButtons([]);
      return;
    }

    const pair = pairs.current.values().next()
      .value as Pair | undefined;

    if (!pair) return;

    const latest = continuousChanges(data.points).at(-1);
    const absolute = oiDifferences(data.points).at(-1);

    const defs: {
      key: LineKey;
      name: string;
      color: string;
      side: "left" | "right";
      series: ISeriesApi<"Line"> | null;
      value: number | null;
    }[] = [
        {
          key: "put",
          name: "Put sum",
          color: "#00d6a3",
          side: "right",
          series: pair.put,
          value:
            mode === "total"
              ? data.latest.put_oi
              : latest?.put_change ?? null
        },
        {
          key: "call",
          name: "Call sum",
          color: "#ff4566",
          side: "right",
          series: pair.call,
          value:
            mode === "total"
              ? data.latest.call_oi
              : latest?.call_change ?? null
        },
        {
          key: "average",
          name: "Average",
          color: "#ffdd00",
          side: "right",
          series: pair.average,
          value:
            mode === "total"
              ? (data.latest.put_oi + data.latest.call_oi) / 2
              : latest
                ? (latest.put_change + latest.call_change) / 2
                : null
        },
        {
          key: "absolutePut",
          name: "Absolute Put",
          color: "#bd83ff",
          side: "left",
          series: absolutePut.current,
          value: absolute?.put ?? null
        },
        {
          key: "absoluteCall",
          name: "Absolute Call",
          color: "#00bfff",
          side: "left",
          series: absoluteCall.current,
          value: absolute?.call ?? null
        }
      ];

    for (const d of defs) {
      d.series?.applyOptions({
        visible: visible[d.key],
        lastValueVisible: false,
        priceLineVisible: visible[d.key]
      });
    }

    const both = visible.put && visible.call;

    pair.putMarkers?.setMarkers(
      both
        ? crosses
          .filter(e => e.direction === "CALL")
          .map(e => ({
            time: e.time as UTCTimestamp,
            position: "belowBar" as const,
            color: "#00d6a3",
            shape: "arrowUp" as const,
            text: "CALL cross"
          }))
        : []
    );

    pair.callMarkers?.setMarkers(
      both
        ? crosses
          .filter(e => e.direction === "PUT")
          .map(e => ({
            time: e.time as UTCTimestamp,
            position: "aboveBar" as const,
            color: "#ff4566",
            shape: "arrowDown" as const,
            text: "PUT cross"
          }))
        : []
    );

    let frame = 0;

    const paint = () => {
      const maxY = Math.max(20, host.clientHeight - 32);

      const rows: AxisButton[] = defs.map((d, i) => {
        const coord =
          visible[d.key] && d.value != null
            ? d.series?.priceToCoordinate(d.value)
            : null;

        const y = Math.max(
          12,
          Math.min(
            maxY,
            coord ?? lastAxisY.current.get(d.key) ?? (22 + i * 24)
          )
        );

        lastAxisY.current.set(d.key, y);

        return {
          key: d.key,
          name: d.name,
          color: d.color,
          side: d.side,
          y,
          value: d.value
        };
      });

      // Keep labels clickable even when two latest values are very close.
      for (const side of ["left", "right"] as const) {
        const group = rows
          .filter(r => r.side === side)
          .sort((a, b) => a.y - b.y);

        for (let i = 1; i < group.length; i++) {
          group[i].y = Math.max(
            group[i].y,
            group[i - 1].y + 24
          );
        }

        if (group.length && group[group.length - 1].y > maxY) {
          group[group.length - 1].y = maxY;

          for (let i = group.length - 2; i >= 0; i--) {
            group[i].y = Math.min(
              group[i].y,
              group[i + 1].y - 24
            );
          }
        }
      }

      setAxisButtons(rows);
    };

    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(paint);
    };

    c.timeScale().subscribeVisibleLogicalRangeChange(schedule);

    const observer = new ResizeObserver(schedule);
    observer.observe(host);

    host.addEventListener("pointermove", schedule);
    host.addEventListener("wheel", schedule);
    host.addEventListener("pointerup", schedule);

    schedule();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();

      if (chart.current === c) {
        c.timeScale().unsubscribeVisibleLogicalRangeChange(schedule);
      }

      host.removeEventListener("pointermove", schedule);
      host.removeEventListener("wheel", schedule);
      host.removeEventListener("pointerup", schedule);
    };
  }, [data, mode, visible, crosses]);

  const latestDifference = data
    ? oiDifferences(data.points).at(-1)
    : undefined;

  const linkedLatest = data
    ? continuousChanges(data.points).at(-1)
    : undefined;

  const a =
    (mode === "total"
      ? data?.latest.put_oi
      : linkedLatest?.put_change) ?? 0;

  const b =
    (mode === "total"
      ? data?.latest.call_oi
      : linkedLatest?.call_change) ?? 0;

  const stale =
    !!error ||
    !data ||
    data.status !== "fresh" ||
    now / 1000 - data.quote_time > 30;

  // CALL BUY / PUT BUY signal based on Total OI.
  const putSumOI = Number(data?.latest.put_oi);
  const callSumOI = Number(data?.latest.call_oi);

  const oiDifference = Math.abs(putSumOI - callSumOI);

  const OI_THRESHOLD = 10_00_000; // 10 lakh

  const bias = !data
    ? "WAITING FOR OI"
    : stale
      ? "OI DATA STALE / UNAVAILABLE"
      : !Number.isFinite(putSumOI) ||
        !Number.isFinite(callSumOI)
        ? "HOLD"
        : oiDifference >= OI_THRESHOLD
          ? putSumOI > callSumOI
            ? "CALL BUY"
            : callSumOI > putSumOI
              ? "PUT BUY"
              : "HOLD"
          : "HOLD";

  const shown = hover ||
    (data
      ? {
        time: data.latest.time,
        a,
        b,
        atm: data.anchor
      }
      : null);

  return (
    <section
      className="oi-signal"
      aria-label="Continuous direct-sum OI comparison"
    >
      <div
        className={`oi-banner ${stale
          ? "oi-pending"
          : bias === "CALL BUY"
            ? "oi-up"
            : bias === "PUT BUY"
              ? "oi-down"
              : "oi-pending"
          }`}
      >
        <div>
          <strong>{bias}</strong>
          <small>
            {stale
              ? "Waiting for a complete fresh basket"
              : mode === "total"
                ? "Total OI · direct sum of 3 contracts per side"
                : "Direct ΔOI sum · ATM + first + second"}
          </small>
        </div>

        <div className="oi-spot">
          <small>NIFTY spot</small>
          <strong>
            {data?.spot != null ? number(data.spot) : "—"}
          </strong>
        </div>
      </div>

      <div className="oi-heading">
        <strong>Signal A vs Signal B</strong>

        <select
          aria-label="OI calculation"
          value={mode}
          onChange={e =>
            setMode(e.target.value as "total" | "change")
          }
        >
          <option value="total">Total OI · direct sum</option>
          <option value="change">Continuous direct-sum ΔOI</option>
        </select>
      </div>

      <div className="oi-legend">
        {([
          ["put", mode === "total" ? "Put sum" : "Put ΔOI", "#00d6a3"],
          ["call", mode === "total" ? "Call sum" : "Call ΔOI", "#ff4566"],
          ["average", "Average", "#ffdd00"],
          ["absolutePut", "Absolute Put", "#bd83ff"],
          ["absoluteCall", "Absolute Call", "#00bfff"]
        ] as [LineKey, string, string][]).map(
          ([key, label, color]) => (
            <button
              type="button"
              key={key}
              aria-pressed={visible[key]}
              onClick={() => toggleLine(key)}
              title={`Click to ${visible[key] ? "hide" : "show"} ${label}`}
              style={{
                background: "transparent",
                border: "1px solid transparent",
                color,
                cursor: "pointer",
                opacity: visible[key] ? 1 : 0.45,
                textDecoration: visible[key] ? "none" : "line-through",
                fontSize: 10,
                padding: "3px 5px"
              }}
            >
              — {label}
              {!visible[key] ? " (hidden)" : ""}
            </button>
          )
        )}
      </div>

      <div className="oi-caption">
        Click a line name or its coloured axis label to hide/show it.
        Hidden labels remain clickable.
      </div>

      <div style={{ position: "relative" }}>
        <div className="oi-plot" ref={el} />

        {axisButtons.map(item => (
          <button
            type="button"
            key={item.key}
            aria-pressed={visible[item.key]}
            aria-label={`${visible[item.key] ? "Hide" : "Show"} ${item.name}`}
            onClick={() => toggleLine(item.key)}
            title={`${item.name}: ${item.value == null ? "Unavailable" : number(item.value)
              }. Click to ${visible[item.key] ? "hide" : "show"}.`}
            style={{
              position: "absolute",
              [item.side]: 0,
              top: item.y,
              transform: "translateY(-50%)",
              zIndex: 5,
              border: `1px solid ${item.color}`,
              borderRadius: 3,
              background: visible[item.key] ? item.color : "#102230",
              color: visible[item.key] ? "#03121c" : item.color,
              padding: "3px 5px",
              fontSize: 9,
              cursor: "pointer",
              maxWidth: 155,
              whiteSpace: "nowrap",
              opacity: visible[item.key] ? 1 : 0.8
            }}
          >
            {item.name}
            {visible[item.key]
              ? ` ${item.value == null ? "—" : number(item.value)}`
              : " · SHOW"}
          </button>
        ))}

        <svg
          width="100%"
          height="100%"
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            overflow: "hidden"
          }}
          aria-label="Estimated visual crossover intersections"
        >
          {(visible.put && visible.call ? crossPixels : []).map(p => (
            <g key={`${p.time}:${p.direction}`}>
              <circle
                cx={p.x}
                cy={p.y}
                r={7}
                fill="#06121e"
                stroke={p.direction === "CALL" ? "#00d6a3" : "#ff4566"}
                strokeWidth={2}
              />
              <path
                d={`M${p.x - 3},${p.y - 3} L${p.x + 3},${p.y + 3} M${p.x - 3},${p.y + 3} L${p.x + 3},${p.y - 3}`}
                stroke={p.direction === "CALL" ? "#00d6a3" : "#ff4566"}
                strokeWidth={2}
              />
            </g>
          ))}
        </svg>

        {hover && (
          <div
            style={{
              position: "absolute",
              top: 12,
              left: 12,
              pointerEvents: "none",
              background: "#111e2cee",
              border: "1px solid #284457",
              borderRadius: 5,
              padding: "8px 10px",
              fontSize: 11,
              color: "#dbe8f2",
              zIndex: 3
            }}
          >
            <b>
              {istTime(hover.time)} IST · ATM {hover.atm}
            </b>
            <br />

            <span style={{ color: "#00d6a3" }}>
              ● Signal A · Put: {number(hover.a)}
            </span>
            <br />

            <span style={{ color: "#ff4566" }}>
              ● Signal B · Call: {number(hover.b)}
            </span>
            <br />

            <span style={{ color: "#ffdd00" }}>
              — Average: {number((hover.a + hover.b) / 2)}
            </span>
            <br />

            <span style={{ color: "#bd83ff" }}>
              Absolute Put: {
                differenceAt.current.get(hover.time)?.put != null
                  ? number(differenceAt.current.get(hover.time)!.put!)
                  : "—"
              }
            </span>
            <br />

            <span style={{ color: "#00bfff" }}>
              Absolute Call: {
                differenceAt.current.get(hover.time)?.call != null
                  ? number(differenceAt.current.get(hover.time)!.call!)
                  : "—"
              }
            </span>
          </div>
        )}
      </div>

      <div className="oi-caption">
        Five lines: Put sum, Call sum and yellow average on the right axis.
        Absolute Put (purple) and Absolute Call (blue), left axis: each side
        = OI from 15 minutes earlier − current OI. Positive = OI decreased;
        negative = OI increased. Same ATM basket only; missing 15-minute
        history → gap.
      </div>

      <div className="oi-caption">
        Fifteen-minute comparison uses the last actual observation in each
        minute bucket, with no forward fill.{" "}
        {latestDifference && (
          <>
            Absolute Put (15m):{" "}
            {latestDifference.put == null
              ? "—"
              : number(latestDifference.put)}{" "}
            · Absolute Call (15m):{" "}
            {latestDifference.call == null
              ? "—"
              : number(latestDifference.call)}
          </>
        )}
      </div>

      <div
        className="chart-horizontal-scroll"
        ref={scrollEl}
        tabIndex={0}
        aria-label="Scroll dynamic OI history horizontally"
      />

      <div className="oi-caption" role="status">
        {crosses.length ? (
          <>
            Last confirmed crossover:{" "}
            <b
              className={
                crosses[crosses.length - 1].direction === "CALL"
                  ? "positive"
                  : "negative"
              }
            >
              {crosses[crosses.length - 1].direction} ·{" "}
              {istTime(crosses[crosses.length - 1].time)} IST
            </b>{" "}
            · {crosses.length} recorded crosses
          </>
        ) : (
          "No confirmed crossover in the available continuous line history."
        )}

        <br />

        Circled × shows an estimated line intersection; arrow shows the
        confirming observation. Markers use completed displayed minutes;
        label time is the confirming observation, not an exact intraminute
        intersection. Historical markers are not current trade recommendations.
      </div>

      <div className="oi-values">
        {shown ? (
          <>
            {istTime(shown.time)} IST · ATM {shown.atm} ·{" "}
            <span className="positive">
              A: {number(shown.a)}
            </span>{" "}
            ·{" "}
            <span className="negative">
              B: {number(shown.b)}
            </span>{" "}
            ·{" "}
            <span style={{ color: "#ffdd00" }}>
              Average: {number((shown.a + shown.b) / 2)}
            </span>{" "}
            ·{" "}
            <span style={{ color: "#bd83ff" }}>
              Absolute Put: {
                (hover
                  ? differenceAt.current.get(hover.time)?.put
                  : latestDifference?.put) != null
                  ? number(
                    (hover
                      ? differenceAt.current.get(hover.time)?.put
                      : latestDifference?.put)!
                  )
                  : "—"
              }
            </span>{" "}
            ·{" "}
            <span style={{ color: "#00bfff" }}>
              Absolute Call: {
                (hover
                  ? differenceAt.current.get(hover.time)?.call
                  : latestDifference?.call) != null
                  ? number(
                    (hover
                      ? differenceAt.current.get(hover.time)?.call
                      : latestDifference?.call)!
                  )
                  : "—"
              }
            </span>
          </>
        ) : (
          "Waiting for the first real observation…"
        )}
      </div>

      <div className="oi-caption" role="status">
        {error ? (
          <span className="negative">
            {error} · last chart retained
          </span>
        ) : !data ? (
          "Loading dynamic contracts…"
        ) : (
          <>
            {data.expiry} · dynamic ATM {data.anchor} · step {data.step} ·{" "}
            {data.contract_count} contracts · refresh 3s
          </>
        )}

        {data && (
          <>
            <br />
            PE: {data.put_strikes.map(number).join(" / ")}
            <br />
            CE: {data.call_strikes.map(number).join(" / ")}
            <br />
            {data.session.date} · {data.session.label} ·{" "}
            {data.observations} recorded samples · 1-min view.
            <br />

            {mode === "total" ? (
              "Total OI uses the actual current contract OI sums, without baseline subtraction or continuity offsets. ATM changes can change the basket total; boundary jumps are not crossover signals."
            ) : (
              <>
                Basket baseline: {istTime(data.baseline_time)} IST · resets
                on each ATM change. Continuous ΔOI carries the prior
                basket’s final change forward.
              </>
            )}

            Backend recorder:{" "}
            {data.collector?.running
              ? "running independently of login"
              : "not running"}{" "}
            · backfill{" "}
            {data.collector?.backfill.status || "waiting"}
            {data.collector?.backfill.contracts_total
              ? ` (${data.collector.backfill.contracts_done}/${data.collector.backfill.contracts_total})`
              : ""}
            . {data.historical_samples || 0} historical minute observations
            / {data.live_samples || 0} live snapshots.{" "}
            {data.collector?.backfill.note || ""}{" "}
            {data.collector?.last_error || ""}
          </>
        )}
      </div>
    </section>
  );
}
