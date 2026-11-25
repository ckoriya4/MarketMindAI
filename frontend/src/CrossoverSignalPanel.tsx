
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
        {
            change_pct?: number | null;
            sector?: string;
        }
    >;
}

type FilterStatus = "PASS" | "FAIL" | "WAITING";

interface DirectionalFilter {
    name: string;
    detail: string;
    call: FilterStatus;
    put: FilterStatus;
}

interface DirectionResult {
    passed: number;
    failed: number;
    waiting: number;
    ready: boolean;
}

const getNumber = (value: unknown): number | null => {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    const number = Number(value);
    return Number.isFinite(number) ? number : null;
};

const normalizeName = (value: string): string =>
    value.toUpperCase().replace(/[^A-Z0-9]/g, "");

const findStockChange = (
    metadata: Props["stockMetadata"],
    stockName: string
): number | null => {
    const target = normalizeName(stockName);

    const matchingKey = Object.keys(metadata).find(
        (key) => normalizeName(key) === target
    );

    if (!matchingKey) return null;

    return getNumber(metadata[matchingKey]?.change_pct);
};

const getStatus = (
    condition: boolean | null
): FilterStatus => {
    if (condition === null) return "WAITING";
    return condition ? "PASS" : "FAIL";
};

const calculateDirection = (
    filters: DirectionalFilter[],
    direction: "call" | "put"
): DirectionResult => {
    const statuses = filters.map((filter) => filter[direction]);

    const passed = statuses.filter(
        (status) => status === "PASS"
    ).length;

    const failed = statuses.filter(
        (status) => status === "FAIL"
    ).length;

    const waiting = statuses.filter(
        (status) => status === "WAITING"
    ).length;

    return {
        passed,
        failed,
        waiting,
        ready: waiting === 0 && passed >= 3,
    };
};

