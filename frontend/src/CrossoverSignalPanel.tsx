
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
    callStatus: FilterStatus;
    putStatus: FilterStatus;
}

export default function CrossoverSignalPanel({
    stats,
    chain,
    stocks,
    stockMetadata
}: Props) {

    const result = useMemo(() => {

        const getNumber = (value: unknown): number | null => {
            if (
                typeof value !== "number" ||
                !Number.isFinite(value)
            ) {
                return null;
            }

            return value;
        };

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
        // CALL: all three positive.
        // PUT: all three negative.
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

        const leadersAvailable = leaderRows.every(Boolean);

        const callLeaderStatus: FilterStatus =
            !leadersAvailable
                ? "WAITING"
                : leaderRows.every(row => row!.change > 0)
                    ? "PASS"
                    : "FAIL";

        const putLeaderStatus: FilterStatus =
            !leadersAvailable
                ? "WAITING"
                : leaderRows.every(row => row!.change < 0)
                    ? "PASS"
                    : "FAIL";

        // --------------------------------------------------
        // 2. ADVANCE / DECLINE
        // CALL: advances >= 35.
        // PUT: declines >= 35.
        // --------------------------------------------------

        const breadthAvailable = validChanges.length >= 35;

        const callBreadthStatus: FilterStatus =
            !breadthAvailable
                ? "WAITING"
                : advances >= 35
                    ? "PASS"
                    : "FAIL";

        const putBreadthStatus: FilterStatus =
            !breadthAvailable
                ? "WAITING"
                : declines >= 35
                    ? "PASS"
                    : "FAIL";

        // --------------------------------------------------
        // 3. MONEY FLOW INDEX
        // CALL: MFI > 50 and < 70.
        // PUT: MFI > 30 and < 50.
        // --------------------------------------------------

        const mfiValue = getNumber(stats?.mfi14);

        const mfiSignal =
            typeof stats?.mfi_signal === "string"
                ? stats.mfi_signal.toUpperCase()
                : null;

        const callMfiStatus: FilterStatus =
            mfiValue === null
                ? "WAITING"
                : mfiValue > 50 && mfiValue < 70
                    ? "PASS"
                    : "FAIL";

        const putMfiStatus: FilterStatus =
            mfiValue === null
                ? "WAITING"
                : mfiValue > 30 && mfiValue < 50
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
            } else if (mfiValue <= 30) {
                zone = "Below preferred range";
            } else if (mfiValue < 50) {
                zone = "PUT range";
            } else if (mfiValue < 70) {
                zone = "CALL range";
            } else {
                zone = "Outside preferred range";
            }

            mfiDetail =
                `MFI ${mfiValue.toFixed(2)} · ${zone}`;

            if (
                mfiSignal &&
                mfiSignal !== "UNAVAILABLE"
            ) {
                mfiDetail += ` · ${mfiSignal}`;
            }

            mfiDetail += " · CALL: 50–70 · PUT: 30–50";
        }

        // --------------------------------------------------
        // 4. PRICE VOLUME TREND
        // CALL: PVT crosses above EMA9.
        // PUT: PVT crosses below EMA9.
        // --------------------------------------------------

        const pvtValue = getNumber(stats?.pvt);

        const pvtSignalLine = getNumber(
            stats?.pvt_signal_line
        );

        const previousPvt = getNumber(
            stats?.pvt_previous
        );

        const previousPvtSignalLine = getNumber(
            stats?.pvt_signal_line_previous
        );

        const pvtAvailable =
            pvtValue !== null &&
            pvtSignalLine !== null &&
            previousPvt !== null &&
            previousPvtSignalLine !== null;

        const callPvtStatus: FilterStatus =
            !pvtAvailable
                ? "WAITING"
                : previousPvt! <= previousPvtSignalLine! &&
                    pvtValue! > pvtSignalLine!
                    ? "PASS"
                    : "FAIL";

        const putPvtStatus: FilterStatus =
            !pvtAvailable
                ? "WAITING"
                : previousPvt! >= previousPvtSignalLine! &&
                    pvtValue! < pvtSignalLine!
                    ? "PASS"
                    : "FAIL";

        let pvtDetail =
            "Waiting for actual PVT crossover data";

        if (pvtAvailable) {
            pvtDetail =
                `PVT ${pvtValue!.toFixed(2)} · ` +
                `EMA9 ${pvtSignalLine!.toFixed(2)} · ` +
                "Crossover checked";
        } else if (pvtValue !== null) {
            pvtDetail =
                `PVT ${pvtValue.toFixed(2)} · Waiting for previous PVT values`;
        }

        // --------------------------------------------------
        // 5. VWAP
        // CALL: price above VWAP.
        // PUT: price below VWAP.
        // --------------------------------------------------

        const ltp = getNumber(stats?.ltp);
        const vwap = getNumber(stats?.vwap);

        const vwapAvailable =
            ltp !== null && vwap !== null;

        const callVwapStatus: FilterStatus =
            !vwapAvailable
                ? "WAITING"
                : ltp! > vwap!
                    ? "PASS"
                    : "FAIL";

        const putVwapStatus: FilterStatus =
            !vwapAvailable
                ? "WAITING"
                : ltp! < vwap!
                    ? "PASS"
                    : "FAIL";

        const vwapDetail =
            vwapAvailable
                ? `Price ${ltp!.toFixed(2)} · VWAP ${vwap!.toFixed(2)}`
                : "Waiting for actual contract price and VWAP";

        // --------------------------------------------------
        // 6. 15-MINUTE TREND
        // CALL: EMA9 > EMA21.
        // PUT: EMA9 < EMA21.
        // --------------------------------------------------

        const trend15Ema9 = getNumber(
            stats?.trend15_ema9
        );

        const trend15Ema21 = getNumber(
            stats?.trend15_ema21
        );

        const trend15Available =
            trend15Ema9 !== null &&
            trend15Ema21 !== null;

        const callTrendStatus: FilterStatus =
            !trend15Available
                ? "WAITING"
                : trend15Ema9! > trend15Ema21!
                    ? "PASS"
                    : "FAIL";

        const putTrendStatus: FilterStatus =
            !trend15Available
                ? "WAITING"
                : trend15Ema9! < trend15Ema21!
                    ? "PASS"
                    : "FAIL";

        // --------------------------------------------------
        // FILTERS
        // --------------------------------------------------

        const filters: Filter[] = [
            {
                name: "Top-weighted stocks",
                detail: leadersAvailable
                    ? "HDFC Bank, Reliance and ICICI Bank · All positive / all negative"
                    : "Waiting for HDFC Bank, Reliance and ICICI Bank quotes",
                callStatus: callLeaderStatus,
                putStatus: putLeaderStatus
            },
            {
                name: "Advance / Decline",
                detail: `${advances} advances · ${declines} declines · Required: 35`,
                callStatus: callBreadthStatus,
                putStatus: putBreadthStatus
            },
            {
                name: "Money Flow Index",
                detail: mfiDetail,
                callStatus: callMfiStatus,
                putStatus: putMfiStatus
            },
            {
                name: "Price Volume Trend",
                detail: pvtDetail,
                callStatus: callPvtStatus,
                putStatus: putPvtStatus
            },
            {
                name: "VWAP",
                detail: vwapDetail,
                callStatus: callVwapStatus,
                putStatus: putVwapStatus
            },
            {
                name: "15-minute trend",
                detail: trend15Available
                    ? `15m EMA9 ${trend15Ema9!.toFixed(2)} · EMA21 ${trend15Ema21!.toFixed(2)}`
                    : "Waiting for separate 15-minute trend confirmation",
                callStatus: callTrendStatus,
                putStatus: putTrendStatus
            }
        ];

        // --------------------------------------------------
        // DIRECTIONAL SCORES
        // --------------------------------------------------

        const callPassed = filters.filter(
            filter => filter.callStatus === "PASS"
        ).length;

        const putPassed = filters.filter(
            filter => filter.putStatus === "PASS"
        ).length;

        const callWaiting = filters.filter(
            filter => filter.callStatus === "WAITING"
        ).length;

        const putWaiting = filters.filter(
            filter => filter.putStatus === "WAITING"
        ).length;

        const callFailed = filters.filter(
            filter => filter.callStatus === "FAIL"
        ).length;

        const putFailed = filters.filter(
            filter => filter.putStatus === "FAIL"
        ).length;

        const callReady =
            callWaiting === 0 && callPassed >= 3;

        const putReady =
            putWaiting === 0 && putPassed >= 3;

        // --------------------------------------------------
        // FINAL SIGNAL
        // --------------------------------------------------

        let signal: "CALL BUY" | "PUT BUY" | "HOLD" = "HOLD";

        if (callReady && !putReady) {
            signal = "CALL BUY";
        } else if (putReady && !callReady) {
            signal = "PUT BUY";
        }

        const passed =
            signal === "CALL BUY"
                ? callPassed
                : signal === "PUT BUY"
                    ? putPassed
                    : Math.max(callPassed, putPassed);

        const waiting =
            signal === "CALL BUY"
                ? callWaiting
                : signal === "PUT BUY"
                    ? putWaiting
                    : Math.min(callWaiting, putWaiting);

        const failed =
            signal === "CALL BUY"
                ? callFailed
                : signal === "PUT BUY"
                    ? putFailed
                    : Math.max(callFailed, putFailed);

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
            signal,
            callPassed,
            putPassed,
            callWaiting,
            putWaiting,
            callReady,
            putReady,
            callOiChange,
            putOiChange,
            oiAvailable,
            advances,
            declines,
            mfiValue,
            mfiSignal,
            pvtValue,
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

    const signal = result.signal;

    const signalColor =
        signal === "CALL BUY"
            ? "#00d6a3"
            : signal === "PUT BUY"
                ? "#ff4566"
                : "#f5b82e";

    // --------------------------------------------------
    // UI - ORIGINAL DESIGN PRESERVED
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

                {result.filters.map((filter, index) => {
                    const status: FilterStatus =
                        filter.callStatus === "PASS" ||
                            filter.putStatus === "PASS"
                            ? "PASS"
                            : filter.callStatus === "WAITING" ||
                                filter.putStatus === "WAITING"
                                ? "WAITING"
                                : "FAIL";

                    const detail =
                        `${filter.detail} · CALL: ${filter.callStatus} · PUT: ${filter.putStatus}`;

                    return (
                        <div
                            className="crossover-filter-row"
                            key={filter.name}
                        >

                            <span className="crossover-filter-number">
                                {index + 1}
                            </span>

                            <div className="crossover-filter-info">
                                <strong>{filter.name}</strong>

                                <small>{detail}</small>
                            </div>

                            <b
                                className={`crossover-filter-status ${status.toLowerCase()}`}
                            >
                                {status}
                            </b>

                        </div>
                    );
                })}

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
                CALL BUY / PUT BUY requires at least 3 directional passes and all six filters available.
                HOLD when neither or both directions qualify.
                {result.failed > 0
                    ? ` · ${result.failed} filters failed.`
                    : ""}
            </div>

        </section>
    );
}
