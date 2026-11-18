import { useEffect, useState } from "react";
import { BrainCircuit } from "lucide-react";

interface LiveSignal {
    warning?: string;
    quote_skew_seconds?: number;
    stale_quote_count?: number;
    quote_count?: number;
    source: "kite";
    status: "fresh" | "stale";
    quote_time: number;
    expiry: string;
    contract_count: number;
    strike_min: number;
    strike_max: number;
    pcr: number;
    pcr_bias: string;
    support: number;
    resistance: number;
    score: number | null;
    trend: string;
    recommendation: string;
    price_action: string;
    price_action_direction: number;
}

export default function LiveConfluencePanel({ expiry, numStrikes }: {
    expiry: string;
    numStrikes: number;
}) {
    const [data, setData] = useState<LiveSignal | null>(null);
    const [error, setError] = useState("");
    const [now, setNow] = useState(Date.now());

    useEffect(() => {
        let active = true;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let controller: AbortController | undefined;
        setData(null);
        setError("");

        const load = async () => {
            const current = new AbortController();
            controller = current;
            const timeout = setTimeout(() => current.abort(), 60000);
            try {
                const params = new URLSearchParams({ num_strikes: String(numStrikes) });
                if (expiry) params.set("expiry", expiry);
                const response = await fetch(
                    `http://127.0.0.1:8000/api/signals/confluence?${params}`,
                    { signal: current.signal }
                );
                const result = await response.json();
                if (!response.ok) {
                    throw new Error(typeof result.detail === "string" ? result.detail : `Signal API error: ${response.status}`);
                }
                if (result.source !== "kite" || !Number.isFinite(result.quote_time) ||
                    !Number.isFinite(result.pcr) || !Number.isFinite(result.support) ||
                    !Number.isFinite(result.resistance) ||
                    !(result.score === null || Number.isFinite(result.score))) {
                    throw new Error("Invalid live signal response");
                }
                if (active) { setData(result); setError(""); setNow(Date.now()); }
            } catch (e) {
                if (active) setError(e instanceof Error && e.name === "AbortError"
                    ? "Signal request timed out. Check the backend."
                    : e instanceof Error ? e.message : "Signal data unavailable");
            } finally {
                clearTimeout(timeout);
                if (active) timer = setTimeout(load, 10000);
            }
        };

        void load();
        return () => { active = false; clearTimeout(timer); controller?.abort(); };
    }, [expiry, numStrikes]);

    useEffect(() => {
        const timer = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(timer);
    }, []);

    const fresh = !!data && !error && data.status === "fresh" && now / 1000 - data.quote_time <= 30;
    const pcrClass = data?.pcr_bias === "Bullish" ? "good" : data?.pcr_bias === "Bearish" ? "bad" : "pending";
    const scoreClass = data?.score != null && data.score >= 65 ? "good" : data?.score != null && data.score <= 35 ? "bad" : "pending";
    const factors = [
        ["Option Chain OI", fresh ? "✓" : "●", data ? `${data.pcr_bias} (${data.pcr.toFixed(2)})` : "Unavailable", fresh ? pcrClass : "pending"],
        ["Support / Res", fresh ? "✓" : "●", data ? `S: ${data.support} | R: ${data.resistance}` : "Unavailable", fresh ? "good" : "pending"],
        ["A/B Score", fresh && data?.score != null ? String(data.score) : "—", data ? fresh ? data.trend : "Stale · withheld" : "Pending", fresh ? scoreClass : "pending"],
        ["Price Action", fresh && data?.price_action_direction ? "✓" : "●", data ? data.price_action : "Unavailable", fresh && data ? data.price_action_direction > 0 ? "good" : data.price_action_direction < 0 ? "bad" : "pending" : "pending"],
    ];

    const description = fresh && data
        ? `Dynamic Confluence: PCR is ${data.pcr.toFixed(2)} (${data.pcr_bias}). Support at ${data.support}, Resistance at ${data.resistance}.`
        : error || (data ? `Last-known measurements shown. ${data.warning || "Quotes are older than 30 seconds."} Waiting for fresh data.` : "Loading live option OI and price data…");
    const foot = data
        ? `Kite · ${data.expiry} · ${data.strike_min}–${data.strike_max} · ${new Date(data.quote_time * 1000).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })} IST · ${fresh ? "Rule-based score" : "STALE · score withheld"}`
        : "Live factor evaluation unavailable; no sample values displayed.";

    // Same elements and CSS classes as the original panel.
    return <section className="panel signal">
        <div className="panel-title"><span><BrainCircuit size={15} />AI MULTI-FACTOR SIGNAL</span></div>
        <div className="factor-grid">
            {factors.map(f => <div className="factor" key={f[0]}><span>{f[0]}</span><b className={f[3]}>{f[1]}</b><small className={f[3]}>{f[2]}</small></div>)}
        </div>
        <div className="signal-result" role="status">
            <strong>{fresh && data ? data.recommendation : data ? "WAIT — DATA STALE" : "WAIT — DATA UNAVAILABLE"}</strong>
            <p>{description}</p>
        </div>
        <div className="muted tiny">{foot}</div>
    </section>;
}
