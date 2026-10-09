/* Gráficas del detalle de una vigilancia (Chart.js) */
let historyChart = null;

const shortDate = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(2, 4)}`;

function buildDatasets(block, providers) {
  const many = block.labels.length > 40;
  return Object.entries(block.series).map(([key, values]) => ({
    label: providers[key].label,
    data: values,
    borderColor: providers[key].color,
    backgroundColor: providers[key].color + '33',
    spanGaps: true,
    tension: 0.25,
    pointRadius: many ? 0 : 3,
    pointHoverRadius: 5,
  }));
}

function lineChart(canvas, block, providers, existing) {
  if (existing) existing.destroy();
  return new Chart(canvas, {
    type: 'line',
    data: { labels: block.labels.map(shortDate), datasets: buildDatasets(block, providers) },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y} €` } },
      },
      scales: { y: { ticks: { callback: (v) => v + ' €' } }, x: { ticks: { maxTicksLimit: 12 } } },
    },
  });
}

function emptyNote(canvas) {
  const box = canvas.parentElement;
  box.style.height = 'auto';
  box.innerHTML = '<p class="muted">Aún no hay datos suficientes. Pulsa «Comprobar ahora» y vuelve en unos minutos.</p>';
}

async function loadDateHistory(watchId, date) {
  const canvas = document.getElementById('chart-date-history');
  if (!canvas || !date) return;
  const data = await (await fetch(`/api/watches/${watchId}/date-history?date=${encodeURIComponent(date)}`)).json();
  if (!data.labels.length) return;
  historyChart = lineChart(canvas, data, data.providers, historyChart);
}

async function initCharts(watchId) {
  const data = await (await fetch(`/api/watches/${watchId}/charts`)).json();
  const c1 = document.getElementById('chart-min');
  const c2 = document.getElementById('chart-dates');
  data.min_over_time.labels.length ? lineChart(c1, data.min_over_time, data.providers) : emptyNote(c1);
  data.by_flight_date.labels.length ? lineChart(c2, data.by_flight_date, data.providers) : emptyNote(c2);

  const select = document.getElementById('date-select');
  if (select) {
    select.addEventListener('change', () => loadDateHistory(watchId, select.value));
    loadDateHistory(watchId, select.value);
    // Pulsar el día en el calendario muestra el historial de esa fecha.
    document.querySelectorAll('button.cal-day[data-date]').forEach((btn) => btn.addEventListener('click', () => {
      select.value = btn.dataset.date;
      loadDateHistory(watchId, select.value);
      select.closest('section').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
  }
}
