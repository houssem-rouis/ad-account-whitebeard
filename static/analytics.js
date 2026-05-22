(function () {
  const palette = {
    primary: '#2563eb',
    success: '#16a34a',
    warning: '#d97706',
    accent: '#7c3aed',
    info: '#0891b2',
    rose: '#e11d48',
    gray: '#94a3b8',
  };

  function rate() {
    if (typeof getDisplayCurrency === 'function') {
      const code = getDisplayCurrency();
      const meta = window.DISPLAY_CURRENCIES[code];
      return meta ? meta.rate_from_usd : 1;
    }
    return 1;
  }

  function tickColor() {
    return getComputedStyle(document.documentElement).getPropertyValue('--color-text-muted').trim() || '#64748b';
  }
  function gridColor() {
    return getComputedStyle(document.documentElement).getPropertyValue('--color-border').trim() || '#e2e8f0';
  }

  const charts = [];

  function scale(values, factor) {
    return values.map(function (v) { return (parseFloat(v) || 0) * factor; });
  }

  function fmtMoney(usd) {
    if (typeof formatMoney === 'function') return formatMoney(usd, getDisplayCurrency(), 2);
    return '$' + (parseFloat(usd) || 0).toFixed(2);
  }

  function build(canvas, factory) {
    if (!canvas) return null;
    const chart = factory(canvas);
    if (chart) charts.push({ chart: chart, refresh: factory.refresh });
    return chart;
  }

  function buildTimeseries() {
    const canvas = document.getElementById('chartTimeseries');
    if (!canvas) return;
    const labels = JSON.parse(canvas.dataset.labels || '[]');
    const spend = JSON.parse(canvas.dataset.spend || '[]');
    const revenue = JSON.parse(canvas.dataset.revenue || '[]');
    const purchases = JSON.parse(canvas.dataset.purchases || '[]');
    let r = rate();

    const chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          { label: 'Spend', data: scale(spend, r), borderColor: palette.primary, backgroundColor: palette.primary + '20', tension: 0.25, fill: true, yAxisID: 'y' },
          { label: 'Revenue', data: scale(revenue, r), borderColor: palette.success, backgroundColor: palette.success + '20', tension: 0.25, fill: true, yAxisID: 'y' },
          { label: 'Purchases', data: purchases, borderColor: palette.accent, backgroundColor: 'transparent', tension: 0.25, yAxisID: 'y1', borderDash: [4, 4] },
        ],
      },
      options: {
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        plugins: { legend: { position: 'bottom', labels: { color: tickColor() } } },
        scales: {
          x: { ticks: { color: tickColor() }, grid: { display: false } },
          y: { position: 'left', beginAtZero: true, ticks: { color: tickColor() }, grid: { color: gridColor() } },
          y1: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false }, ticks: { color: tickColor() } },
        },
      },
    });

    document.addEventListener('display-currency-changed', function () {
      const newRate = rate();
      chart.data.datasets[0].data = scale(spend, newRate);
      chart.data.datasets[1].data = scale(revenue, newRate);
      chart.update();
    });
  }

  function buildAccounts() {
    const canvas = document.getElementById('chartAccounts');
    if (!canvas) return;
    const labels = JSON.parse(canvas.dataset.labels || '[]');
    const spend = JSON.parse(canvas.dataset.spend || '[]');
    const revenue = JSON.parse(canvas.dataset.revenue || '[]');
    let r = rate();

    const chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          { label: 'Spend', data: scale(spend, r), backgroundColor: palette.primary, borderRadius: 6 },
          { label: 'Revenue', data: scale(revenue, r), backgroundColor: palette.success, borderRadius: 6 },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: 'bottom', labels: { color: tickColor() } } },
        scales: {
          x: { ticks: { color: tickColor() }, grid: { display: false } },
          y: { beginAtZero: true, ticks: { color: tickColor() }, grid: { color: gridColor() } },
        },
      },
    });
    document.addEventListener('display-currency-changed', function () {
      const newRate = rate();
      chart.data.datasets[0].data = scale(spend, newRate);
      chart.data.datasets[1].data = scale(revenue, newRate);
      chart.update();
    });
  }

  function buildDonut(canvasId, colors) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const labels = JSON.parse(canvas.dataset.labels || '[]');
    const values = JSON.parse(canvas.dataset.values || '[]');
    new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels: labels.map(function (l) { return String(l).charAt(0).toUpperCase() + String(l).slice(1); }),
        datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: 'bottom', labels: { color: tickColor(), boxWidth: 10 } } },
        cutout: '60%',
      },
    });
  }

  function buildBarSpend(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const labels = JSON.parse(canvas.dataset.labels || '[]');
    const spend = JSON.parse(canvas.dataset.spend || '[]');
    let r = rate();
    const chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{ label: 'Spend', data: scale(spend, r), backgroundColor: palette.primary, borderRadius: 6 }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { beginAtZero: true, ticks: { color: tickColor() }, grid: { color: gridColor() } },
          y: { ticks: { color: tickColor() }, grid: { display: false } },
        },
      },
    });
    document.addEventListener('display-currency-changed', function () {
      const newRate = rate();
      chart.data.datasets[0].data = scale(spend, newRate);
      chart.update();
    });
  }

  function buildHourly() {
    const canvas = document.getElementById('chartHourly');
    if (!canvas) return;
    const labels = JSON.parse(canvas.dataset.labels || '[]');
    const spend = JSON.parse(canvas.dataset.spend || '[]');
    const purchases = JSON.parse(canvas.dataset.purchases || '[]');
    let r = rate();
    const chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          { label: 'Spend', data: scale(spend, r), backgroundColor: palette.primary, borderRadius: 4, yAxisID: 'y' },
          { label: 'Purchases', data: purchases, type: 'line', borderColor: palette.accent, backgroundColor: 'transparent', tension: 0.25, yAxisID: 'y1' },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: 'bottom', labels: { color: tickColor() } } },
        scales: {
          x: { ticks: { color: tickColor() }, grid: { display: false } },
          y: { beginAtZero: true, ticks: { color: tickColor() }, grid: { color: gridColor() } },
          y1: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false }, ticks: { color: tickColor() } },
        },
      },
    });
    document.addEventListener('display-currency-changed', function () {
      const newRate = rate();
      chart.data.datasets[0].data = scale(spend, newRate);
      chart.update();
    });
  }

  function buildScatter() {
    const canvas = document.getElementById('chartScatter');
    if (!canvas) return;
    const points = JSON.parse(canvas.dataset.points || '[]');
    if (!points.length) return;
    new Chart(canvas, {
      type: 'scatter',
      data: {
        datasets: [{
          label: 'Creative',
          data: points,
          backgroundColor: palette.primary,
          borderColor: palette.primary,
          pointRadius: 6,
          pointHoverRadius: 8,
        }],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                const p = ctx.raw;
                return p.label + ' · Freq ' + p.x.toFixed(2) + ' · CTR ' + p.y.toFixed(2) + '%';
              },
            },
          },
        },
        scales: {
          x: { title: { display: true, text: 'Frequency', color: tickColor() }, ticks: { color: tickColor() }, grid: { color: gridColor() } },
          y: { title: { display: true, text: 'CTR (%)', color: tickColor() }, beginAtZero: true, ticks: { color: tickColor() }, grid: { color: gridColor() } },
        },
      },
    });
  }

  function colorHeatmap() {
    const cells = Array.from(document.querySelectorAll('.heatmap-cell'));
    const values = cells.map(function (c) { return parseFloat(c.dataset.value || '0'); });
    const max = Math.max.apply(null, values);
    if (!max) return;
    cells.forEach(function (cell) {
      const v = parseFloat(cell.dataset.value || '0');
      const alpha = max ? Math.min(0.85, 0.08 + (v / max) * 0.7) : 0;
      cell.style.background = 'rgba(37, 99, 235, ' + alpha.toFixed(3) + ')';
      if (alpha > 0.5) cell.style.color = '#fff';
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    buildTimeseries();
    buildAccounts();
    buildDonut('chartStatusMix', [palette.success, palette.warning, palette.rose, palette.gray]);
    buildDonut('chartCreativeMix', [palette.primary, palette.accent, palette.info, palette.gray]);
    buildBarSpend('chartCountry');
    buildBarSpend('chartPlacement');
    buildBarSpend('chartDevice');
    buildHourly();
    buildScatter();
    colorHeatmap();
  });
})();
