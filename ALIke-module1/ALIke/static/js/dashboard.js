/* Dashboard: Plotly charts, severity filter, jump-to-comparison. */
(() => {
  const data = JSON.parse(document.getElementById('page-data').textContent);
  const COLORS = { high: '#FF626F', medium: '#FFBF69', low: '#42D9E8' };
  const TEXT = '#A1A3B5', GRID = 'rgba(255,255,255,.07)', PRIMARY = '#9065FF';
  const REGION_LABEL = { left_arm: 'Left arm', right_arm: 'Right arm', left_leg: 'Left leg', right_leg: 'Right leg', other: 'Other' };
  const label = (s) => String(s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  const mmss = (s) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`;
  const openComparison = (index) => { window.location.href = `${data.urls.comparison}?error=${index}`; };

  // ---- error list: filter + open
  const list = document.getElementById('err-list');
  if (list) {
    list.addEventListener('click', (e) => {
      const item = e.target.closest('.err-item');
      if (item) openComparison(item.dataset.index);
    });
    document.querySelectorAll('.chip').forEach((chip) => chip.addEventListener('click', () => {
      document.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', String(c === chip)));
      const f = chip.dataset.filter;
      list.querySelectorAll('.err-item').forEach((it) => { it.hidden = !(f === 'all' || it.dataset.severity === f); });
    }));
  }

  if (typeof Plotly === 'undefined') return;   // CDN blocked: the rest of the page still works
  const base = {
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Manrope, sans-serif', color: TEXT, size: 13 },
    margin: { l: 70, r: 20, t: 10, b: 44 },
  };
  const config = { displayModeBar: false, responsive: true };

  // ---- timeline
  const tl = document.getElementById('timeline-chart');
  if (tl && data.errors.length) {
    const lanes = { low: 1, medium: 2, high: 3 };
    const errs = data.errors;
    Plotly.newPlot(tl, [{
      type: 'scatter', mode: 'markers',
      x: errs.map((e) => e.timestamp),
      y: errs.map((e) => lanes[e.severity] || 1),
      customdata: errs.map((e) => [e.index, label(e.joint), e.deviation, e.unit || '°', e.severity]),
      marker: { size: 16, color: errs.map((e) => COLORS[e.severity] || TEXT), line: { width: 2, color: '#1B1D27' } },
      hovertemplate: '<b>%{customdata[1]}</b><br>%{customdata[2]}%{customdata[3]} · %{customdata[4]}<br>at %{x:.1f}s<extra></extra>',
    }], {
      ...base,
      xaxis: { range: [0, Math.max(data.duration, ...errs.map((e) => e.timestamp + 0.5))], title: { text: 'Seconds', standoff: 8 }, gridcolor: GRID, zeroline: false },
      yaxis: { range: [0.4, 3.6], tickvals: [1, 2, 3], ticktext: ['Low', 'Medium', 'High'], gridcolor: GRID, zeroline: false, fixedrange: true },
      hoverlabel: { bgcolor: '#212331', bordercolor: '#3a3d52', font: { color: '#F5F5FA' } },
    }, config);
    tl.on('plotly_click', (ev) => openComparison(ev.points[0].customdata[0]));
  }

  // ---- distribution
  const dist = document.getElementById('dist-chart');
  if (dist) {
    const entries = Object.entries(data.distribution).sort((a, b) => a[1] - b[1]);
    Plotly.newPlot(dist, [{
      type: 'bar', orientation: 'h',
      x: entries.map((e) => e[1]), y: entries.map((e) => REGION_LABEL[e[0]] || label(e[0])),
      marker: { color: PRIMARY }, hovertemplate: '%{y}: %{x}<extra></extra>',
    }], {
      ...base, margin: { l: 90, r: 20, t: 6, b: 36 },
      xaxis: { dtick: 1, gridcolor: GRID, zeroline: false, rangemode: 'tozero' },
      yaxis: { automargin: true, fixedrange: true },
      hoverlabel: { bgcolor: '#212331', bordercolor: '#3a3d52', font: { color: '#F5F5FA' } },
    }, config);
  }
})();
