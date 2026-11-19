
import { useEffect, useState } from "react";
import { apiUrl } from "./config/api";

interface Row {
    strike: number;
    is_atm: boolean;
    call_ltp: number | null;
    put_ltp: number | null;
    call_oi_formatted: string;
    put_oi_formatted: string;
    call_oi_chg: number | null;
    put_oi_chg: number | null;
    call_oi_pct_chg: number | null;
    put_oi_pct_chg: number | null;
    call_baseline_at?: string | null;
    put_baseline_at?: string | null;
}

interface Chain {
    atm_strike: number;
    selected_expiry: string;
    status: string;
    timestamp: string;
    strikes: Row[];
    spot_quote_at: number;
}

const color = (n: number | null | undefined) =>
    n == null || n === 0
        ? "#87a1b5"
        : n > 0
            ? "#00d6a3"
            : "#ff4566";

const quantity = (n: number) =>
    Math.abs(n) >= 1e7
        ? `${(n / 1e7).toFixed(2)}Cr`
        : `${(n / 1e5).toFixed(2)}L`;

export default function AtmOiSummary({
    expiry = "",
    spotChange,
}: {
    expiry?: string;
    spotChange?: number | null;
}) {
    const [data, setData] = useState<Chain | null>(null);
    const [error, setError] = useState("");
    const [now, setNow] = useState(Date.now());

    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(id);
    }, []);

    useEffect(() => {
        let active = true;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let controller: AbortController | undefined;

        setData(null);

        const load = async () => {
            controller = new AbortController();

            const timeout = setTimeout(() => {
                controller?.abort();
            }, 25000);

            try {
                const url = new URL(
                    apiUrl("/api/options/chain"),
                    window.location.origin
                );

                url.searchParams.set("num_strikes", "3");

                if (expiry) {
                    url.searchParams.set("expiry", expiry);
                }

                const res = await fetch(url, {
                    signal: controller.signal,
                });

                const body = await res.json();

                if (!res.ok) {
                    throw new Error(
                        typeof body.detail === "string"
                            ? body.detail
                            : "OI unavailable"
                    );
                }

                if (active) {
                    setData(body);
                    setError("");
                }
            } catch (e) {
                if (active) {
                    setData(null);
                    setError(
                        e instanceof Error ? e.message : "OI unavailable"
                    );
                }
            } finally {
                clearTimeout(timeout);

                if (active) {
                    timer = setTimeout(load, 6000);
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

    const row = data?.strikes.find((r) => r.is_atm);

    const stale =
        !!data &&
        (data.status !== "fresh" ||
            now / 1000 - data.spot_quote_at > 90);

    return (
        <div
            className="market-status"
            style={{ gap: 5 }}
            title={
                error ||
                "Actual Kite ATM quotes. OI change compared to previous trading-session close."
            }
        >
            <span className="muted tiny">
                ATM Strike{stale ? " · STALE" : ""}
            </span>

            <strong>{data?.atm_strike ?? "—"}</strong>

            <span style={{ color: color(spotChange) }}>
                Spot{" "}
                {spotChange == null
                    ? "—"
                    : `${spotChange > 0 ? "+" : ""}${spotChange.toFixed(2)}%`}
            </span>

            <div
                style={{
                    width: "100%",
                    borderTop: "1px solid #1b3447",
                    paddingTop: 5,
                    fontSize: 10,
                    textAlign: "left",
                }}
            >
                <div className="muted tiny">
                    {data?.selected_expiry || "Loading expiry…"}
                </div>

                {(["call", "put"] as const).map((side) => {
                    const change = row?.[`${side}_oi_chg`];
                    const pct = row?.[`${side}_oi_pct_chg`];
                    const baseline = row?.[`${side}_baseline_at`];

                    return (
                        <div
                            key={side}
                            style={{
                                display: "flex",
                                justifyContent: "space-between",
                                gap: 6,
                                flexWrap: "wrap",
                                marginTop: 4,
                            }}
                        >
                            <span>
                                {side === "call" ? "CE" : "PE"} OI{" "}
                                {row?.[`${side}_oi_formatted`] || "—"} · LTP{" "}
                                {row?.[`${side}_ltp`]?.toFixed(2) ?? "—"}
                            </span>

                            <span
                                style={{ color: color(change) }}
                                title={`Previous-session baseline: ${baseline || "loading/unavailable"
                                    }`}
                            >
                                {change == null
                                    ? "Δ —"
                                    : `${change > 0 ? "↑ +" : change < 0 ? "↓ " : ""}${quantity(change)}`}{" "}
                                {pct == null
                                    ? "(—)"
                                    : `(${pct > 0 ? "+" : ""}${pct.toFixed(2)}%)`}
                            </span>
                        </div>
                    );
                })}

                <div className="muted tiny" style={{ marginTop: 5 }}>
                    {error ||
                        "OI Δ vs previous trading-session close; — = loading / unavailable."}
                </div>

                {data && (
                    <div className="muted tiny">
                        {new Date(data.timestamp).toLocaleTimeString("en-IN", {
                            timeZone: "Asia/Kolkata",
                            hour12: false,
                        })}{" "}
                        IST · Kite snapshot
                    </div>
                )}
            </div>
        </div>
    );
}
