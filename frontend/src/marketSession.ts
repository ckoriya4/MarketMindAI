import type { UTCTimestamp, WhitespaceData } from "lightweight-charts";

export interface MarketSession {
  date: string;
  open: number;
  close: number;
  label: string;
}

// Whitespace has a time but no fabricated price/OI. Minute anchors keep time spacing uniform.
export function sessionData<T extends { time: UTCTimestamp }>(
  points: T[], session: MarketSession
): (T | WhitespaceData<UTCTimestamp>)[] {
  const entries = new Map<number, T | WhitespaceData<UTCTimestamp>>();
  for (let t = session.open; t <= session.close; t += 60) {
    entries.set(t, { time: t as UTCTimestamp });
  }
  entries.set(session.close, { time: session.close as UTCTimestamp });
  for (const point of points) {
    if (point.time >= session.open && point.time <= session.close) {
      entries.set(point.time, point);
    }
  }
  return Array.from(entries.values()).sort((a, b) => Number(a.time) - Number(b.time));
}

// Display one real observation per minute; all raw observations remain in the API/database.
export function minuteSnapshots<T extends { time: number }>(points: T[]): (Omit<T, "time"> & { time: UTCTimestamp })[] {
  const minutes = new Map<number, Omit<T, "time"> & { time: UTCTimestamp }>();
  for (const point of points) {
    const minute = Math.floor(point.time / 60) * 60;
    minutes.set(minute, { ...point, time: minute as UTCTimestamp });
  }
  return Array.from(minutes.values()).sort((a, b) => a.time - b.time);
}
