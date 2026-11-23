
import { useEffect, useState } from "react";
import AtmOiSummary from "./AtmOiSummary";
import { apiUrl } from "./config/api";

interface MarketCardData {
  id: string;
  name: string;
  price: number | null;
  change?: number | null;
  change_pct?: number | null;
  status: string;
  currency?: string | null;
  source?: string;
  symbol?: string;
  error?: string;
  quote_time?: number | null;
  received_at?: number;
  history: { time: number; value: number }[];
}

interface MarketOverview {
  cards: MarketCardData[];
  fetched_at: string;
  atm: {
    strike: number | null;
    status: string;
    spot_change_pct: number | null;
    quote_time: number | null;
  };
}

const MARKET_LIST = [
  { id: "NIFTY", name: "NIFTY 50" },
  { id: "BANKNIFTY", name: "BANK NIFTY" },
  { id: "FINNIFTY", name: "FINNIFTY" },
  { id: "MIDCPNIFTY", name: "MIDCPNIFTY" },
  { id: "NIFTYNXT50", name: "NIFTY NEXT 50" },
  { id: "SENSEX", name: "SENSEX" },
  { id: "BANKEX", name: "BANKEX" },
];

// const EMPTY = MARKET_LIST.map((market) => ({
//   ...market,
//   price: null,
//   status: "loading",
//   history: [],
// })) as MarketCardData[];

const signed = (n: number) =>
  `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;

const formatted = (card: MarketCardData) =>
  card.price == null
    ? "—"
    : `${card.currency === "INR" ? "₹" : ""}${card.price.toLocaleString(
      "en-IN",
      {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }
    )}`;

const normalizeSymbol = (value?: string) =>
  (value || "").toUpperCase().replace(/[^A-Z0-9]/g, "");

interface LiveMarketStripProps {
  symbol?: string;
  expiry?: string;
  onMarketChange?: (symbol: string) => void;
}

export default function LiveMarketStrip({
  symbol = "NIFTY",
  expiry = "",
  onMarketChange,
}: LiveMarketStripProps) {
  const [data, setData] = useState<MarketOverview | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    const load = async () => {
      const current = new AbortController();
      controller = current;

      const timeout = setTimeout(() => current.abort(), 60000);

      try {
        const response = await fetch(apiUrl("/api/market/overview"), {
          signal: current.signal,
        });

        const result = await response.json();

        if (!response.ok) {
          throw new Error(
            typeof result.detail === "string"
              ? result.detail
              : `Market API error ${response.status}`
          );
        }

        if (
          result.source !== "kite" ||
          !Array.isArray(result.cards) ||
          !result.atm
        ) {
          throw new Error("Invalid market quote response");
        }

        if (active) {
          setData(result);
          setError("");
        }
      } catch (e) {
        if (active) {
          setError(
            e instanceof Error && e.name === "AbortError"
              ? "Market quote request timed out"
              : e instanceof Error
                ? e.message
                : "Market quotes unavailable"
          );
        }
      } finally {
        clearTimeout(timeout);

        if (active) {
          timer = setTimeout(load, 5000);
        }
      }
    };

    void load();

    return () => {
      active = false;
      clearTimeout(timer);
      controller?.abort();
    };
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const received = Date.parse(data?.fetched_at || "");

  const requestStale =
    !!error ||
    (!!data && (!Number.isFinite(received) || now - received > 45000));

  // Show exactly the seven markets available in the Option Chain buttons.
  // Match API quotes by either card ID or instrument symbol.
  const cards = MARKET_LIST.map((market) => {
    const apiCard = data?.cards.find(
      (card) =>
        normalizeSymbol(card.id) === normalizeSymbol(market.id) ||
        normalizeSymbol(card.symbol) === normalizeSymbol(market.id)
    );

    return (
      apiCard || {
        ...market,
        price: null,
        status: data ? "unavailable" : "loading",
        history: [],
        error: data
          ? "This market quote is not available from the backend yet."
          : undefined,
      }
    ) as MarketCardData;
  });

  // Find the selected market's quote for the ATM spot-change display.
  const selectedMarketCard = cards.find(
    (card) =>
      normalizeSymbol(card.id) === normalizeSymbol(symbol) ||
      normalizeSymbol(card.symbol) === normalizeSymbol(symbol)
  );

  const selectedSpotChange =
    selectedMarketCard?.change_pct ??
    (symbol === "NIFTY" ? data?.atm?.spot_change_pct : null);

  return (
    <section className="market-strip" aria-label="Live market overview">
      {cards.map((card) => {
        const stale =
          requestStale ||
          card.status === "stale" ||
          (card.quote_time != null &&
            now / 1000 - card.quote_time > 90);

        const unavailable = card.price == null;
        const down = card.change != null && card.change < 0;

        const status = unavailable
          ? error
            ? "UNAVAILABLE"
            : card.status === "loading"
              ? "LOADING"
              : "UNAVAILABLE"
          : stale
            ? "STALE"
            : "";

        const title =
          error ||
          card.error ||
          `${card.source || "Kite"}${card.symbol ? ` · ${card.symbol}` : ""
          } · ${card.quote_time
            ? `exchange time ${new Date(
              card.quote_time * 1000
            ).toLocaleString("en-IN", {
              timeZone: "Asia/Kolkata",
            })} IST`
            : "exchange timestamp not supplied; received snapshot shown"
          }`;

        const isSelected =
          normalizeSymbol(symbol) === normalizeSymbol(card.id);

        return (
          <div
            className="market-card"
            key={card.id}
            title={title}
            role={onMarketChange ? "button" : undefined}
            tabIndex={onMarketChange ? 0 : undefined}
            aria-pressed={onMarketChange ? isSelected : undefined}
            onClick={() => onMarketChange?.(card.id)}
            onKeyDown={(e) => {
              if (
                onMarketChange &&
                (e.key === "Enter" || e.key === " ")
              ) {
                e.preventDefault();
                onMarketChange(card.id);
              }
            }}
          >
            <div className="market-card-content">
              <div className="muted tiny">
                {card.name}
                {status && <span className="amber"> · {status}</span>}
              </div>

              <strong className="market-value">
                {formatted(card)}
              </strong>

              <div
                className={
                  card.change == null || card.change === 0
                    ? "muted change"
                    : down
                      ? "negative change"
                      : "positive change"
                }
              >
                {card.change != null
                  ? `${signed(card.change)}${card.change_pct != null
                    ? ` (${signed(card.change_pct)}%)`
                    : ""
                  }`
                  : unavailable
                    ? "Waiting for quote"
                    : "Previous close unavailable"}
              </div>
            </div>
          </div>
        );
      })}

      {/* ATM card remains after all seven market cards */}
      <AtmOiSummary
        symbol={symbol}
        expiry={expiry}
        spotChange={selectedSpotChange}
      />
    </section>
  );
}
