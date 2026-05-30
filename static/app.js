const strategySelect = document.getElementById('strategy-select');
const providerSelect = document.getElementById('provider-select');
const filePathLabel = document.getElementById('file-path-label');
const filePathInput = document.getElementById('file-path-input');
const paramsBox = document.getElementById('params');
const customCodeBox = document.getElementById('custom_code');
const metricsBox = document.getElementById('metrics');
const sourceBox = document.getElementById('source');
const statusBox = document.getElementById('status');
const tradesBody = document.getElementById('trades-body');
const loadExampleButton = document.getElementById('load-example');
const form = document.getElementById('run-form');

let strategies = {};
let providers = {};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail || 'Request failed');
  }
  return body;
}

function renderMetrics(metrics) {
  const entries = [
    ['Ending Equity', metrics.ending_equity],
    ['Total Return %', metrics.total_return_pct],
    ['Annualized %', metrics.annualized_return_pct],
    ['Max Drawdown %', metrics.max_drawdown_pct],
    ['Sharpe', metrics.sharpe],
    ['Trades', metrics.trade_count],
    ['Win Rate %', metrics.win_rate_pct],
    ['Exposure %', metrics.exposure_pct],
  ];

  // AZC bracket strategies report R-native truth — the numbers the crypto
  // research is judged on. Surface them alongside the cash metrics.
  if (metrics.execution === 'bracket') {
    entries.push(['Net R / trade', metrics.net_r_per_trade]);
    entries.push(['Total R', metrics.total_r]);
    entries.push(['Max DD (R)', metrics.max_drawdown_r]);
    entries.push(['Fee model', metrics.fee_model]);
  }

  metricsBox.innerHTML = entries.map(([label, value]) => {
    const numeric = Number(value);
    const cls = label.includes('Drawdown') ? 'bad' : numeric > 0 ? 'good' : '';
    return `
      <div class="metric ${cls}">
        <div class="label">${label}</div>
        <div class="value">${value}</div>
      </div>
    `;
  }).join('');
}

function renderTrades(trades) {
  if (!trades.length) {
    tradesBody.innerHTML = '<tr><td colspan="6">No completed trades yet.</td></tr>';
    return;
  }
  tradesBody.innerHTML = trades.slice().reverse().map((trade) => `
    <tr>
      <td>${trade.entry_at}</td>
      <td>${trade.exit_at}</td>
      <td>${trade.entry_price}</td>
      <td>${trade.exit_price}</td>
      <td>${trade.pnl_pct}</td>
      <td>${trade.equity_after}</td>
    </tr>
  `).join('');
}

function renderCharts(priceBars, curve) {
  const time = curve.map((row) => row.time);
  Plotly.newPlot('price-chart', [
    {
      x: priceBars.map((row) => row.time),
      y: priceBars.map((row) => row.close),
      name: 'Close',
      type: 'scatter',
      line: { color: '#6ea8fe' },
      yaxis: 'y1',
    },
    {
      x: time,
      y: curve.map((row) => row.equity),
      name: 'Equity',
      type: 'scatter',
      line: { color: '#2ecc71' },
      yaxis: 'y2',
    },
  ], {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: '#edf2ff' },
    margin: { l: 40, r: 40, t: 20, b: 40 },
    yaxis: { title: 'Price' },
    yaxis2: { title: 'Equity', overlaying: 'y', side: 'right' },
    legend: { orientation: 'h' },
  }, { responsive: true });

  Plotly.newPlot('drawdown-chart', [{
    x: time,
    y: curve.map((row) => row.drawdown),
    type: 'scatter',
    fill: 'tozeroy',
    line: { color: '#ff6b6b' },
    name: 'Drawdown %',
  }], {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: '#edf2ff' },
    margin: { l: 40, r: 20, t: 20, b: 40 },
  }, { responsive: true });
}

function syncParamsForStrategy(name) {
  const preset = strategies[name]?.params || {};
  if (name === 'custom_python') {
    paramsBox.value = JSON.stringify({}, null, 2);
    return;
  }
  paramsBox.value = JSON.stringify(preset, null, 2);
}

function syncProviderFields() {
  const providerName = providerSelect.value;
  const provider = providers[providerName];
  const needsFile = Boolean(provider?.supports_files);
  filePathLabel.classList.toggle('hidden', !needsFile);
  filePathInput.required = needsFile;
}

async function loadStrategies() {
  strategies = await fetchJson('/api/strategies');
  strategySelect.innerHTML = Object.entries(strategies)
    .map(([name, config]) => `<option value="${name}">${config.label}</option>`)
    .join('');
  syncParamsForStrategy(strategySelect.value);
}

async function loadProviders() {
  providers = await fetchJson('/api/providers');
  providerSelect.innerHTML = Object.entries(providers)
    .map(([name, config]) => `<option value="${name}">${config.label}</option>`)
    .join('');
  providerSelect.value = 'yahoo';
  syncProviderFields();
}

async function loadCustomExample() {
  const result = await fetchJson('/api/example/custom-strategy');
  strategySelect.value = 'custom_python';
  paramsBox.value = JSON.stringify({ fast: 10, slow: 30 }, null, 2);
  customCodeBox.value = result.code;
}

async function runBacktest(event) {
  event.preventDefault();
  statusBox.textContent = 'Running...';
  try {
    const formData = new FormData(form);
    const payload = {
      data_provider: formData.get('data_provider'),
      symbol: formData.get('symbol'),
      interval: formData.get('interval'),
      years: Number(formData.get('years')),
      market: formData.get('market') || null,
      timezone: formData.get('timezone') || 'UTC',
      session: formData.get('session') || null,
      file_path: formData.get('file_path') || null,
      initial_cash: Number(formData.get('initial_cash')),
      fee_bps: Number(formData.get('fee_bps')),
      refresh_data: formData.get('refresh_data') === 'on',
      strategy: formData.get('strategy'),
      strategy_params: JSON.parse(paramsBox.value || '{}'),
      custom_code: customCodeBox.value,
    };
    const result = await fetchJson('/api/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    renderMetrics(result.metrics);
    renderTrades(result.trades);
    renderCharts(result.price_bars, result.curve);
    sourceBox.textContent = JSON.stringify(result.source, null, 2);
    statusBox.textContent = 'Done';
  } catch (error) {
    statusBox.textContent = `Error: ${error.message}`;
  }
}

strategySelect?.addEventListener('change', (event) => syncParamsForStrategy(event.target.value));
providerSelect?.addEventListener('change', syncProviderFields);
loadExampleButton?.addEventListener('click', loadCustomExample);
form?.addEventListener('submit', runBacktest);

Promise.all([loadProviders(), loadStrategies()])
  .then(() => runBacktest(new Event('submit')))
  .catch((error) => {
    statusBox.textContent = `Boot error: ${error.message}`;
  });
