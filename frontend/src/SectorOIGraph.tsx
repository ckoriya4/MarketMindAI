
// import { useEffect, useRef, useState } from "react";
// import { createChart, ColorType, LineSeries } from "lightweight-charts";
// import type { ISeriesApi, UTCTimestamp, Time } from "lightweight-charts";
// import { attachChartScrollbar } from "./chartScrollbar.js";
// import "./SectorOIGraph.css";
// import { sectorLineData, valueCount } from "./sectorLineData.js";
// import type { MarketSession } from "./marketSession";
// import { apiUrl } from "./config/api";

// const names = ['Financial Services', 'Information Technology', 'Oil, Gas & Consumable Fuels', 'FMCG', 'Combined'];
// const colors = ['#00d6a3', '#00a6ff', '#f5b82e', '#c477ff', '#f0f6ff'];

// interface Value {
//   call: number | null;
//   put: number | null;
//   total: number | null;
// }

// interface Snapshot {
//   recording?: { running: boolean; error?: string | null };
//   sector_coverage?: Record<string, { expected: number; complete: number; missing: string[] }>;
//   absolute_points?: { time: number; values: Record<string, Value> }[];
//   sector_company_counts?: Record<string, number>;
//   session?: MarketSession;
//   backfill?: { status: string; contracts_done?: number; contracts_total?: number; note?: string };
//   baseline_times?: Record<string, number>;
//   stage?: string;
//   scope?: string;
//   status?: string;
//   error?: string;
//   expiry?: string;
//   baseline_time?: number;
//   contracts_total?: number;
//   contracts_done?: number;
//   quoted_companies?: number;
//   company_count?: number;
//   collection_span_seconds?: number;
//   fetched_at?: number;
//   points: { time: number; values: Record<string, Value> }[];
// }

// const time = (t: number) =>
//   new Date(t * 1000).toLocaleTimeString('en-IN', {
//     timeZone: 'Asia/Kolkata',
//     hour12: false
//   });

// export default function SectorOIGraph() {
//   const host = useRef<HTMLDivElement>(null),
//     scrollHost = useRef<HTMLDivElement>(null),
//     chart = useRef<ReturnType<typeof createChart> | null>(null),
//     lines = useRef<ISeriesApi<'Line'>[]>([]),
//     scroller = useRef<ReturnType<typeof attachChartScrollbar> | null>(null),
//     fitted = useRef(false);

//   const scopeRef = useRef('');
//   const anchor = useRef<ISeriesApi<'Line'> | null>(null);

//   const [view, setView] = useState<'oi' | 'change'>('oi');
//   const [data, setData] = useState<Snapshot | null>(null),
//     [error, setError] = useState(''),
//     [metric, setMetric] = useState<'total' | 'call' | 'put'>('total'),
//     [visible, setVisible] = useState(names),
//     [now, setNow] = useState(Date.now());

//   const points = data
//     ? (view === 'oi' ? data.absolute_points || [] : data.points)
//     : [];

//   useEffect(() => {
//     const id = setInterval(() => setNow(Date.now()), 10000);
//     return () => clearInterval(id);
//   }, []);

//   useEffect(() => {
//     if (!host.current || !scrollHost.current) return;

//     const c = createChart(host.current, {
//       autoSize: true,
//       layout: {
//         background: { type: ColorType.Solid, color: '#06121e' },
//         textColor: '#8fa9bd',
//         fontSize: 10
//       },
//       grid: {
//         vertLines: { color: '#12283a' },
//         horzLines: { color: '#12283a' }
//       },
//       rightPriceScale: { borderColor: '#1b3447' },
//       timeScale: {
//         timeVisible: true,
//         borderColor: '#1b3447',
//         tickMarkFormatter: (t: Time) => time(Number(t)).slice(0, 5)
//       },
//       localization: {
//         timeFormatter: (t: Time) => time(Number(t)) + ' IST'
//       }
//     });

//     chart.current = c;

//     anchor.current = c.addSeries(LineSeries, {
//       color: 'transparent',
//       lineVisible: false,
//       lastValueVisible: false,
//       priceLineVisible: false,
//       crosshairMarkerVisible: false
//     });

//     lines.current = names.map((name, i) =>
//       c.addSeries(LineSeries, {
//         color: colors[i],
//         lineWidth: name === 'Combined' ? 3 : 2,
//         pointMarkersVisible: false,
//         title: name,
//         priceLineVisible: false,
//         lastValueVisible: false,
//         priceFormat: { type: 'volume' }
//       })
//     );

