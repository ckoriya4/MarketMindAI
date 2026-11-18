import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Zap } from "lucide-react";
import CrudePriceChart from "./CrudePriceChart";
import "./EnergyPanels.css";

interface PriceSeries {
    price: number; as_of: string; change: number; change_pct: number | null;
    previous_date: string; history: { date: string; value: number }[]; url: string;
}
interface CrudeData {
    official: { status: string; error?: string; fetched_at?: string; series?: { WTI?: PriceSeries; Brent?: PriceSeries } };
    mcx: { status: string; price?: number; change_pct?: number | null; symbol?: string; quote_time?: number; error?: string; history?: { time: number; value: number }[]; history_mode?: string; history_error?: string };
}
interface NewsItem { id: string; title: string; url: string; published_at: string | null; source: string; categories: string[]; tag: string; sentiment?: { label: string; method: string; positive_terms: string[]; negative_terms: string[]; mixed_or_negated: boolean } }
interface CalendarEvent { id: string; title: string; currency: string; scheduled_at: string; impact: string; forecast: string; previous: string; source: string; url: string; upcoming: boolean }
interface NewsSourceStatus { status: string; error?: string; fetched_at?: string }
interface Share { total: number; direction: string; percentages: Record<string, number | null> }
interface Analysis { overall: Share; factors: (Share & { name: string; related_sectors?: string[]; mentioned_company_sectors?: string[]; companies?: { name: string; symbol: string; sector: string }[] })[]; unique_headlines: number }
interface NewsData { analysis?: Analysis; status: string; items: NewsItem[]; fetched_at?: string; error?: string; feed_failures?: number; days?: number; total?: number; range_start?: string; range_end?: string; coverage?: string; calendar_events?: CalendarEvent[]; sources?: Record<string, NewsSourceStatus> }

function useOfficialData<T>(path: string, interval: number) {
    const [data, setData] = useState<T | null>(null);
    const [error, setError] = useState("");
    useEffect(() => {
        let active = true;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let controller: AbortController | undefined;
        const load = async () => {
            const current = new AbortController(); controller = current;
            const timeout = setTimeout(() => current.abort(), 90000);
            try {
                const response = await fetch(`http://127.0.0.1:8000${path}`, { signal: current.signal });
                const result = await response.json();
                if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : `Energy API error ${response.status}`);
                if (active) { setData(result); setError(""); }
            } catch (e) {
                if (active) setError(e instanceof Error && e.name === "AbortError" ? "Official data request timed out" : e instanceof Error ? e.message : "Official data unavailable");
            } finally { clearTimeout(timeout); if (active) timer = setTimeout(load, interval); }
        };
        void load();
        return () => { active = false; clearTimeout(timer); controller?.abort(); };
    }, [path, interval]);
    return { data, error };
}

const signed = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;
const dollars = (s?: PriceSeries) => s ? `$${s.price.toFixed(2)}` : "—";
const shortNewsDate = (value: string) => {
    const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "2-digit" }).formatToParts(new Date(value));
    const part = (type: string) => parts.find(p => p.type === type)?.value || "";
    return `${part("day")}/${part("month")}/${part("year")}`;
};
const ist = (timestamp: number) => new Date(timestamp * 1000).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });

