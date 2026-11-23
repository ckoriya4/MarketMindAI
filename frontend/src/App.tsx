
import KiteLoginButton from "./KiteLoginButton";
import TradeSetupPanel from "./TradeSetupPanel";
import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import {
  Activity,
  Bell,
  BrainCircuit,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
  Volume2
} from "lucide-react";
import "./App.css";
import OISignalChart, { type OILiveSnapshot } from "./OISignalChart";
import SectorSummary from "./SectorSummary";
import LiveMarketStrip from "./LiveMarketStrip";
import { OfficialNewsPanel } from "./EnergyPanels";
import CrudeOilPanel from "./LiveCrudeOilPanel";
import LiveConfluencePanel from "./LiveConfluencePanel";
import WeightedSetupPanel from "./WeightedSetupPanel";
import IndicatorCandleChart from "./IndicatorCandleChart";
import { apiUrl } from "./config/api";

const navItems = [
  "Dashboard",
  "Option Chain",
  "Stock Scanner",
  "Charts",
  "Signals",
  "News & Events",
  "Settings"
];

// Supported market selector options.
// The backend must support each symbol before its data can load.
const optionMarkets = [
  { symbol: "NIFTY", label: "NIFTY 50" },
  { symbol: "BANKNIFTY", label: "BANK NIFTY" },
  { symbol: "FINNIFTY", label: "FINNIFTY" },
  { symbol: "MIDCPNIFTY", label: "MIDCPNIFTY" },
  { symbol: "NIFTYNXT50", label: "NIFTY NEXT 50" },
  { symbol: "SENSEX", label: "SENSEX" },
  { symbol: "BANKEX", label: "BANKEX" }
];

interface StrikeItem {
  strike: number;
  is_atm: boolean;
  is_resistance: boolean;
  is_support: boolean;
  call_ltp: number | null;
  call_oi: number | null;
  call_oi_formatted: string;
  call_oi_chg: number | null;
  call_oi_chg_formatted: string;
  call_oi_pct_chg: number | null;
  put_ltp: number | null;
  put_oi: number | null;
  put_oi_formatted: string;
  put_oi_chg: number | null;
  put_oi_chg_formatted: string;
  put_oi_pct_chg: number | null;
  strike_pcr: number | null;
  call_bar_pct: number;
  put_bar_pct: number;
}

interface OptionChainData {
  symbol: string;
  spot_price: number;
  atm_strike: number;
  selected_expiry: string;
  days_to_expiry?: number;
  available_expiries: string[];
  total_call_oi: string;
  total_put_oi: string;
  pcr: number | null;
  pcr_bias: string;
  resistance_strike: number | null;
  resistance_oi: string;
  support_strike: number | null;
  support_oi: string;
  ab_score: {
    score: number | null;
    trend: string;
    recommendation: string;
    color: string;
  };
  strikes: StrikeItem[];
  timestamp: string;
  data_mode: string;
  status?: string;
  oi_change_basis?: string;
  score_method?: string;
  level_scope?: string;
}

interface ChartIndicators {
  ltp: number;
  change: number | null;
  change_pct: number | null;
  ema9: number | null;
  ema21: number | null;
  ma8?: number | null;
  wma8?: number | null;
  vwap: number | null;
  rsi14: number | null;
  macd: string;
  instrument?: string;
}

function PanelTitle({
  children,
  icon
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="panel-title">
      <span>{icon}{children}</span>
    </div>
  );
}

