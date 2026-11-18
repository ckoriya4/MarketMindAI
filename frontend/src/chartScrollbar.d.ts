import type { IChartApi } from "lightweight-charts";
export interface ChartScrollController {
  setExtent(totalBars: number): void;
  showWindow(lastDataIndex: number, visibleBars?: number): void;
  destroy(): void;
}
export function scrollGeometry(totalBars: number, range: {from: number; to: number}, viewport: number): {
  span: number; window: number; maxFrom: number; from: number; contentWidth: number;
};
export function attachChartScrollbar(chart: IChartApi, host: HTMLElement): ChartScrollController;