export function CrudeOilPanel() {
    const { data, error } = useOfficialData<CrudeData>("/api/energy/crude", 30000);
    const [now, setNow] = useState(Date.now());
    const [chartSource, setChartSource] = useState("MCX");
    useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
    const wti = data?.official.series?.WTI, brent = data?.official.series?.Brent;
    const mcx = data?.mcx;
    const mcxFresh = !error && mcx?.status === "fresh" && mcx.quote_time != null && now / 1000 - mcx.quote_time <= 90;
    const points = useMemo(() => chartSource === "MCX" ? mcx?.history || [] : (chartSource === "WTI" ? wti?.history : brent?.history)?.map(p => ({ time: Date.parse(`${p.date}T12:00:00Z`) / 1000, value: p.value })) || [], [chartSource, mcx, wti, brent]);
    const chartNote = chartSource === "MCX" ? mcx?.history_error || mcx?.error : data?.official.error;
    const changed = wti ? `${signed(wti.change)}${wti.change_pct != null ? ` (${signed(wti.change_pct)}%)` : ""} · WTI daily` : "Waiting for official prices…";
    return <section className="panel crude">
        <div className="panel-title"><span><Activity size={15} />CRUDE OIL ANALYSIS</span></div>
        <div className="crude-head"><div className="oil-icon">♜</div><div>
            <span className="muted tiny">WTI / Brent (EIA daily · USD/barrel)</span>
            <b>{dollars(wti)} / {dollars(brent)}</b>
            <span className={wti && wti.change < 0 ? "negative" : "positive"}>{changed}</span>
        </div></div>
        <div className="energy-chart-toolbar"><strong className="tiny">{chartSource === "MCX" ? mcx?.symbol || "MCX crude" : `${chartSource} daily spot`} — PRICE CHART</strong>
            <select aria-label="Crude chart instrument" value={chartSource} onChange={e => setChartSource(e.target.value)}><option value="MCX">MCX crude · INR</option><option value="WTI">WTI · EIA daily</option><option value="Brent">Brent · EIA daily</option></select>
        </div>
        <CrudePriceChart points={points} instrument={chartSource === "MCX" ? mcx?.symbol || "MCX" : chartSource} intraday={chartSource === "MCX"} unavailable={chartNote} />
        <div className="muted tiny">{chartSource === "MCX" ? mcx?.history_mode || "Kite historical/observed prices" : "U.S. EIA daily published observations"}{chartNote && points.length > 0 ? ` · ${chartNote}` : ""}</div>
        <ul className="check-list">
            <li>{wti || brent ? <>As of: WTI {wti?.as_of || "—"} · Brent {brent?.as_of || "—"}</> : "Official daily observations loading…"}</li>
            <li>{mcx?.price != null ? <>MCX {mcx.symbol}: ₹{mcx.price.toLocaleString("en-IN")} {mcx.change_pct != null ? `(${signed(mcx.change_pct)}%)` : ""} · {mcx.quote_time ? `${ist(mcx.quote_time)} IST` : ""} · {mcxFresh ? "Kite snapshot" : "STALE"}</> : mcx?.error || "Loading optional MCX quote…"}</li>
            <li>{error ? `STALE / UNAVAILABLE · ${error}` : data?.official.status === "stale" || data?.official.status === "unavailable" ? data.official.error : <>Source: U.S. EIA · daily spot history · auto refresh{data?.official.fetched_at ? ` · fetched ${new Date(data.official.fetched_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" })} IST` : ""}</>}</li>
        </ul>
    </section>;
}