export default function App() {
  const [active, setActive] = useState("Dashboard");
  const [search, setSearch] = useState("");
  const [timeframe, setTimeframe] = useState("5m");

  // Selected option-chain market
  const [selectedMarket, setSelectedMarket] = useState("NIFTY");

  const [tradeMode, setTradeMode] = useState("Manual");
  const [auto, setAuto] = useState(false);
  const [alerts, setAlerts] = useState(true);
  const [sound, setSound] = useState(true);
  const [notice, setNotice] = useState("");

  // Backend Dynamic Options States
  const [chainError, setChainError] = useState("");
  const chainRequest = useRef(0);
  const [chainData, setChainData] = useState<OptionChainData | null>(null);
  const [liveOi, setLiveOi] = useState<OILiveSnapshot | null>(null);
  const [selectedExpiry, setSelectedExpiry] = useState<string>("");
  const [strikeRange, setStrikeRange] = useState<number>(7);
  const [backendOnline, setBackendOnline] = useState<boolean>(false);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [candleStatus, setCandleStatus] = useState("Loading Kite candles…");
  const [chartIndicators, setChartIndicators] = useState<ChartIndicators | null>(null);

  // Scanner quotes
  const [stocks, setStocks] = useState<string[][]>([]);
  const [stockSnapshotAt, setStockSnapshotAt] = useState("");
  const [stockQuoteError, setStockQuoteError] = useState("");
  const [stockMetadata, setStockMetadata] = useState<
    Record<string, { sector?: string; change_pct?: number | null }>
  >({});
  const [scannerSector, setScannerSector] = useState("All Sectors");
  const [scannerSort, setScannerSort] = useState("Strongest");

  // Fetch live stock quotes
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    const fetchQuotes = async () => {
      const requestController = new AbortController();
      controller = requestController;
      const timeout = setTimeout(() => requestController.abort(), 25000);

      try {
        const response = await fetch(
          apiUrl("/api/market/quotes"),
          { signal: requestController.signal }
        );

        const data = await response.json();

        if (!response.ok) {
          throw new Error(
            typeof data.detail === "string"
              ? data.detail
              : `Stock API error: ${response.status}. Check /api/market/quotes in your browser.`
          );
        }

        if (
          !Array.isArray(data.quotes) ||
          data.quotes.length === 0 ||
          !data.quotes.every((row: unknown) =>
            Array.isArray(row) &&
            row.length === 8 &&
            row.every((value: unknown) => typeof value === "string")
          )
        ) {
          throw new Error("Stock API returned no valid scanner rows");
        }

        if (active) {
          setStocks(data.quotes);
          setStockMetadata(data.metadata || {});
          setStockSnapshotAt(data.fetched_at || new Date().toISOString());
          setStockQuoteError("");
        }
      } catch (error) {
        if (active) {
          const message =
            error instanceof Error && error.name === "AbortError"
              ? "Stock quote request timed out. Check the backend."
              : error instanceof Error
                ? error.message
                : "Stock quotes unavailable";

          setStockQuoteError(message);
          console.error("Scanner quotes failed:", error);
          setNotice(message);
        }
      } finally {
        clearTimeout(timeout);

        if (active) {
          timer = setTimeout(fetchQuotes, 5000);
        }
      }
    };

    void fetchQuotes();

    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
    };
  }, []);

  const scannerSectors = useMemo(
    () =>
      Array.from(
        new Set(
          stocks
            .map(row => stockMetadata[row[0]]?.sector?.trim())
            .filter((s): s is string => Boolean(s))
        )
      ).sort((a, b) => a.localeCompare(b)),
    [stocks, stockMetadata]
  );

  const filtered = useMemo(() => {
    const percentage = (row: string[]) => {
      const raw = stockMetadata[row[0]]?.change_pct;

      if (typeof raw === "number" && Number.isFinite(raw)) {
        return raw;
      }

      if (row[2].trim() === "—" || !row[2].trim()) {
        return null;
      }

      const parsed = Number(row[2].replace(/[%+,]/g, "").trim());

      return Number.isFinite(parsed) ? parsed : null;
    };

    return stocks
      .filter(row =>
        row[0].toLowerCase().includes(search.trim().toLowerCase()) &&
        (
          scannerSector === "All Sectors" ||
          stockMetadata[row[0]]?.sector?.trim() === scannerSector
        )
      )
      .sort((a, b) => {
        const av = percentage(a);
        const bv = percentage(b);

        if (av === null) {
          return bv === null ? a[0].localeCompare(b[0]) : 1;
        }

        if (bv === null) return -1;

        const difference =
          scannerSort === "Strongest" ? bv - av : av - bv;

        return difference || a[0].localeCompare(b[0]);
      });
  }, [stocks, stockMetadata, search, scannerSector, scannerSort]);

  const notify = (s: string) => {
    setNotice(s);
    window.setTimeout(() => setNotice(""), 2600);
  };

  // Market selection
  const handleMarketChange = (symbol: string) => {
    if (selectedMarket === symbol) return;

    const market = optionMarkets.find(m => m.symbol === symbol);

    // Cancel pending requests for the previous market
    chainRequest.current++;

    setSelectedMarket(symbol);
    setSelectedExpiry("");
    setChainData(null);
    setChainError("");
    setLiveOi(null);
    setBackendOnline(false);

    notify(`Switching to ${market?.label || symbol}...`);
  };

  // Use the exact live OI snapshot supplied by OISignalChart.
  const handleOiUpdate = useCallback((snapshot: OILiveSnapshot | null) => {
    setLiveOi(snapshot);
  }, []);

  const oiSignal = useMemo(() => {
    const oiThreshold = 1_000_000;
    const hasFreshOi = Boolean(liveOi && liveOi.fresh);

    const putOI = hasFreshOi ? liveOi!.putOI : null;
    const callOI = hasFreshOi ? liveOi!.callOI : null;

    const oiDifference =
      putOI !== null && callOI !== null
        ? Math.abs(putOI - callOI)
        : null;

    let oiType: "PUT BUY" | "CALL BUY" | "HOLD" | "WAITING" = "WAITING";

    if (oiDifference !== null) {
      if (oiDifference < oiThreshold) {
        oiType = "HOLD";
      } else if (putOI! > callOI!) {
        oiType = "CALL BUY";
      } else if (callOI! > putOI!) {
        oiType = "PUT BUY";
      } else {
        oiType = "HOLD";
      }
    }

    const ma8 =
      typeof chartIndicators?.ma8 === "number" &&
        Number.isFinite(chartIndicators.ma8)
        ? chartIndicators.ma8
        : null;

    const wma8 =
      typeof chartIndicators?.wma8 === "number" &&
        Number.isFinite(chartIndicators.wma8)
        ? chartIndicators.wma8
        : null;

    const maDifference =
      ma8 !== null && wma8 !== null
        ? Math.abs(ma8 - wma8)
        : null;

    let maType: "PUT BUY" | "CALL BUY" | "EQUAL" | "HOLD" | "WAITING" = "WAITING";

    if (maDifference !== null) {
      if (maDifference < 0.000001) {
        maType = "EQUAL";
      } else if (maDifference >= 5) {
        maType = ma8! > wma8! ? "PUT BUY" : "CALL BUY";
      } else {
        maType = "HOLD";
      }
    }

    return {
      oiType,
      maType,
      putOI,
      callOI,
      difference: oiDifference,
      ma8,
      wma8,
      maDifference,
      hasData: hasFreshOi || (ma8 !== null && wma8 !== null)
    };
  }, [liveOi, chartIndicators]);

  // Fetch dynamic option chain from FastAPI backend
  const fetchOptionChain = useCallback(
    async (exp?: string, rangeCount: number = strikeRange) => {
      const requestId = ++chainRequest.current;

      try {
        const url = new URL(apiUrl("/api/options/chain"));

        // Selected market is sent to the backend
        url.searchParams.set("symbol", selectedMarket);

        const targetExp = exp || selectedExpiry;

        if (targetExp) {
          url.searchParams.set("expiry", targetExp);
        }

        url.searchParams.set("num_strikes", String(rangeCount));

        const res = await fetch(url.toString(), {
          signal: AbortSignal.timeout(25000)
        });

        if (requestId !== chainRequest.current) return;

        if (res.ok) {
          const data: OptionChainData = await res.json();

          if (requestId !== chainRequest.current) return;

          setChainError("");
          setChainData(data);

          if (!selectedExpiry && data.selected_expiry) {
            setSelectedExpiry(data.selected_expiry);
          }

          setBackendOnline(true);
        } else {
          const result = await res.json();

          if (requestId !== chainRequest.current) return;

          setChainData(null);

          setChainError(
            typeof result.detail === "string"
              ? result.detail
              : "Live option chain unavailable"
          );

          if (res.status === 422 && selectedExpiry) {
            setSelectedExpiry("");
          }

          setBackendOnline(false);
        }
      } catch {
        if (requestId !== chainRequest.current) return;

        setChainData(null);
        setChainError("Live option chain request failed or timed out.");
        setBackendOnline(false);
      }
    },
    [selectedExpiry, strikeRange, selectedMarket]
  );

  const handleRefresh = async () => {
    setIsRefreshing(true);

    const exp = selectedExpiry || chainData?.selected_expiry;

    notify(
      `Refreshed ${selectedMarket} option chain (${exp || "nearest expiry"}).`
    );

    await fetchOptionChain(exp, strikeRange);

    setTimeout(() => {
      setIsRefreshing(false);
    }, 600);
  };

  // Poll selected market option chain
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      await fetchOptionChain(selectedExpiry, strikeRange);

      if (active) {
        timer = setTimeout(poll, 6000);
      }
    };

    void poll();

    return () => {
      active = false;
      clearTimeout(timer);
      chainRequest.current++;
    };
  }, [fetchOptionChain, selectedExpiry, strikeRange]);

  const selectedMarketLabel =
    optionMarkets.find(m => m.symbol === selectedMarket)?.label ||
    selectedMarket;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-icon">
            <BrainCircuit size={25} />
          </div>

          <div>
            <div className="brand-name">MarketMind AI</div>
            <div className="brand-sub">
              Dynamic ATM • OI &amp; PCR • Support/Resistance • AI Trading
            </div>
          </div>
        </div>

        <nav>
          {navItems.map(n => (
            <button
              key={n}
              className={active === n ? "nav active" : "nav"}
              onClick={() => setActive(n)}
            >
              {n}
            </button>
          ))}
        </nav>

        <label className="global-search">
          <Search size={14} />
          <input
            placeholder="Search stock / index"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </label>

        <button
          className="icon-button"
          onClick={() => notify("Alerts active.")}
        >
          <Bell size={17} />
          <i>3</i>
        </button>

        <button className="avatar">
          <UserRound size={17} />
        </button>
      </header>

      <div className={`demo-banner ${oiSignal.hasData ? "oi-signal-active" : ""}`}>
        {oiSignal.hasData ? (
          <div className="oi-signal-lines" role="status" aria-live="polite">
            <div
              className={`oi-single-line ${oiSignal.oiType === "CALL BUY"
                ? "call-alert"
                : oiSignal.oiType === "PUT BUY"
                  ? "put-alert"
                  : "hold-alert"
                }`}
            >
              <Activity size={14} />
              <strong>SUM OI: {oiSignal.oiType}</strong>

              <span>
                PUT OI: {
                  oiSignal.putOI == null
                    ? "—"
                    : oiSignal.putOI.toLocaleString("en-IN")
                }
              </span>

              <span>
                CALL OI: {
                  oiSignal.callOI == null
                    ? "—"
                    : oiSignal.callOI.toLocaleString("en-IN")
                }
              </span>

              <span className="oi-difference">
                OI DIFF: {
                  oiSignal.difference == null
                    ? "—"
                    : oiSignal.difference.toLocaleString("en-IN")
                }
              </span>

              <span className="oi-threshold">Threshold: 10 lakh</span>
            </div>

            <div
              className={`oi-single-line ${oiSignal.maType === "CALL BUY"
                ? "call-alert"
                : oiSignal.maType === "PUT BUY"
                  ? "put-alert"
                  : oiSignal.maType === "EQUAL"
                    ? "equal-alert"
                    : "hold-alert"
                }`}
            >
              <Activity size={14} />
              <strong>MA / WMA: {oiSignal.maType}</strong>

              <span>
                MA8: {oiSignal.ma8 == null ? "—" : oiSignal.ma8.toFixed(2)}
              </span>

              <span>
                WMA8: {oiSignal.wma8 == null ? "—" : oiSignal.wma8.toFixed(2)}
              </span>

              <span className="oi-difference">
                GAP: {
                  oiSignal.maDifference == null
                    ? "—"
                    : oiSignal.maDifference.toFixed(2)
                }
              </span>

              <span className="oi-threshold">Buy threshold: 5 points</span>
            </div>
          </div>
        ) : (
          <>
            <b>
              <Activity size={13} />
              {backendOnline ? "BACKEND ONLINE" : "DEMO / OFFLINE"}
            </b>

            <KiteLoginButton />

            {backendOnline && chainData ? (
              <span>
                Connected to FastAPI &bull; Mode: <b>{chainData.data_mode}</b>
                &bull; {selectedMarketLabel} ATM Active ({chainData.atm_strike})
              </span>
            ) : (
              <span>
                Connecting to MarketMind AI backend... Waiting for live data.
              </span>
            )}
          </>
        )}
      </div>

      <LiveMarketStrip
        symbol={selectedMarket}
        expiry={selectedExpiry || chainData?.selected_expiry || ""}
      />

      <main className="dashboard">
        {/* STOCK SCANNER — POSITION 3 */}
        <section className="panel scanner" style={{ gridArea: "options" }}>
          <PanelTitle icon={<span className="live-dot" />}>
            NIFTY 50 STOCK SCANNER
          </PanelTitle>

          <div className="scanner-tools">
            <label className="field">
              <Search size={13} />
              <input
                placeholder="Search stock..."
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </label>

            <select
              aria-label="Filter stocks by sector"
              value={scannerSector}
              onChange={e => setScannerSector(e.target.value)}
            >
              <option>All Sectors</option>
              {scannerSectors.map(sector => (
                <option key={sector} value={sector}>{sector}</option>
              ))}
            </select>

            <select
              aria-label="Sort stocks by percentage change"
              value={scannerSort}
              onChange={e => setScannerSort(e.target.value)}
            >
              <option>Strongest</option>
              <option>Weakest</option>
            </select>

            <button
              className="icon-button small-btn"
              title="Reset scanner filters"
              aria-label="Reset scanner filters"
              onClick={() => {
                setSearch("");
                setScannerSector("All Sectors");
                setScannerSort("Strongest");
              }}
            >
              <SlidersHorizontal size={14} />
            </button>
          </div>

          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>STOCK</th>
                  <th>LTP</th>
                  <th>% CHG</th>
                  <th>CALL OI</th>
                  <th>PUT OI</th>
                  <th>PCR</th>
                  <th>TREND</th>
                  <th>SIGNAL</th>
                </tr>
              </thead>

              <tbody>
                {filtered.map((s, i) => (
                  <tr key={s[0]}>
                    <td>{i + 1}</td>
                    <td className="symbol">{s[0]}</td>
                    <td>{s[1]}</td>
                    <td className={s[2].startsWith("+") ? "positive" : "negative"}>
                      {s[2]}
                    </td>
                    <td>{s[3]}</td>
                    <td>{s[4]}</td>
                    <td>{s[5]}</td>
                    <td className={
                      s[6] === "Bullish"
                        ? "positive"
                        : s[6] === "Bearish"
                          ? "negative"
                          : "amber"
                    }>
                      {s[6]}
                    </td>
                    <td>
                      <b className={`pill ${String(s[7]).toLowerCase()}`}>
                        {s[7]}
                      </b>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="muted tiny foot">
            {filtered.length} of {stocks.length} instruments · {scannerSort}
          </div>

          <SectorSummary
            stocks={stocks}
            metadata={stockMetadata}
            fetchedAt={stockSnapshotAt}
            error={stockQuoteError}
          />
        </section>

        {/* LIVE CHART */}
        <section className="panel chart-panel">
          <OISignalChart
            expiry={selectedExpiry || chainData?.selected_expiry || ""}
            numStrikes={strikeRange}
            onOiUpdate={handleOiUpdate}
          />

          <PanelTitle
            icon={
              <span
                className="live-dot"
                style={{
                  background: candleStatus.startsWith("Kite")
                    ? undefined
                    : "#f5b82e"
                }}
              />
            }
          >
            {selectedMarketLabel} — Candles
          </PanelTitle>

          <div className="toolbar">
            {["1m", "3m", "5m", "15m", "30m", "1H", "1D", "W"].map(t => (
              <button
                key={t}
                className={timeframe === t ? "selected" : ""}
                onClick={() => setTimeframe(t)}
              >
                {t}
              </button>
            ))}
          </div>

          <div className="chart-meta">
            <strong>
              {chartIndicators?.instrument || selectedMarket} · {timeframe}
            </strong>

            <span className={
              (chartIndicators?.change ?? 0) >= 0
                ? "positive"
                : "negative"
            }>
              ● {
                chartIndicators
                  ? chartIndicators.ltp.toLocaleString("en-IN", {
                    minimumFractionDigits: 2
                  })
                  : "—"
              }
              {" "}
              {
                chartIndicators?.change != null
                  ? `${chartIndicators.change >= 0 ? "+" : ""}${chartIndicators.change} (${chartIndicators.change_pct}%)`
                  : ""
              }
            </span>
          </div>

          <IndicatorCandleChart
            timeframe={timeframe}
            onIndicatorsUpdate={setChartIndicators}
            onStatusUpdate={setCandleStatus}
          />

          <div className="oi-caption" role="status">
            {candleStatus}
          </div>
        </section>

        {/* OPTION BUY / SELL + OPTION CHAIN */}
        <div className="option-action-stack" style={{ gridArea: "scanner" }}>
          <TradeSetupPanel
            expiry={selectedExpiry || chainData?.selected_expiry || ""}
          />

          <section className="panel options">
            <PanelTitle icon={<span className="live-dot" />}>
              OPTION CHAIN — {selectedMarketLabel} {
                chainData?.selected_expiry
                  ? `· ${chainData.selected_expiry} (${chainData.days_to_expiry ?? 0} DTE)`
                  : ""
              }
            </PanelTitle>

            {/* HORIZONTAL MARKET SELECTOR */}
            <div className="market-selector">
              {optionMarkets.map(market => (
                <button
                  key={market.symbol}
                  type="button"
                  className={
                    selectedMarket === market.symbol
                      ? "market-tab active"
                      : "market-tab"
                  }
                  onClick={() => handleMarketChange(market.symbol)}
                >
                  {market.label}
                </button>
              ))}
            </div>

            <div className="chain-controls">
              <select
                value={selectedExpiry || (chainData?.selected_expiry ?? "")}
                onChange={e => {
                  setSelectedExpiry(e.target.value);
                }}
              >
                {chainData?.available_expiries ? (
                  chainData.available_expiries.map(exp => (
                    <option key={exp} value={exp}>{exp}</option>
                  ))
                ) : (
                  <option value="">Loading expiries...</option>
                )}
              </select>

              <select
                value={strikeRange}
                onChange={e => {
                  const r = Number(e.target.value);
                  setStrikeRange(r);
                }}
              >
                <option value={5}>±5 Strikes</option>
                <option value={7}>±7 Strikes</option>
                <option value={10}>±10 Strikes</option>
                <option value={25}>±25 Strikes</option>
                <option value={50}>±50 Strikes</option>
              </select>

              <button
                className="refresh-btn"
                onClick={handleRefresh}
                disabled={isRefreshing}
                title="Refresh option chain data"
              >
                <RefreshCw
                  size={11}
                  className={isRefreshing ? "spin" : ""}
                />
                <span>{isRefreshing ? "Syncing..." : "Refresh"}</span>
              </button>
            </div>

            <div className="muted tiny" role="status">
              {chainError || (
                chainData
                  ? `${chainData.data_mode} · ${new Date(chainData.timestamp).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" })} IST`
                  : "Waiting for Kite quotes…"
              )}
            </div>

            <div className="muted tiny">
              OI Chg%: versus previous trading-session close. Dash = baseline loading/unavailable.
            </div>

            {/* COMBINED CALL + PUT OPTION CHAIN */}
            <div className="table-scroll">
              <table className="option-table">
                <thead>
                  <tr>
                    <th>CALL OI (Chg%)</th>
                    <th>LTP</th>
                    <th>STRIKE</th>
                    <th>LTP</th>
                    <th>PUT OI (Chg%)</th>
                    <th>PCR / OI DEPTH</th>
                  </tr>
                </thead>

                <tbody>
                  {chainData?.strikes ? (
                    chainData.strikes.map(s => {
                      const rowClass = s.is_atm
                        ? "atm"
                        : s.is_resistance
                          ? "resistance"
                          : s.is_support
                            ? "support"
                            : "";

                      return (
                        <tr key={s.strike} className={rowClass}>
                          <td className={`oi-cell ${s.call_oi_chg == null
                            ? "muted"
                            : s.call_oi_chg > 0
                              ? "positive"
                              : s.call_oi_chg < 0
                                ? "negative"
                                : "muted"
                            }`}>
                            <span>
                              {s.call_oi_formatted}{" "}
                              <small>
                                ({(s.call_oi_pct_chg ?? 0) > 0 ? "+" : ""}
                                {s.call_oi_pct_chg == null
                                  ? "—"
                                  : `${s.call_oi_pct_chg}%`})
                              </small>
                            </span>

                            <div className="oi-bar-wrap">
                              <div
                                className="oi-bar call"
                                style={{
                                  width: `${s.call_bar_pct}%`,
                                  background:
                                    s.call_oi_chg == null || s.call_oi_chg === 0
                                      ? "#698494"
                                      : s.call_oi_chg > 0
                                        ? "#00d6a3"
                                        : "#ff4566"
                                }}
                              />
                            </div>
                          </td>

                          <td>{s.call_ltp?.toFixed(2) ?? "—"}</td>

                          <td className="strike">
                            {s.strike}
                            {s.is_atm && <span className="badge-atm">ATM</span>}
                            {s.is_resistance && <span className="badge-res">R1</span>}
                            {s.is_support && <span className="badge-sup">S1</span>}
                          </td>

                          <td>{s.put_ltp?.toFixed(2) ?? "—"}</td>

                          <td className={`oi-cell ${s.put_oi_chg == null
                            ? "muted"
                            : s.put_oi_chg > 0
                              ? "positive"
                              : s.put_oi_chg < 0
                                ? "negative"
                                : "muted"
                            }`}>
                            <span>
                              {s.put_oi_formatted}{" "}
                              <small>
                                ({(s.put_oi_pct_chg ?? 0) > 0 ? "+" : ""}
                                {s.put_oi_pct_chg == null
                                  ? "—"
                                  : `${s.put_oi_pct_chg}%`})
                              </small>
                            </span>

                            <div className="oi-bar-wrap">
                              <div
                                className="oi-bar put"
                                style={{
                                  width: `${s.put_bar_pct}%`,
                                  background:
                                    s.put_oi_chg == null || s.put_oi_chg === 0
                                      ? "#698494"
                                      : s.put_oi_chg > 0
                                        ? "#00d6a3"
                                        : "#ff4566"
                                }}
                              />
                            </div>
                          </td>

                          <td>
                            <div style={{
                              display: "flex",
                              gap: "2px",
                              alignItems: "center",
                              justifyContent: "center"
                            }}>
                              <span style={{
                                fontSize: "7px",
                                color: "#8da6bd"
                              }}>
                                {s.strike_pcr ?? "—"}
                              </span>

                              <div style={{
                                width: "35px",
                                height: "4px",
                                background: "#061826",
                                borderRadius: "2px",
                                display: "flex",
                                overflow: "hidden"
                              }}>
                                <div
                                  style={{
                                    width: `${s.call_bar_pct / 2}%`,
                                    background: "#ff4566"
                                  }}
                                />
                                <div
                                  style={{
                                    width: `${s.put_bar_pct / 2}%`,
                                    background: "#00d6a3"
                                  }}
                                />
                              </div>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  ) : (
                    <tr>
                      <td colSpan={6} style={{
                        textAlign: "center",
                        padding: "15px"
                      }}>
                        {chainError || "Loading live option chain…"}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="option-summary">
              <div>
                <span>Total Call OI</span>
                <b className="negative">
                  {chainData?.total_call_oi ?? "—"}
                </b>
              </div>

              <div>
                <span>PCR</span>
                <b>{chainData?.pcr ?? "—"}</b>
                <small className={
                  chainData?.pcr_bias === "Bullish"
                    ? "positive"
                    : "negative"
                }>
                  {chainData ? chainData.pcr_bias : "Neutral"}
                </small>
              </div>

              <div>
                <span>Total Put OI</span>
                <b className="positive">
                  {chainData?.total_put_oi ?? "—"}
                </b>
              </div>
            </div>

            <div className="max-oi" title={chainData?.level_scope}>
              <div>
                Major Resistance (R1):{" "}
                <b style={{ color: "#ff8ca0" }}>
                  {chainData?.resistance_strike ?? "—"}
                </b>{" "}
                ({chainData?.resistance_oi})
              </div>

              <div>
                Major Support (S1):{" "}
                <b style={{ color: "#38f1c1" }}>
                  {chainData?.support_strike ?? "—"}
                </b>{" "}
                ({chainData?.support_oi})
              </div>
            </div>

            {chainData?.ab_score && (
              <div className="ab-score-box" title={chainData?.score_method}>
                <div>
                  <span>OI Balance Score: </span>
                  <strong>{chainData.ab_score.score ?? "—"} / 100</strong>
                  <span style={{
                    marginLeft: "5px",
                    color: "#8da6bd"
                  }}>
                    ({chainData.ab_score.trend})
                  </span>
                </div>

                <b className={`ab-score-pill ${chainData.ab_score.color}`}>
                  {chainData.ab_score.recommendation}
                </b>
              </div>
            )}
          </section>
        </div>

        {/* TRADING CONTROL */}
        <section className="panel trading">
          <PanelTitle>TRADING CONTROL</PanelTitle>

          <div className="segmented">
            {["Manual", "Auto (AI)", "Paper"].map(m => (
              <button
                key={m}
                className={tradeMode === m ? "selected" : ""}
                onClick={() => {
                  setTradeMode(m);
                  if (m === "Auto (AI)") setAuto(false);
                }}
              >
                {m}
              </button>
            ))}
          </div>

          <h3>Auto Trading Settings</h3>

          <div className="setting-row">
            <span>Enable Auto Trade</span>
            <button
              className={`toggle ${auto ? "on" : ""}`}
              onClick={() => {
                setAuto(!auto);
                if (!auto) {
                  notify("UI demo only: live auto-trading is not connected.");
                }
              }}
            >
              <i />
            </button>
          </div>

          {[
            "Confirmation|Strict Confirmation",
            "Risk per Trade|1%",
            "Risk / Reward|1:2",
            "Max Trades / Day|3",
            "Daily Loss Limit|₹2,000",
            "Order Authorization|Confirm before order",
            "Auto Exit|SL + Target + Trailing"
          ].map(x => (
            <label className="setting-select" key={x}>
              {x.split("|")[0]}
              <select>
                <option>{x.split("|")[1]}</option>
              </select>
            </label>
          ))}

          <div className="switch-row">
            <button onClick={() => setAlerts(!alerts)}>
              <i className={alerts ? "switch on" : "switch"} />
              Alerts {alerts ? "ON" : "OFF"}
            </button>

            <button onClick={() => setSound(!sound)}>
              <i className={sound ? "switch on" : "switch"} />
              <Volume2 size={12} />
              Sound
            </button>
          </div>

          <div className="trade-buttons">
            <button
              className="buy"
              onClick={() => notify("Order preview created: BUY (CE)")}
            >
              BUY (CE)
            </button>

            <button
              className="sell"
              onClick={() => notify("Order preview created: SELL (PE)")}
            >
              SELL (PE)
            </button>
          </div>

          <h3>
            Quick Order <span className="amber tiny">DEMO</span>
          </h3>

          <div className="order-row">
            <select value={selectedMarket} onChange={e => handleMarketChange(e.target.value)}>
              {optionMarkets.map(m => (
                <option key={m.symbol} value={m.symbol}>{m.label}</option>
              ))}
            </select>

            <select>
              <option>{chainData?.selected_expiry ?? "Nearest expiry"}</option>
            </select>
          </div>

          <div className="order-row">
            <button
              className="order-choice selected"
              onClick={() => notify("CE selected")}
            >
              CE
            </button>

            <button
              className="order-choice"
              onClick={() => notify("PE selected")}
            >
              PE
            </button>
          </div>

          <div className="order-row">
            <select>
              <option>{chainData?.atm_strike ?? "ATM Strike"}</option>
              <option>{(chainData?.atm_strike ?? 0) + 50}</option>
            </select>

            <input
              type="number"
              defaultValue={1}
              min={1}
              aria-label="Quantity"
            />

            <select>
              <option>Market</option>
              <option>Limit</option>
            </select>
          </div>

          <label className="checkbox">
            <input type="checkbox" defaultChecked />
            Set Stop Loss &amp; Target
          </label>

          <button
            className="primary"
            onClick={() =>
              notify(
                tradeMode === "Paper"
                  ? "Demo paper-order preview created."
                  : "Demo order preview created."
              )
            }
          >
            Preview Order
          </button>
        </section>

        <LiveConfluencePanel
          expiry={selectedExpiry || chainData?.selected_expiry || ""}
          numStrikes={strikeRange}
        />

        <CrudeOilPanel />

        <OfficialNewsPanel />

        <WeightedSetupPanel
          expiry={selectedExpiry || chainData?.selected_expiry || ""}
        />
      </main>

      <footer>
        <span>
          <ShieldCheck size={13} /> MarketMind AI
        </span>

        <span>
          <i className="live-dot" />
          Backend: {backendOnline ? "Connected" : "Connecting..."}
        </span>

        <span>
          {chainData
            ? `Last sync: ${chainData.timestamp}`
            : "Polling..."}
        </span>
      </footer>

      {notice && (
        <div className="toast" role="status">
          {notice}
        </div>
      )}
    </div>
  );
}
