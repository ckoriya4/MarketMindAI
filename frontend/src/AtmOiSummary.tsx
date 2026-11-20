
import { useEffect, useState } from "react";
import { apiUrl } from "./config/api";

interface AtmOiSummaryProps {
    symbol?: string;
    expiry?: string;
    spotChange?: number | null;
}

interface AtmOiData {
    symbol?: string;
    spot_price?: number;
    atm_strike?: number;
    selected_expiry?: string;
    call_oi?: number | null;
    put_oi?: number | null;
    call_ltp?: number | null;
    put_ltp?: number | null;
    call_oi_chg?: number | null;
    put_oi_chg?: number | null;
    pcr?: number | null;
}

export default function AtmOiSummary({
    symbol = "NIFTY",
    expiry = "",
    spotChange
}: AtmOiSummaryProps) {
    const [data, setData] = useState<AtmOiData | null>(null);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let active = true;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let controller: AbortController | undefined;

        const fetchAtmOi = async () => {
            const currentController = new AbortController();
            controller = currentController;

            try {
                const url = new URL(apiUrl("/api/options/chain"));

                // Fetch data for the currently selected market.
                url.searchParams.set("symbol", symbol);
                url.searchParams.set("num_strikes", "3");

                if (expiry) {
                    url.searchParams.set("expiry", expiry);
                }

                const response = await fetch(url.toString(), {
                    signal: currentController.signal
                });

                const result = await response.json();

                if (!active) return;

                if (!response.ok) {
                    throw new Error(
                        typeof result.detail === "string"
                            ? result.detail
                            : "ATM OI data unavailable"
                    );
                }

                setData(result);
                setError("");
            } catch (err) {
                if (!active) return;

                if (err instanceof Error && err.name !== "AbortError") {
                    setError(err.message);
                }
            } finally {
                if (active) {
                    setLoading(false);

                    // Refresh selected market data every 5 seconds.
                    timer = setTimeout(fetchAtmOi, 5000);
                }
            }
        };

        // Clear previous market data when market or expiry changes.
        setData(null);
        setError("");
        setLoading(true);

        void fetchAtmOi();

        return () => {
            active = false;
            clearTimeout(timer);
            controller?.abort();
        };
    }, [symbol, expiry]);

    const formatValue = (value: number | null | undefined) => {
        if (value == null || !Number.isFinite(value)) return "—";
        return value.toLocaleString("en-IN");
    };

    const formatPrice = (value: number | null | undefined) => {
        if (value == null || !Number.isFinite(value)) return "—";
        return value.toFixed(2);
    };

    const formatChange = (value: number | null | undefined) => {
        if (value == null || !Number.isFinite(value)) return "—";

        return `${value > 0 ? "+" : ""}${value.toLocaleString("en-IN")}`;
    };

    return (
        <div className="atm-oi-summary">
            <div className="atm-oi-header">
                <strong>ATM OI SUMMARY — {symbol}</strong>
                <span>{data?.selected_expiry || expiry || "Nearest Expiry"}</span>
            </div>

            {loading && !data ? (
                <div className="muted tiny">Loading {symbol} ATM OI...</div>
            ) : error ? (
                <div className="muted tiny">{error}</div>
            ) : data ? (
                <>
                    <div className="atm-oi-price">
                        <span>Spot Price</span>
                        <strong>{formatPrice(data.spot_price)}</strong>
                        {spotChange != null && (
                            <span className={spotChange >= 0 ? "positive" : "negative"}>
                                {spotChange > 0 ? "+" : ""}
                                {spotChange.toFixed(2)}
                            </span>
                        )}
                    </div>

                    <div className="atm-oi-strike">
                        <span>ATM STRIKE</span>
                        <strong>{formatValue(data.atm_strike)}</strong>
                    </div>

                    <div className="atm-oi-grid">
                        <div>
                            <span>CALL OI</span>
                            <strong className="negative">
                                {formatValue(data.call_oi)}
                            </strong>
                            <small>LTP: {formatPrice(data.call_ltp)}</small>
                            <small>OI Change: {formatChange(data.call_oi_chg)}</small>
                        </div>

                        <div>
                            <span>PUT OI</span>
                            <strong className="positive">
                                {formatValue(data.put_oi)}
                            </strong>
                            <small>LTP: {formatPrice(data.put_ltp)}</small>
                            <small>OI Change: {formatChange(data.put_oi_chg)}</small>
                        </div>
                    </div>

                    <div className="atm-oi-pcr">
                        <span>PCR</span>
                        <strong>{formatPrice(data.pcr)}</strong>
                    </div>
                </>
            ) : (
                <div className="muted tiny">ATM OI data unavailable</div>
            )}
        </div>
    );
}
