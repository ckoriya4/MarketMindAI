
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
                String(row[2] ?? "")
                    .replace(/[%+,]/g, "")
                    .trim()
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

        // --------------------------------------------------
        // 1. TOP-WEIGHTED STOCKS
        // --------------------------------------------------

        const leaders = [
            "HDFCBANK",
            "RELIANCE",
            "ICICIBANK"
        ];

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

        // --------------------------------------------------
        // 2. ADVANCE / DECLINE
        // --------------------------------------------------

        const breadthStatus: FilterStatus =
            validChanges.length < 35
                ? "WAITING"
                : advances >= 35
                    ? "PASS"
                    : "FAIL";

        // --------------------------------------------------
        // 3. MONEY FLOW INDEX
        //
        // Actual MFI comes from chart_indicators.py.
        // Required range: strictly above 50 and below 70.
        // --------------------------------------------------

        const mfiValue =
            typeof stats?.mfi14 === "number" &&
                Number.isFinite(stats.mfi14)
                ? stats.mfi14
                : null;

        const mfiSignal =
            typeof stats?.mfi_signal === "string"
                ? stats.mfi_signal.toUpperCase()
                : null;

        const mfi: FilterStatus =
            mfiValue === null
                ? "WAITING"
                : mfiValue > 50 && mfiValue < 70
                    ? "PASS"
                    : "FAIL";

        let mfiDetail = "Waiting for actual MFI data";

        if (mfiValue !== null) {

            let zone = "";

            if (mfiValue >= 80) {
                zone = "Overbought";
            } else if (mfiValue >= 70) {
                zone = "Above preferred range";
            } else if (mfiValue <= 20) {
                zone = "Oversold";
            } else if (mfiValue <= 50) {
                zone = "Below preferred range";
            } else {
                zone = "Inside preferred range";
            }

            mfiDetail =
                `MFI ${mfiValue.toFixed(2)} · ${zone}`;

            if (
                mfiSignal &&
                mfiSignal !== "UNAVAILABLE"
            ) {
                mfiDetail += ` · ${mfiSignal}`;
            }

            mfiDetail += " · Required: 50–70";
        }

        // --------------------------------------------------
        // 4. PRICE VOLUME TREND
        //
        // Use actual PVT and backend-calculated PVT signal.
        // Positive PVT alone is NOT treated as bullish.
        // --------------------------------------------------

        const pvtValue =
            typeof stats?.pvt === "number" &&
                Number.isFinite(stats.pvt)
                ? stats.pvt
                : null;

        const pvtSignalLine =
            typeof stats?.pvt_signal_line === "number" &&
                Number.isFinite(stats.pvt_signal_line)
                ? stats.pvt_signal_line
                : null;

        const pvtSignal =
            typeof stats?.pvt_signal === "string"
                ? stats.pvt_signal.toUpperCase()
                : null;

        const pvtHasData =
            pvtValue !== null &&
            pvtSignalLine !== null &&
            pvtSignal !== null &&
            pvtSignal !== "UNAVAILABLE";

        let pvt: FilterStatus = "WAITING";

        if (pvtHasData) {

            if (
                pvtSignal === "BUY" ||
                pvtSignal === "BULLISH"
            ) {
                pvt = "PASS";
            } else {
                // SELL, BEARISH and NEUTRAL do not
                // satisfy the required upward PVT condition.
                pvt = "FAIL";
            }
        }

        let pvtDetail = "Waiting for actual PVT and signal-line data";

        if (pvtHasData) {
            pvtDetail =
                `PVT ${pvtValue!.toFixed(2)} · ` +
                `Signal EMA9 ${pvtSignalLine!.toFixed(2)} · ` +
                `${pvtSignal}`;
        } else if (pvtValue !== null) {
            pvtDetail =
                `PVT ${pvtValue.toFixed(2)} · Waiting for signal confirmation`;
        }

        // --------------------------------------------------
        // 5. VWAP
        // --------------------------------------------------

        const vwapStatus: FilterStatus =
            typeof stats?.ltp === "number" &&
                Number.isFinite(stats.ltp) &&
                typeof stats?.vwap === "number" &&
                Number.isFinite(stats.vwap)
                ? stats.ltp > stats.vwap
                    ? "PASS"
                    : "FAIL"
                : "WAITING";

        const vwapDetail =
            typeof stats?.ltp === "number" &&
                typeof stats?.vwap === "number"
                ? `Price ${stats.ltp.toFixed(2)} · VWAP ${stats.vwap.toFixed(2)}`
                : "Waiting for actual futures price and VWAP";

        // --------------------------------------------------
        // 6. 15-MINUTE TREND
        //
        // Kept separate because this component currently
        // receives only the selected chart statistics.
        // --------------------------------------------------

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
                detail: mfiDetail,
                status: mfi
            },
            {
                name: "Price Volume Trend",
                detail: pvtDetail,
                status: pvt
            },
            {
                name: "VWAP",
                detail: vwapDetail,
                status: vwapStatus
            },
            {
                name: "15-minute trend",
                detail: "Waiting for separate 15-minute trend confirmation",
                status: trend15
            }
        ];

        // --------------------------------------------------
        // FILTER SCORE
        // --------------------------------------------------

        const passed = filters.filter(
            filter => filter.status === "PASS"
        ).length;

        const waiting = filters.filter(
            filter => filter.status === "WAITING"
        ).length;

        const failed = filters.filter(
            filter => filter.status === "FAIL"
        ).length;

        // --------------------------------------------------
        // WMA8 / MA8 DIRECTION
        // --------------------------------------------------

        const ma = stats?.ma8;
        const wma = stats?.wma8;

        const direction =
            typeof ma === "number" &&
                typeof wma === "number"
                ? wma > ma
                    ? "CALL"
                    : wma < ma
                        ? "PUT"
                        : "WAIT"
                : "WAIT";

        // --------------------------------------------------
        // OPEN INTEREST CONTEXT
        // --------------------------------------------------

        const callOiChange = chain?.strikes.reduce(
            (sum, strike) =>
                sum +
                (
                    typeof strike.call_oi_chg === "number"
                        ? strike.call_oi_chg
                        : 0
                ),
            0
        );

        const putOiChange = chain?.strikes.reduce(
            (sum, strike) =>
                sum +
                (
                    typeof strike.put_oi_chg === "number"
                        ? strike.put_oi_chg
                        : 0
                ),
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
            failed,
            direction,
            callOiChange,
            putOiChange,
            oiAvailable,
            advances,
            declines,
            mfiValue,
            mfiSignal,
            pvtValue,
            pvtSignal,
            pvtSignalLine
        };

    }, [stats, chain, stocks, stockMetadata]);

    // --------------------------------------------------
    // OVERALL SIGNAL STRENGTH
    // --------------------------------------------------

    const strength =
        result.passed >= 5
            ? "VERY STRONG"
            : result.passed >= 3
                ? "MEDIUM"
                : "WEAK / WAIT";

    // Preserve the existing NO TRADE condition:
    // all six filters must have data and at least
    // three must pass.
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

    // --------------------------------------------------
    // UI
    // --------------------------------------------------

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

                    <strong
                        style={{
                            color: signalColor
                        }}
                    >
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
                {result.failed > 0
                    ? ` · ${result.failed} filters failed.`
                    : ""}
            </div>

        </section>
    );
}