export function OfficialNewsPanel() {
    const { data, error } = useOfficialData<NewsData>("/api/energy/news", 60000);
    const [filter, setFilter] = useState("All");
    const [now, setNow] = useState(Date.now());
    useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 30000); return () => clearInterval(timer); }, []);
    const calendar = filter === "High Impact";
    const filtered = useMemo(() => (data?.items || []).filter(item => filter === "All" ? true : filter === "FXStreet" ? item.source === "FXStreet" : item.categories.includes(filter)), [data, filter]);
    const dayKey = (value: number) => new Date(value).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
    const recent = (value: string | null) => !!value && Date.parse(value) <= now && [dayKey(now), dayKey(now - 86400000)].includes(dayKey(Date.parse(value)));
    const upcoming = (data?.calendar_events || []).filter(event => recent(event.scheduled_at)).sort((a, b) => Date.parse(b.scheduled_at) - Date.parse(a.scheduled_at));
    const displayed = filtered.filter(item => recent(item.published_at));
    const summary = data?.analysis;
    const currentSummary = !!data?.range_start && dayKey(Date.parse(data.range_start)) === dayKey(now - 86400000);
    const pct = (row: Share, label: string) => row.percentages[label] == null ? "—" : `${row.percentages[label]!.toFixed(1)}%`;
    const newsScroll = useRef<HTMLDivElement>(null);
    useEffect(() => { if (newsScroll.current) newsScroll.current.scrollTop = 0; }, [filter]);
    const sourceStatus = calendar ? data?.sources?.forexfactory : filter === "FXStreet" ? data?.sources?.fxstreet : undefined;
    const status = error || sourceStatus?.error || data?.error;
    const failedSources = Object.entries(data?.sources || {}).filter(([, s]) => s.status === "unavailable" || s.status === "stale" || s.status === "not_configured" || s.status === "partial").map(([key]) => key);
    return <section className="panel news">
        <div className="panel-title"><span><Zap size={15} />LATEST NEWS &amp; EVENTS</span></div>
        <div className="news-filters">{["All", "Market", "Crude", "Stocks", "Policy", "High Impact", "FXStreet"].map(label => <button key={label} className={filter === label ? "selected" : ""} onClick={() => setFilter(label)}>{label}</button>)}</div>
        <div className="energy-news-scroll" ref={newsScroll} tabIndex={0} aria-label={calendar ? "Recent scheduled high-impact events" : "News from today and yesterday IST"}>
            {calendar ? upcoming.map(event => <div className="news-row" key={event.id}>
                <time title={new Date(event.scheduled_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) + " IST"}>{shortNewsDate(event.scheduled_at)}<br />{new Date(event.scheduled_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false })}</time>
                <span><a href={event.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }}>{event.currency} · {event.title}</a><small className="fx-news-detail">Forex Factory · scheduled IST · Forecast: {event.forecast || "—"} · Previous: {event.previous || "—"}</small></span>
                <b className="negative-tag" title="Forex Factory high expected impact; this is not negative sentiment">High</b>
            </div>) : displayed.map(item => <div className="news-row" key={item.id}>
                <time title={item.published_at ? new Date(item.published_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" }) + " IST" : "Publication time not supplied"}>{item.published_at ? shortNewsDate(item.published_at) : "—"}{item.published_at && <><br />{new Date(item.published_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false })} IST</>}</time>
                <span><a href={item.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }} title={`Read ${item.source} article`}>{item.title}</a><small className="fx-news-detail">{item.source}</small></span>
                <b className={(item.sentiment?.label || item.tag) === "Positive" ? "positive-tag" : (item.sentiment?.label || item.tag) === "Negative" ? "negative-tag" : "neutral-tag"}
                    title={`Automated headline wording · ${item.sentiment?.method || "rules"}; not publisher sentiment or a market-impact prediction`}>
                    {["Positive", "Negative", "Neutral"].includes(item.sentiment?.label || item.tag) ? item.sentiment?.label || item.tag : "Neutral"}
                </b>
            </div>)}
            {!(calendar ? upcoming.length : displayed.length) && <div className="muted tiny">{!data && !error ? "Loading publisher feeds…" : status || (calendar ? "No High Impact events available for today or yesterday." : `No ${filter === "All" ? "headlines" : filter + " headlines"} available today or yesterday.`)}</div>}
        </div>
        <div className="news-factor-summary" aria-label="All-news headline sentiment">
            <strong>ALL NEWS · FACTOR SENTIMENT</strong>
            {summary && currentSummary && summary.overall.total > 0 ? <>
                <div className="news-share-row"><b>{summary.overall.direction} wording</b><span className="positive">+ {pct(summary.overall, "Positive")}</span><span className="negative">− {pct(summary.overall, "Negative")}</span><span>Neutral {pct(summary.overall, "Neutral")}</span></div>
                <div className="news-factor-scroll" tabIndex={0}>{summary.factors.map(row => <details className="news-factor-detail" key={row.name}>
                    <summary><span className="news-share-row"><span>{row.name} ({row.total})</span><span className="positive">+ {pct(row, "Positive")}</span><span className="negative">− {pct(row, "Negative")}</span><span>N {pct(row, "Neutral")}</span></span></summary>
                    <div className="news-sector-detail"><b>Related sectors:</b> {row.related_sectors?.join(", ") || "Depends on the named company / announcement."}
                        <div><b>Mentioned company sectors:</b> {row.mentioned_company_sectors?.join(", ") || "Not mapped."}</div>
                        <b>Companies mentioned ({row.companies?.length || 0}):</b>
                        {row.companies?.length ? <ul>{row.companies.map(c => <li key={c.name}>{c.name}{c.symbol ? ` (${c.symbol})` : ""} · {c.sector}</li>)}</ul> : <div>No supported company match in these headlines.</div>}
                        <small>Related sectors are a watchlist. Company mentions do not confirm positive/negative impact.</small>
                    </div>
                </details>)}</div>
                <small>{summary.unique_headlines} unique headlines · all tabs · factors may overlap.</small>
            </> : <div className="muted tiny">No current summary available.</div>}
            <small>Headline wording percentages, not predicted market impact. Missing feeds reduce coverage.</small>
        </div>
        <div className="muted tiny" role="status" title={Object.entries(data?.sources || {}).map(([name, s]) => `${name}: ${s.status}${s.error ? ` — ${s.error}` : ""}`).join("\n")}>{status ? `STALE / UNAVAILABLE · ${status}` : calendar ? `Forex Factory · ${upcoming.length} scheduled high-impact events · today + yesterday · times IST` : `Today + yesterday IST · ${displayed.length} shown · multi-source feeds · automated sentiment · refresh 1m`}{failedSources.length > 0 && !status ? ` · source issues: ${failedSources.join(", ")}` : ""}</div>
    </section>;
}
