import { useEffect, useMemo, useState } from "react";
import { sectorSummary, signedSectorChange } from "./sectorData";
import type { StockSectorMeta } from "./sectorData";
import "./SectorSummary.css";
// import SectorOIGraph from "./SectorOIGraph";

export default function SectorSummary({ stocks, metadata, fetchedAt, error }: {
  stocks: string[][];
  metadata: Record<string, StockSectorMeta>;
  fetchedAt: string;
  error: string;
}) {
  const sectors = useMemo(() => sectorSummary(stocks, metadata), [stocks, metadata]);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const parsed = Date.parse(fetchedAt);
  const stale = !!error || !Number.isFinite(parsed) || now - parsed > 45000;
  // const covered = sectors.reduce((sum, s) => sum + s.covered, 0);
  const total = sectors.reduce((sum, s) => sum + s.stocks, 0);

  return <section className="sector-summary" aria-label="NIFTY 50 sector breakdown">
    <div className="sector-summary-heading"><strong>NIFTY 50 — SECTOR BREAKDOWN</strong><span className={stale ? "amber" : "muted"}>{total} stocks</span></div>
    <div className="sector-summary-scroll" tabIndex={0} aria-label="Scroll all sectors">
      <table>
        <thead><tr><th>SECTOR</th><th title="Companies in sector divided by all scanner companies">STOCK SHARE</th><th title="Equal-weight mean of available daily stock percentage changes">AVG % CHG</th></tr></thead>
        <tbody>{sectors.map(s => {
          const tone = s.change === null ? "muted" : Math.abs(s.change) < 0.005 ? "amber" : s.change > 0 ? "positive" : "negative";
          return <tr key={s.sector} title={`${s.stocks} stocks · ${s.covered} with percentage data · ${s.gainers} up / ${s.losers} down / ${s.unchanged} unchanged`}>
            <td><span className="sector-summary-name">{s.sector}</span><small>{s.stocks} stocks</small></td>
            <td><span>{s.share.toFixed(1)}%</span><div className="sector-share-track"><div style={{ width: `${s.share}%` }} /></div></td>
            <td className={tone}>{signedSectorChange(s.change)}<small>{s.covered}/{s.stocks} quoted</small></td>
          </tr>;
        })}</tbody>
      </table>
      {!sectors.length && <div className="muted tiny">Waiting for scanner quotes…</div>}
    </div>
    {/* <div className="sector-summary-note" role="status">
      {stale && total ? `STALE · ${error || "Waiting for updated scanner quotes"} · ` : ""}
      Share = stock count. Change = average daily stock return. {covered}/{total} with change data.
      <br/>These figures describe the NIFTY 50 stocks; index weights and option-OI shares require separate data.
    </div>
    <SectorOIGraph /> */}
  </section>;
}