//     scroller.current = attachChartScrollbar(c, scrollHost.current);

//     return () => {
//       scroller.current?.destroy();
//       c.remove();
//       chart.current = null;
//       lines.current = [];
//     };
//   }, []);

//   useEffect(() => {
//     let active = true;
//     let timer: ReturnType<typeof setTimeout> | undefined;
//     let controller: AbortController | undefined;

//     const load = async () => {
//       controller = new AbortController();
//       const timeout = setTimeout(() => controller?.abort(), 20000);

//       try {
//         const response = await fetch(
//           apiUrl("/api/market/sector-oi"),
//           { signal: controller.signal }
//         );

//         const result = await response.json();

//         if (!response.ok)
//           throw new Error(
//             typeof result.detail === 'string'
//               ? result.detail
//               : 'Sector OI unavailable'
//           );

//         if (active) {
//           setData(result);
//           setError('');
//         }

//       } catch (e) {
//         if (active)
//           setError(e instanceof Error ? e.message : 'Sector OI unavailable');

//       } finally {
//         clearTimeout(timeout);
//         if (active) timer = setTimeout(load, 15000);
//       }
//     };

//     void load();

//     return () => {
//       active = false;
//       clearTimeout(timer);
//       controller?.abort();
//     };
//   }, []);

//   useEffect(() => {
//     if (!data || !chart.current) return;

//     if (scopeRef.current !== data.scope) {
//       fitted.current = false;
//       scopeRef.current = data.scope || '';
//     }

//     if (data.session) {
//       const times = [];

//       for (let t = data.session.open; t <= data.session.close; t += 60)
//         times.push({ time: t as UTCTimestamp });

//       times.push({ time: data.session.close as UTCTimestamp });

//       anchor.current?.setData(
//         Array.from(new Map(times.map(p => [p.time, p])).values())
//       );

//     } else {
//       anchor.current?.setData([]);
//     }

//     names.forEach((name, i) => {
//       const seriesPoints = sectorLineData(points, name, metric, data.session);

//       lines.current[i].setData(
//         seriesPoints.map(p =>
//           p.value == null
//             ? { time: p.time as UTCTimestamp }
//             : { time: p.time as UTCTimestamp, value: p.value }
//         )
//       );

//       lines.current[i].applyOptions({
//         visible: visible.includes(name),
//         lastValueVisible: visible.includes(name)
//       });
//     });

//     scroller.current?.setExtent(
//       data.session
//         ? Math.floor((data.session.close - data.session.open) / 60) + 1
//         : Math.max(1, points.length)
//     );

//     if (!fitted.current && (data.session || points.length)) {
//       chart.current.timeScale().fitContent();
//       fitted.current = true;
//     }

//   }, [data, metric, visible, view]);

//   const counts = Object.fromEntries(
//     names.map(name => [
//       name,
//       valueCount(sectorLineData(points, name, metric, data?.session))
//     ])
//   );

//   const stale =
//     !!error ||
//     !data?.fetched_at ||
//     now / 1000 - data.fetched_at > 240 ||
//     data.status !== 'ok';

//   return (
//     <section className="sector-oi-graph" aria-label="Four sector option OI change graph">

//       <div className="sector-oi-heading">
//         <button
//           title="Show complete market session"
//           onClick={() => chart.current?.timeScale().fitContent()}
//         >
//           Full session
//         </button>

//         <strong>
//           4 SECTORS + COMBINED · {view === 'oi' ? 'TOTAL OI' : 'CHANGE IN OI'}
//         </strong>

//         <select
//           aria-label="OI value type"
//           value={view}
//           onChange={e => setView(e.target.value as 'oi' | 'change')}
//         >
//           <option value="oi">Total OI</option>
//           <option value="change">Change in OI</option>
//         </select>

//         <select
//           aria-label="Sector OI measure"
//           value={metric}
//           onChange={e => setMetric(e.target.value as 'total' | 'call' | 'put')}
//         >
//           <option value="total">Call + Put OI</option>
//           <option value="put">Put OI</option>
//           <option value="call">Call OI</option>
//         </select>
//       </div>

//       <div className="sector-oi-legend">
//         {names.map((name, i) =>
//           <button
//             key={name}
//             title="Toggle line"
//             onClick={() => setVisible(v =>
//               v.includes(name) ? v.filter(n => n !== name) : [...v, name]
//             )}
//             style={{
//               color: colors[i],
//               opacity: visible.includes(name) ? 1 : .35
//             }}
//           >
//             {name === 'Combined' ? '━' : '—'} {name}
//           </button>
//         )}
//       </div>

