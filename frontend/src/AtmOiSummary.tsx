
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
    symbol?: string;
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
    symbol = "NIFTY",
    expiry = "",
    spotChange,
}: {
    symbol?: string;
    expiry?: string;
    spotChange?: number | null;
}) {
    const [data, setData] = useState<Chain | null>(null);
    const [error, setError] = useState("");
    const [now, setNow] = useState(Date.now());

    // Update stale-data timer.
    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 1000);
        return () => clearInterval(id);
    }, []);

    // Fetch ATM option-chain values for the selected market.
    useEffect(() => {
        let active = true;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let controller: AbortController | undefined;

        setData(null);
        setError("");

        const load = async () => {
            const requestController = new AbortController();
            controller = requestController;

            const timeout = setTimeout(() => {
                requestController.abort();
            }, 25000);

            try {
                const url = new URL(
                    apiUrl("/api/options/chain"),
                    window.location.origin
                );

                // Selected market from the Option Chain buttons.
                url.searchParams.set("symbol", symbol);

                // Fetch ATM and nearby strikes.
                url.searchParams.set("num_strikes", "3");

                // Keep the selected expiry.
                if (expiry) {
                    url.searchParams.set("expiry", expiry);
                }

                const res = await fetch(url.toString(), {
                    signal: requestController.signal,
                });

                const body = await res.json();

                if (!res.ok) {
                    throw new Error(
                        typeof body.detail === "string"
                            ? body.detail
                            : "OI unavailable"
                    );
                }

                if (
                    !Array.isArray(body.strikes) ||
                    typeof body.atm_strike !== "number"
                ) {
                    throw new Error("Invalid option-chain response");
                }

                // Avoid displaying data from a previous market.
                if (
                    active &&
                    (!body.symbol ||
                        body.symbol.toUpperCase() === symbol.toUpperCase())
                ) {
                    setData(body);
                    setError("");
                } else if (
                    active &&
                    body.symbol &&
                    body.symbol.toUpperCase() !== symbol.toUpperCase()
                ) {
                    throw new Error(
                        `Backend returned ${body.symbol} instead of ${symbol}`
                    );
                }
            } catch (e) {
                if (active) {
                    setData(null);
                    setError(
                        e instanceof Error
                            ? e.name === "AbortError"
                                ? "Option-chain request timed out"
                                : e.message
                            : "OI unavailable"
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
    }, [symbol, expiry]);

    // Find the ATM strike for the selected market.
    const row = data?.strikes.find((r) => r.is_atm);

    const stale =
        !!data &&
        (
            data.status !== "fresh" ||
            now / 1000 - data.spot_quote_at > 90
        );

    const sides = [
        {
            label: "CE",
            oi: row?.call_oi_formatted,
            ltp: row?.call_ltp,
            change: row?.call_oi_chg,
            pct: row?.call_oi_pct_chg,
            baseline: row?.call_baseline_at,
            sideColor: "#00d6a3",
        },
        {
            label: "PE",
            oi: row?.put_oi_formatted,
            ltp: row?.put_ltp,
            change: row?.put_oi_chg,
            pct: row?.put_oi_pct_chg,
            baseline: row?.put_baseline_at,
            sideColor: "#ff4566",
        },
    ];

    return (
        <div
            className="market-card atm-oi-card"
            title={
                error ||
                `${symbol} ATM OI · ${data?.selected_expiry || expiry} · Previous-session OI baseline`
            }
            style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                boxSizing: "border-box",
                overflow: "hidden",
            }}
        >
            {/* LEFT: ATM STRIKE AND SPOT */}
            <div
                style={{
                    flex: "0 0 38%",
                    minWidth: 0,
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "center",
                    gap: 4,
                }}
            >
                <div
                    style={{
                        fontSize: 9,
                        color: "#87a1b5",
                        fontWeight: 700,
                        whiteSpace: "nowrap",
                    }}
                >
                    ATM {stale ? "· STALE" : ""}
                </div>

                <div
                    style={{
                        fontSize: 18,
                        fontWeight: 800,
                        color: "#f1f6fc",
                        lineHeight: 1.1,
                        whiteSpace: "nowrap",
                    }}
                >
                    {data?.atm_strike?.toLocaleString("en-IN") ?? "—"}
                </div>

                <div
                    style={{
                        fontSize: 10,
                        color: color(spotChange),
                        whiteSpace: "nowrap",
                    }}
                >
                    Spot{" "}
                    {spotChange == null
                        ? "—"
                        : `${spotChange > 0 ? "+" : ""}${spotChange.toFixed(2)}%`}
                </div>
            </div>

            {/* RIGHT: CE ABOVE, PE BELOW */}
            <div
                style={{
                    flex: 1,
                    minWidth: 0,
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "center",
                    gap: 5,
                    borderLeft: "1px solid #1b3447",
                    paddingLeft: 8,
                }}
            >
                {sides.map((side) => (
                    <div
                        key={side.label}
                        style={{
                            display: "flex",
                            flexDirection: "column",
                            gap: 2,
                            minWidth: 0,
                        }}
                    >
                        <div
                            style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                gap: 3,
                            }}
                        >
                            <strong
                                style={{
                                    fontSize: 10,
                                    color: side.sideColor,
                                }}
                            >
                                {side.label}
                            </strong>

                            <span
                                style={{
                                    fontSize: 10,
                                    color: "#e6f0fb",
                                    fontWeight: 600,
                                    whiteSpace: "nowrap",
                                }}
                            >
                                {side.oi || "—"}
                            </span>
                        </div>

                        <div
                            style={{
                                display: "flex",
                                justifyContent: "space-between",
                                gap: 3,
                                fontSize: 9,
                                whiteSpace: "nowrap",
                                color: "#87a1b5",
                            }}
                        >
                            <span>
                                LTP {side.ltp?.toFixed(2) ?? "—"}
                            </span>

                            <span
                                style={{
                                    color: color(side.change),
                                }}
                                title={`Previous-session baseline: ${side.baseline || "unavailable"}`}
                            >
                                {side.change == null
                                    ? "Δ —"
                                    : `${side.change > 0 ? "+" : ""}${quantity(side.change)}`}
                            </span>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
