
import { useMemo } from "react";
import type { ChartStats } from "./IndicatorCandleChart";

interface StrikeItem {
    call_oi_chg: number | null;
    put_oi_chg: number | null;
}

interface SignalChain {
    strikes: StrikeItem[];
}

interface Props {
    stats: ChartStats | null;
    chain: SignalChain | null;
    stocks: string[][];
    stockMetadata: Record<
        string,
        { change_pct?: number | null; sector?: string }
    >;
}

type FilterStatus = "PASS" | "FAIL" | "WAITING";

interface Filter {
    name: string;
    detail: string;
    status: FilterStatus;
}

export default function CrossoverSignalPanel({
    stats,
    chain,
    stocks,
    stockMetadata
}: Props) {
    const result = useMemo(() => {
        const getChange = (row: string[]) => {
            const metadataValue = stockMetadata[row[0]]?.change_pct;

            if (
                typeof metadataValue === "number" &&
                Number.isFinite(metadataValue)
            ) {
                return metadataValue;
            }

            const parsed = Number(
                String(row[2] ?? "").replace(/[%+,]/g, "").trim()
            );

            return Number.isFinite(parsed) ? parsed : null;
        };

        const validChanges = stocks
            .map(row => ({
                symbol: row[0],
                change: getChange(row)
            }))
            .filter(
                (row): row is { symbol: string; change: number } =>
                    row.change !== null
            );

        const advances = validChanges.filter(
            row => row.change > 0
        ).length;

        const declines = validChanges.filter(
            row => row.change < 0
        ).length;

        // Top-weighted stocks
        const leaders = ["HDFCBANK", "RELIANCE", "ICICIBANK"];

        const leaderRows = leaders.map(symbol =>
            validChanges.find(row =>
                row.symbol
                    .toUpperCase()
                    .replace(/[^A-Z]/g, "")
                    .includes(symbol)
            )
        );

        const leaderStatus: FilterStatus =
            leaderRows.every(Boolean)
                ? leaderRows.every(row => row!.change > 0)
                    ? "PASS"
                    : "FAIL"
                : "WAITING";

        // Advance / Decline
        const breadthStatus: FilterStatus =
            validChanges.length < 35
                ? "WAITING"
                : advances >= 35
                    ? "PASS"
                    : "FAIL";

        // MFI and PVT require indicator data not currently supplied.
        const mfi: FilterStatus = "WAITING";
        const pvt: FilterStatus = "WAITING";

        // VWAP
        const vwapStatus: FilterStatus =
            typeof stats?.ltp === "number" &&
                typeof stats?.vwap === "number" &&
                Number.isFinite(stats.vwap)
                ? stats.ltp > stats.vwap
                    ? "PASS"
                    : "FAIL"
                : "WAITING";

        // A separate 15-minute data feed is required.
        const trend15: FilterStatus = "WAITING";

        const filters: Filter[] = [
            {
                name: "Top-weighted stocks",
                detail:
                    leaderStatus === "WAITING"
                        ? "Waiting for HDFC Bank, Reliance and ICICI Bank quotes"
                        : leaderStatus === "PASS"
                            ? "HDFC Bank, Reliance and ICICI Bank are positive"
                            : "One or more of the three leading stocks are negative",
                status: leaderStatus
            },
            {
                name: "Advance / Decline",
                detail: `${advances} advances · ${declines} declines`,
                status: breadthStatus
            },
            {
                name: "Money Flow Index",
                detail: "MFI above 50 and below 70 required",
                status: mfi
            },
            {
                name: "Price Volume Trend",
                detail: "PVT upward slope required",
                status: pvt
            },
            {
                name: "VWAP",
                detail:
                    stats?.ltp != null && stats?.vwap != null
                        ? `Price ${stats.ltp.toFixed(2)} · VWAP ${stats.vwap.toFixed(2)}`
                        : "Waiting for price and VWAP",
                status: vwapStatus
            },
            {
                name: "15-minute trend",
                detail: "Waiting for separate 15-minute trend data",
                status: trend15
            }
        ];

        const passed = filters.filter(
            filter => filter.status === "PASS"
        ).length;

        const waiting = filters.filter(
            filter => filter.status === "WAITING"
        ).length;

        // WMA 8 / MA 8 direction
        const ma = stats?.ma8;
        const wma = stats?.wma8;

        const direction =
            typeof ma === "number" && typeof wma === "number"
                ? wma > ma
                    ? "CALL"
                    : wma < ma
                        ? "PUT"
                        : "WAIT"
                : "WAIT";

        // OI changes are displayed as market context.
        const callOiChange = chain?.strikes.reduce(
            (sum, strike) =>
                sum +
                (typeof strike.call_oi_chg === "number"
                    ? strike.call_oi_chg
                    : 0),
            0
        );

        const putOiChange = chain?.strikes.reduce(
            (sum, strike) =>
                sum +
                (typeof strike.put_oi_chg === "number"
                    ? strike.put_oi_chg
                    : 0),
            0
        );

        const oiAvailable = Boolean(
            chain?.strikes.some(
                strike =>
                    strike.call_oi_chg !== null ||
                    strike.put_oi_chg !== null
            )
        );

        return {
            filters,
            passed,
            waiting,
            direction,
            callOiChange,
            putOiChange,
            oiAvailable,
            advances,
            declines
        };
    }, [stats, chain, stocks, stockMetadata]);

    const strength =
        result.passed >= 5
            ? "VERY STRONG"
            : result.passed >= 3
                ? "MEDIUM"
                : "WEAK / WAIT";

    const signalReady =
        result.waiting === 0 &&
        result.passed >= 3 &&
        result.direction !== "WAIT";

    const signal = signalReady
        ? result.direction
        : "NO TRADE";

    const signalColor =
        signal === "CALL"
            ? "#00d6a3"
            : signal === "PUT"
                ? "#ff4566"
                : "#f5b82e";

    return (
        <section className="panel crossover-signal-panel">
            <div className="panel-title">
                <span>
                    <i className="live-dot" />
                    NIFTY 50 WMA 8 / MA 8 CROSSOVER SIGNAL
                </span>
            </div>

            <div className="crossover-signal-main">
                <div
                    className="crossover-direction"
                    style={{
                        borderColor: signalColor
                    }}
                >
                    <small>TRADE SIGNAL</small>

                    <strong style={{ color: signalColor }}>
                        {signal}
                    </strong>

                    <span>{strength}</span>
                </div>

                <div className="crossover-score">
                    <small>FILTER SCORE</small>

                    <strong>
                        {result.passed} / 6
                    </strong>

                    <span>
                        {result.waiting} filters waiting
                    </span>
                </div>
            </div>

            <div className="crossover-filter-list">
                {result.filters.map((filter, index) => (
                    <div
                        className="crossover-filter-row"
                        key={filter.name}
                    >
                        <span className="crossover-filter-number">
                            {index + 1}
                        </span>

                        <div className="crossover-filter-info">
                            <strong>{filter.name}</strong>

                            <small>{filter.detail}</small>
                        </div>

                        <b
                            className={`crossover-filter-status ${filter.status.toLowerCase()}`}
                        >
                            {filter.status}
                        </b>
                    </div>
                ))}
            </div>

            <div className="crossover-market-context">
                <div>
                    <span>ADVANCES</span>

                    <strong className="positive">
                        {result.advances}
                    </strong>
                </div>

                <div>
                    <span>DECLINES</span>

                    <strong className="negative">
                        {result.declines}
                    </strong>
                </div>

                <div>
                    <span>CALL OI CHANGE</span>

                    <strong>
                        {result.oiAvailable
                            ? (result.callOiChange ?? 0).toLocaleString("en-IN")
                            : "—"}
                    </strong>
                </div>

                <div>
                    <span>PUT OI CHANGE</span>

                    <strong>
                        {result.oiAvailable
                            ? (result.putOiChange ?? 0).toLocaleString("en-IN")
                            : "—"}
                    </strong>
                </div>
            </div>

            <div className="crossover-signal-footer">
                5–6 PASS: Very Strong · 3–4 PASS: Medium · 0–2 PASS: Weak.
                Signal remains NO TRADE until all six filters have data.
            </div>
        </section>
    );
}
