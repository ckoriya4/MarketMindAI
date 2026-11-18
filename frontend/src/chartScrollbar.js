// A native horizontal scrollbar synchronized with Lightweight Charts' time scale.
export function scrollGeometry(totalBars, range, viewport) {
  const span = Math.max(1, totalBars - 1);
  const window = Math.min(span, Math.max(1, range.to - range.from));
  const maxFrom = Math.max(0, span - window);
  const from = Math.max(0, Math.min(maxFrom, range.from));
  const contentWidth = Math.max(viewport, viewport * span / window);
  return { span, window, maxFrom, from, contentWidth };
}

export function attachChartScrollbar(chart, host) {
  const spacer = document.createElement('div');
  spacer.className = 'chart-scroll-spacer';
  host.replaceChildren(spacer);
  let total = 0;
  let frame = 0;
  let disposed = false;
  let expectedLeft = 0;
  const scale = chart.timeScale();

  const sync = () => {
    frame = 0;
    if (disposed) return;
    const range = scale.getVisibleLogicalRange();
    if (!range || total < 2 || host.clientWidth < 1) {
      spacer.style.width = '100%';
      expectedLeft = 0;
      host.scrollLeft = 0;
      return;
    }
    const geometry = scrollGeometry(total, range, host.clientWidth);
    spacer.style.width = `${geometry.contentWidth}px`;
    const pixels = host.scrollWidth - host.clientWidth;
    expectedLeft = geometry.maxFrom > 0 ? geometry.from / geometry.maxFrom * pixels : 0;
    host.scrollLeft = expectedLeft;
    expectedLeft = host.scrollLeft;
  };
  const schedule = () => {
    if (!disposed && !frame) frame = requestAnimationFrame(sync);
  };
  const scroll = () => {
    // Ignore the scroll event caused by syncing the thumb after chart pan/zoom.
    if (Math.abs(host.scrollLeft - expectedLeft) < 1) return;
    const range = scale.getVisibleLogicalRange();
    const pixels = host.scrollWidth - host.clientWidth;
    if (!range || !pixels || total < 2) return;
    const geometry = scrollGeometry(total, range, host.clientWidth);
    const from = host.scrollLeft / pixels * geometry.maxFrom;
    expectedLeft = host.scrollLeft;
    scale.setVisibleLogicalRange({ from, to: from + geometry.window });
  };
  const resize = new ResizeObserver(schedule);
  resize.observe(host);
  host.addEventListener('scroll', scroll, { passive: true });
  scale.subscribeVisibleLogicalRangeChange(schedule);

  return {
    setExtent(totalBars) { total = Math.max(0, totalBars); schedule(); },
    showWindow(lastDataIndex, visibleBars = 120) {
      if (total < 2) return;
      const span = total - 1;
      const window = Math.min(span, visibleBars);
      const from = Math.max(0, Math.min(span - window, lastDataIndex - window));
      scale.setVisibleLogicalRange({ from, to: from + window });
      schedule();
    },
    destroy() {
      disposed = true;
      cancelAnimationFrame(frame);
      resize.disconnect();
      host.removeEventListener('scroll', scroll);
      scale.unsubscribeVisibleLogicalRangeChange(schedule);
      host.replaceChildren();
    },
  };
}
