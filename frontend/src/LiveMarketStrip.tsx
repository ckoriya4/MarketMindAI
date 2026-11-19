
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

const EMPTY = [
  ["NIFTY", "NIFTY 50 (SPOT)"],
  ["BANKNIFTY", "BANK NIFTY"],
  ["SENSEX", "SENSEX"],
  ["VIX", "INDIA VIX"],
  ["CRUDE", "CRUDE OIL (MCX)"],
].map(
  ([id, name]) =>
    ({
      id,
      name,
      price: null,
      status: "loading",
      history: [],
    }) as MarketCardData
);

const signed = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;

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

function ObservedSpark({
  points,
  down,
}: {
  points: { time: number; value: number }[];
  down: boolean;
}) {
  const values = points
    .filter((p) => Number.isFinite(p.value))
    .map((p) => p.value);

  const min = Math.min(...values);
  const max = Math.max(...values);

  const pts = values
    .map(
      (value, i) =>
        `${values.length > 1 ? (i / (values.length - 1)) * 100 : 50},${min === max ? 20 : 34 - ((value - min) / (max - min)) * 28
        }`
    )
    .join(" ");

  return (
    <svg
      className={`spark ${down ? "down" : ""}`}
      viewBox="0 0 100 40"
      preserveAspectRatio="none"
      role="img"
      aria-label="Recorded quote history"
    >
      <title>
        {values.length > 1
          ? `${values.length} actual quote observations`
          : "Waiting for more quote observations"}
      </title>

      {values.length > 1 && (
        <>
          <polyline
            points={pts}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          />
          <polygon
            points={`0,40 ${pts} 100,40`}
            fill="currentColor"
            opacity=".12"
          />
        </>
      )}
    </svg>
  );
}

export default function LiveMarketStrip({
  expiry = "",
}: {
  expiry?: string;
}) {
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

  const cards = data?.cards || EMPTY;
  const atm = data?.atm;
  const atmChange = atm?.spot_change_pct;

  return (
    <section className="market-strip" aria-label="Live market overview">
      {cards.map((card) => {
        const stale =
          requestStale ||
          card.status === "stale" ||
          (card.quote_time != null && now / 1000 - card.quote_time > 90);

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

        return (
          <div className="market-card" key={card.id} title={title}>
            <div>
              <div className="muted tiny">
                {card.name}
                {status && <span className="amber"> · {status}</span>}
              </div>

              <strong className="market-value">{formatted(card)}</strong>

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

            <ObservedSpark points={card.history || []} down={down} />
          </div>
        );
      })}

      <AtmOiSummary expiry={expiry} spotChange={atmChange} />
    </section>
  );
}