export default function CrossoverSignalPanel({
    stats,
    chain,
    stocks,
    stockMetadata,
}: Props) {
    const result = useMemo(() => {
        /*
         * 1. TOP-WEIGHTED STOCKS
         * CALL: HDFC Bank, Reliance and ICICI Bank all positive.
         * PUT: all three negative.
         */
        const topStocks = [
            "HDFCBANK",
            "RELIANCE",
            "ICICIBANK",
        ];

        const topStockChanges = topStocks.map((name) =>
            findStockChange(stockMetadata, name)
        );

        const topStocksAvailable = topStockChanges.every(
            (value) => value !== null
        );

        const allTopStocksPositive = topStocksAvailable
            ? topStockChanges.every((value) => value! > 0)
            : null;

        const allTopStocksNegative = topStocksAvailable
            ? topStockChanges.every((value) => value! < 0)
            : null;

        /*
         * 2. ADVANCE / DECLINE
         * CALL: advances >= 35.
         * PUT: declines >= 35.
         */
        const stockNames = [
            ...new Set(
                (stocks || [])
                    .flat()
                    .filter(
                        (name): name is string =>
                            typeof name === "string" &&
                            name.trim().length > 0
                    )
            ),
        ];

        const stockChanges = stockNames
            .map((name) => findStockChange(stockMetadata, name))
            .filter(
                (value): value is number => value !== null
            );

        const advances = stockChanges.filter(
            (value) => value > 0
        ).length;

        const declines = stockChanges.filter(
            (value) => value < 0
        ).length;

        const breadthAvailable = stockChanges.length > 0;

        const advanceCondition = breadthAvailable
            ? advances >= 35
            : null;

        const declineCondition = breadthAvailable
            ? declines >= 35
            : null;

        /*
         * 3. MFI
         * CALL: strictly above 50 and below 70.
         * PUT: strictly above 30 and below 50.
         */
        const mfi = getNumber(stats?.mfi14);

        const callMfiCondition =
            mfi === null ? null : mfi > 50 && mfi < 70;

        const putMfiCondition =
            mfi === null ? null : mfi > 30 && mfi < 50;

        /*
         * 4. PVT CROSSOVER
         * CALL: previous PVT <= previous EMA9 and current PVT > current EMA9.
         * PUT: previous PVT >= previous EMA9 and current PVT < current EMA9.
         *
         * Requires previous values from the chart API.
         */
        const pvt = getNumber(stats?.pvt);
        const pvtSignalLine = getNumber(stats?.pvt_signal_line);

        const previousPvt = getNumber(stats?.pvt_previous);
        const previousPvtSignalLine = getNumber(
            stats?.pvt_signal_line_previous
        );

        const pvtValuesAvailable =
            pvt !== null &&
            pvtSignalLine !== null &&
            previousPvt !== null &&
            previousPvtSignalLine !== null;

        const callPvtCondition = pvtValuesAvailable
            ? previousPvt! <= previousPvtSignalLine! &&
            pvt! > pvtSignalLine!
            : null;

        const putPvtCondition = pvtValuesAvailable
            ? previousPvt! >= previousPvtSignalLine! &&
            pvt! < pvtSignalLine!
            : null;

        /*
         * 5. VWAP
         * CALL: selected contract price above VWAP.
         * PUT: selected contract price below VWAP.
         */
        const ltp = getNumber(stats?.ltp);
        const vwap = getNumber(stats?.vwap);

        const vwapAvailable = ltp !== null && vwap !== null;

        const callVwapCondition = vwapAvailable
            ? ltp! > vwap!
            : null;

        const putVwapCondition = vwapAvailable
            ? ltp! < vwap!
            : null;

        /*
         * 6. 15-MINUTE TREND
         * CALL: 15m EMA9 above EMA21.
         * PUT: 15m EMA9 below EMA21.
         */
        const trend15Ema9 = getNumber(stats?.trend15_ema9);
        const trend15Ema21 = getNumber(stats?.trend15_ema21);

        const trend15Available =
            trend15Ema9 !== null && trend15Ema21 !== null;

        const callTrendCondition = trend15Available
            ? trend15Ema9! > trend15Ema21!
            : null;

        const putTrendCondition = trend15Available
            ? trend15Ema9! < trend15Ema21!
            : null;

        const filters: DirectionalFilter[] = [
            {
                name: "Top-weighted stocks",
                detail:
                    "HDFC Bank, Reliance and ICICI Bank must all be positive for CALL or all negative for PUT.",
                call: getStatus(allTopStocksPositive),
                put: getStatus(allTopStocksNegative),
            },
            {
                name: "Advance / Decline",
                detail:
                    "At least 35 advances for CALL or at least 35 declines for PUT.",
                call: getStatus(advanceCondition),
                put: getStatus(declineCondition),
            },
            {
                name: "MFI",
                detail:
                    "CALL: MFI above 50 and below 70. PUT: MFI above 30 and below 50.",
                call: getStatus(callMfiCondition),
                put: getStatus(putMfiCondition),
            },
            {
                name: "PVT",
                detail:
                    "CALL: PVT crosses above EMA9. PUT: PVT crosses below EMA9.",
                call: getStatus(callPvtCondition),
                put: getStatus(putPvtCondition),
            },
            {
                name: "VWAP",
                detail:
                    "CALL: selected contract price above VWAP. PUT: selected contract price below VWAP.",
                call: getStatus(callVwapCondition),
                put: getStatus(putVwapCondition),
            },
            {
                name: "15-minute trend",
                detail:
                    "CALL: EMA9 above EMA21. PUT: EMA9 below EMA21.",
                call: getStatus(callTrendCondition),
                put: getStatus(putTrendCondition),
            },
        ];

        const call = calculateDirection(filters, "call");
        const put = calculateDirection(filters, "put");

        /*
         * Final signal:
         * Only one direction must qualify.
         * Both qualifying or neither qualifying = HOLD.
         */
        let signal: "CALL BUY" | "PUT BUY" | "HOLD" = "HOLD";

        if (call.ready && !put.ready) {
            signal = "CALL BUY";
        } else if (put.ready && !call.ready) {
            signal = "PUT BUY";
        }

        /*
         * OI context
         */
        const strikes = chain?.strikes || [];

        const callOiChange = strikes.reduce(
            (total, item) =>
                total + (getNumber(item.call_oi_chg) ?? 0),
            0
        );

        const putOiChange = strikes.reduce(
            (total, item) =>
                total + (getNumber(item.put_oi_chg) ?? 0),
            0
        );

        const aggregateStatus = (
            filter: DirectionalFilter
        ): FilterStatus => {
            if (
                filter.call === "PASS" ||
                filter.put === "PASS"
            ) {
                return "PASS";
            }

            if (
                filter.call === "WAITING" ||
                filter.put === "WAITING"
            ) {
                return "WAITING";
            }

            return "FAIL";
        };

        const activeDirection =
            signal === "CALL BUY"
                ? call
                : signal === "PUT BUY"
                    ? put
                    : null;

        const score = activeDirection
            ? activeDirection.passed
            : Math.max(call.passed, put.passed);

        return {
            filters,
            call,
            put,
            signal,
            score,
            advances,
            declines,
            callOiChange,
            putOiChange,
            aggregateStatus,
        };
    }, [stats, chain, stocks, stockMetadata]);

    const signalClass =
        result.signal === "CALL BUY"
            ? "call"
            : result.signal === "PUT BUY"
                ? "put"
                : "hold";

    const activeDirection =
        result.signal === "CALL BUY"
            ? result.call
            : result.signal === "PUT BUY"
                ? result.put
                : null;

    return (
        <section className="panel crossover-signal-panel">
            <div className="panel-header">
                <div>
                    <h3>Crossover Signal</h3>
                    <span className="panel-subtitle">
                        Six directional confirmation filters
                    </span>
                </div>

                <div className={`trade-signal ${signalClass}`}>
                    <span className="signal-label">
                        {result.signal}
                    </span>

                    <span className="signal-score">
                        {result.score}/6
                    </span>
                </div>
            </div>

            <div className="signal-summary">
                <div className="signal-summary-item">
                    <span>CALL BUY</span>
                    <strong>
                        {result.call.passed}/6
                    </strong>
                    <small>
                        {result.call.waiting > 0
                            ? `${result.call.waiting} waiting`
                            : result.call.ready
                                ? "Qualified"
                                : "Not qualified"}
                    </small>
                </div>

                <div className="signal-summary-item">
                    <span>PUT BUY</span>
                    <strong>
                        {result.put.passed}/6
                    </strong>
                    <small>
                        {result.put.waiting > 0
                            ? `${result.put.waiting} waiting`
                            : result.put.ready
                                ? "Qualified"
                                : "Not qualified"}
                    </small>
                </div>
            </div>

            <div className="crossover-filters">
                {result.filters.map((filter, index) => {
                    const status =
                        result.aggregateStatus(filter);

                    return (
                        <div
                            className="crossover-filter-row"
                            key={filter.name}
                        >
                            <div className="filter-number">
                                {index + 1}
                            </div>

                            <div className="filter-info">
                                <strong>{filter.name}</strong>
                                <small>{filter.detail}</small>

                                <div className="filter-direction-status">
                                    <span
                                        className={`filter-status ${filter.call.toLowerCase()}`}
                                    >
                                        CALL: {filter.call}
                                    </span>

                                    <span
                                        className={`filter-status ${filter.put.toLowerCase()}`}
                                    >
                                        PUT: {filter.put}
                                    </span>
                                </div>
                            </div>

                            <span
                                className={`filter-status ${status.toLowerCase()}`}
                            >
                                {status}
                            </span>
                        </div>
                    );
                })}
            </div>

            <div className="market-context">
                <div className="market-context-item">
                    <span>Advances</span>
                    <strong className="positive">
                        {result.advances}
                    </strong>
                </div>

                <div className="market-context-item">
                    <span>Declines</span>
                    <strong className="negative">
                        {result.declines}
                    </strong>
                </div>

                <div className="market-context-item">
                    <span>CALL OI Change</span>
                    <strong>
                        {result.callOiChange.toLocaleString(
                            "en-IN"
                        )}
                    </strong>
                </div>

                <div className="market-context-item">
                    <span>PUT OI Change</span>
                    <strong>
                        {result.putOiChange.toLocaleString(
                            "en-IN"
                        )}
                    </strong>
                </div>
            </div>

            <div className="crossover-footer">
                {result.signal === "HOLD" ? (
                    <span>
                        HOLD — directional conditions are not
                        uniquely confirmed.
                    </span>
                ) : (
                    <span>
                        {result.signal} —{" "}
                        {activeDirection?.passed ?? 0} of 6
                        directional filters passed.
                    </span>
                )}
            </div>
        </section>
    );
}
