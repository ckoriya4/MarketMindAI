export interface StockSectorMeta {
  sector?: string;
  change_pct?: number | null;
  available?: boolean;
}
export interface SectorAggregate {
  sector: string;
  stocks: number;
  share: number;
  change: number | null;
  covered: number;
  gainers: number;
  losers: number;
  unchanged: number;
}

export function sectorSummary(rows: string[][], metadata: Record<string, StockSectorMeta>): SectorAggregate[] {
  const unique = new Map(rows.filter(r => r.length >= 3).map(r => [r[0], r]));
  const sectors = new Map<string, { count: number; changes: number[] }>();
  for (const [symbol, row] of unique) {
    const meta = metadata[symbol];
    const name = meta?.sector?.trim() || "Unclassified";
    const group = sectors.get(name) || { count: 0, changes: [] };
    group.count++;
    let pct: number | null = null;
    if (meta?.available !== false) {
      if (typeof meta?.change_pct === "number" && Number.isFinite(meta.change_pct)) pct = meta.change_pct;
      else if (/^[+-]?\d+(?:\.\d+)?%$/.test(row[2].trim())) pct = Number(row[2].trim().replace("%", ""));
    }
    if (pct !== null) group.changes.push(pct);
    sectors.set(name, group);
  }
  return Array.from(sectors, ([sector, group]) => ({
    sector,
    stocks: group.count,
    share: unique.size ? group.count / unique.size * 100 : 0,
    change: group.changes.length ? group.changes.reduce((sum,n) => sum+n,0) / group.changes.length : null,
    covered: group.changes.length,
    gainers: group.changes.filter(n => n > 0).length,
    losers: group.changes.filter(n => n < 0).length,
    unchanged: group.changes.filter(n => n === 0).length,
  })).sort((a,b) => b.stocks-a.stocks || a.sector.localeCompare(b.sector));
}

export function signedSectorChange(change: number | null): string {
  if (change === null) return "—";
  const rounded = Math.abs(change) < 0.005 ? 0 : change;
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(2)}%`;
}
