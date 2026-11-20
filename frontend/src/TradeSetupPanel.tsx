
import { useEffect, useState } from "react";
import "./TradeSetupPanel.css";
import { apiUrl } from "./config/api";

interface Check {
    name: string;
    weight: number;
    passed: boolean | null;
    detail: string;
}

interface Card {
    base_score?: number | null;
    risk_fit_pct?: number | null;
    matched_weight?: number;
    excluded_checks?: string[];
    partial?: boolean;
    action: string;
    score: number | null;
    known_weight: number;
    missing_weight: number;
    status: string;
    color: string;
    blockers: string[];
    checks: Check[];
    execution: {
        max_loss: number | null;
        lot_size?: number;
        legs: {
            side: string;
            strike: number;
            type: string;
            price: number | null;
        }[];
    };
}

interface Data {
    status: string;
    quote_time?: number;
    expiry: string;
    indicator_instrument: string;
    symbol?: string;
    cards: Card[];
    note: string;
}

interface TradeSetupPanelProps {
    expiry?: string;
    selectedMarket?: string;
}

const names = [
    "CALL BUY",
    "PUT BUY",
    "CALL SELL",
    "PUT SELL"
];

const marketNames: Record<string, string> = {
    NIFTY: "NIFTY 50",
    BANKNIFTY: "BANK NIFTY",
    FINNIFTY: "FINNIFTY",
    MIDCPNIFTY: "MIDCPNIFTY",
    NIFTYNXT50: "NIFTY NEXT 50",
    SENSEX: "SENSEX",
    BANKEX: "BANKEX"
};