//       <div
//         className="sector-oi-host"
//         ref={host}
//         style={{ height: 260, minHeight: 260 }}
//       />

//       <div
//         className="chart-horizontal-scroll"
//         ref={scrollHost}
//         tabIndex={0}
//         aria-label="Scroll sector OI graph"
//       />

//       <div className="sector-combined-values">
//         {names.map((name, i) => {
//           const point = [...points].reverse().find(
//             p => p.values[name]?.[metric] != null
//           );

//           return (
//             <span key={name} style={{ color: colors[i] }}>
//               {name}
//               {name !== 'Combined'
//                 ? ` (${data?.sector_company_counts?.[name] || 0} companies)`
//                 : ''}:
//               <b>
//                 {point?.values[name]?.[metric]?.toLocaleString('en-IN') ?? 'Unavailable'}
//               </b>
//               {point
//                 ? ` · ${time(point.time)} · ${counts[name]} observations${counts[name] === 1 ? ' — waiting for second real snapshot' : ''}`
//                 : ''}
//             </span>
//           );
//         })}
//       </div>

//       <div className="sector-oi-note">
//         Backend recording: {data?.recording?.running
//           ? 'running independently of browser'
//           : 'not started — install startup hook'}. {data?.recording?.error || ''}
//         <br />
//         Lines connect actual observations; empty axis minutes do not insert fake values. Missing-sector snapshots remain gaps. A single value can show a price label but cannot draw a history line.
//         <br />
//         {data?.session
//           ? `${data.session.date} · ${data.session.label} · full-session axis. `
//           : ''}
//         Combined = Financial + IT + Oil/Gas + FMCG. All four are required at the same minute.
//         <br />
//         Historical backfill: {data?.backfill?.status || 'waiting'} {data?.backfill?.contracts_total
//           ? `${data.backfill.contracts_done || 0}/${data.backfill.contracts_total} contracts`
//           : ''}. {data?.backfill?.note || ''}
//       </div>

//       {data?.sector_coverage && (
//         <div className="sector-oi-note">
//           {Object.entries(data.sector_coverage).map(([name, c]) =>
//             <div key={name}>
//               {name}: {c.complete}/{c.expected} companies complete
//               {c.missing.length ? ` · missing: ${c.missing.join(', ')}` : ''}
//             </div>
//           )}
//         </div>
//       )}

//       <div className="sector-oi-note" role="status">
//         {error || data?.error || (!points.length
//           ? 'Collecting actual CE/PE quotes. A sector starts when its basket is complete; at least two observations are needed to draw a line.'
//           : stale
//             ? 'Last recorded data / collecting update.'
//             : 'Live polling snapshots.')}
//         {data?.expiry ? ` Expiry ${data.expiry}.` : ''}
//         {data?.baseline_time ? ` Baseline ${time(data.baseline_time)} IST.` : ''}
//         {data?.contracts_total != null
//           ? ` ${data.contracts_done || 0}/${data.contracts_total} contracts processed.`
//           : ''}
//         {data?.company_count != null
//           ? ` ${data.quoted_companies || 0}/${data.company_count} companies complete.`
//           : ''}
//         {data?.fetched_at
//           ? ` Collected ${time(data.fetched_at)} IST (${data.collection_span_seconds || 0}s collection).`
//           : ''}
//         {data?.stage ? ` Stage: ${data.stage}.` : ''}
//         {points.length === 1
//           ? ' One point recorded; waiting for the second observation.'
//           : ''}

//         {data?.baseline_times && (
//           <div>
//             {Object.entries(data.baseline_times).map(([name, t]) =>
//               <span key={name}>{name}: baseline {time(t)} IST. </span>
//             )}
//           </div>
//         )}

//         <br />
//         {view === 'oi'
//           ? 'Total OI: each sector = sum of its companies’ actual option OI. Combined = sum of all four sectors; no baseline subtraction.'
//           : 'Change in OI: sector totals minus each sector’s earliest complete baseline. The first snapshot correctly has zero change.'
//         }
//         NIFTY50 members only · all listed strikes of common expiry · raw OI units, not sector price return. Missing coverage stays unavailable. One observation is a starting value; a line requires a second recorded observation.
//       </div>

//     </section>
//   );
// }