export default function TradeSetupPanel({
    expiry = "",
    selectedMarket = "NIFTY"
}: TradeSetupPanelProps) {

    const [data, setData] = useState<Data | null>(null);
    const [error, setError] = useState("");
    const [budget, setBudget] = useState("");
    const [now, setNow] = useState(Date.now());
    const [loading, setLoading] = useState(true);

    const marketLabel =
        marketNames[selectedMarket] || selectedMarket;

    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 1000);

        return () => clearInterval(id);
    }, []);

    // FETCH SETUPS FOR SELECTED MARKET
    useEffect(() => {

        let active = true;

        let timer: ReturnType<typeof setTimeout> | undefined;

        let controller: AbortController | undefined;

        // Clear previous market data immediately
        setData(null);
        setError("");
        setLoading(true);

        const load = async () => {

            controller = new AbortController();

            const timeout = setTimeout(
                () => controller?.abort(),
                60000
            );

            try {

                const q = new URLSearchParams();

                // Selected Kite market
                q.set("symbol", selectedMarket);

                if (expiry) {
                    q.set("expiry", expiry);
                }

                if (Number(budget) > 0) {
                    q.set("risk_budget", budget);
                }

                const r = await fetch(
                    `${apiUrl("/api/signals/trade-setups")}?${q.toString()}`,
                    {
                        signal: controller.signal
                    }
                );

                const result = await r.json();

                if (!r.ok) {
                    throw new Error(
                        typeof result.detail === "string"
                            ? result.detail
                            : "Setup inputs unavailable"
                    );
                }

                // Avoid showing another market's response
                if (
                    result.symbol &&
                    result.symbol.toUpperCase() !==
                    selectedMarket.toUpperCase()
                ) {
                    throw new Error("Selected market response mismatch");
                }

                if (active) {
                    setData(result);
                    setError("");
                    setLoading(false);
                }

            } catch (e) {

                if (active) {

                    setData(null);

                    setError(
                        e instanceof Error
                            ? e.message
                            : "Setup data unavailable"
                    );

                    setLoading(false);
                }

            } finally {

                clearTimeout(timeout);

                if (active) {
                    timer = setTimeout(load, 10000);
                }
            }
        };

        const debounce = setTimeout(
            () => void load(),
            400
        );

        return () => {

            active = false;

            clearTimeout(debounce);
            clearTimeout(timer);

            controller?.abort();
        };

    }, [expiry, budget, selectedMarket]);

    // LIVE DATA VALIDATION
    const fresh =
        !error &&
        data?.status === "fresh" &&
        data.quote_time != null &&
        now / 1000 - data.quote_time <= 90;

    return (
        <section className="panel trade-action-panel">

            <div className="panel-title">
                OPTION BUY / SELL · SETUP SCORES
                <span
                    style={{
                        marginLeft: 6,
                        color: "#00d6a3",
                        fontSize: 10
                    }}
                >
                    · {marketLabel}
                </span>
            </div>

            <label className="action-budget">
                Maximum loss budget ₹

                <input
                    type="number"
                    min="1"
                    step="100"
                    placeholder="Set your limit"
                    value={budget}
                    onChange={e => setBudget(e.target.value)}
                />
            </label>

            <div className="action-score-grid">

                {names.map(name => {

                    const card = data?.cards.find(
                        c => c.action === name
                    );

                    const score = fresh
                        ? card?.score
                        : null;

                    return (
                        <article
                            key={name}
                            className={`action-score-card ${fresh
                                    ? card?.color || "red"
                                    : "red"
                                }`}
                        >

                            <strong>{name}</strong>

                            <b className="action-score">
                                {score == null
                                    ? "—"
                                    : `${score}%`}
                            </b>

                            <span>
                                {fresh
                                    ? card?.status || "NO TRADE"
                                    : loading
                                        ? "LOADING MARKET DATA"
                                        : "NO TRADE · DATA UNAVAILABLE"}
                            </span>

                            {card && <>

                                <small>
                                    Coverage {card.known_weight}/100 ·{" "}
                                    {card.matched_weight ?? "—"}/
                                    {card.known_weight} available points matched ·{" "}
                                    {card.missing_weight} points excluded
                                </small>

                                <small>
                                    Base setup:{" "}
                                    {fresh && card.base_score != null
                                        ? `${card.base_score}%`
                                        : "—"}
                                    {" "}· Loss-limit fit:{" "}
                                    {card.risk_fit_pct == null
                                        ? "Set limit / loss unavailable"
                                        : `${card.risk_fit_pct}%`}
                                </small>

                                {card.partial && (
                                    <small>
                                        Partial checks only · excluded factors are not confirmed.
                                    </small>
                                )}

                                <details>

                                    <summary>
                                        Conditions / reasons
                                    </summary>

                                    <ul>
                                        {card.checks.map(c => (
                                            <li
                                                key={c.name}
                                                title={c.detail}
                                            >
                                                {c.passed === null
                                                    ? "?"
                                                    : c.passed
                                                        ? "✓"
                                                        : "×"}{" "}
                                                {c.name} · {c.weight} pts

                                                <small
                                                    style={{
                                                        display: "block"
                                                    }}
                                                >
                                                    {c.detail}
                                                </small>
                                            </li>
                                        ))}
                                    </ul>

                                    {card.excluded_checks?.length
                                        ? (
                                            <p>
                                                Excluded:{" "}
                                                {card.excluded_checks.join(", ")}
                                            </p>
                                        )
                                        : null
                                    }

                                    {card.blockers.map(b => (
                                        <p key={b}>{b}</p>
                                    ))}

                                    {card.execution.legs.map((l, i) => (
                                        <div key={i}>
                                            {l.side} {l.strike} {l.type} @{" "}
                                            {l.price == null
                                                ? "—"
                                                : l.price.toFixed(2)}
                                        </div>
                                    ))}

                                    <p>
                                        Estimated max loss / lot:{" "}
                                        {card.execution.max_loss == null
                                            ? "—"
                                            : `₹${card.execution.max_loss.toLocaleString("en-IN")}`}
                                        {" "}· excludes charges/slippage; margin not verified.
                                    </p>

                                </details>

                            </>}

                        </article>
                    );
                })}

            </div>

            <p className="action-panel-note">
                Displayed % = available-check agreement × loss-limit fit
                (when set); not profit probability. Raising the limit
                never boosts the score above its base. A failed loss
                limit still blocks the trade. SELL means opening a
                hedged credit spread, not exiting an existing position.
                No orders placed.
            </p>

            <p
                className="action-panel-note"
                role="status"
            >
                {error ||
                    (!data
                        ? `Loading ${marketLabel} market inputs…`
                        : !fresh
                            ? "Market data stale — no active setup."
                            : "Live snapshot · unavailable checks excluded from denominator; coverage disclosed.")}
            </p>

            {data && (
                <p className="action-panel-note">

                    Market: {marketLabel} ·{" "}

                    Expiry {data.expiry} ·{" "}

                    Indicators: {data.indicator_instrument} ·{" "}

                    Quote{" "}

                    {data.quote_time
                        ? new Date(
                            data.quote_time * 1000
                        ).toLocaleString("en-IN", {
                            timeZone: "Asia/Kolkata"
                        })
                        : "—"} IST.

                </p>
            )}

        </section>
    );
}
