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
const significanceBox = document.getElementById('significance');
const sweepGridBox = document.getElementById('sweep-grid');
const sweepSortBox = document.getElementById('sweep-sort');
const sweepButton = document.getElementById('sweep-button');
const sweepStatusBox = document.getElementById('sweep-status');
const sweepBody = document.getElementById('sweep-body');
const wfOosBox = document.getElementById('wf-oos');
const wfButton = document.getElementById('wf-button');
const wfStatusBox = document.getElementById('wf-status');
const wfResultBox = document.getElementById('wf-result');

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

function renderSignificance(sig) {
  if (!sig || sig.n < 2) {
    significanceBox.innerHTML = '';
    return;
  }
  const real = sig.significant;
  const cls = real ? 'good' : 'bad';
  const verdict = real ? 'LIKELY REAL' : 'NOT SIGNIFICANT';
  significanceBox.innerHTML = `
    <div class="verdict-row ${cls}">
      <span class="verdict-tag">${verdict}</span>
      <span class="verdict-stat">t&nbsp;<b>${sig.tstat}</b></span>
      <span class="verdict-stat">p&nbsp;<b>${sig.pvalue}</b></span>
      <span class="verdict-stat">n&nbsp;${sig.n}</span>
    </div>
    <div class="verdict-note">Edge is trustworthy only when |t| &ge; 2 and p &lt; 0.05. A great curve with weak stats is noise.</div>
  `;
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
    const payload = buildBasePayload();
    const result = await fetchJson('/api/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    renderMetrics(result.metrics);
    renderSignificance(result.significance);
    renderTrades(result.trades);
    renderCharts(result.price_bars, result.curve);
    sourceBox.textContent = JSON.stringify(result.source, null, 2);
    statusBox.textContent = 'Done';
  } catch (error) {
    statusBox.textContent = `Error: ${error.message}`;
  }
}

function buildBasePayload() {
  const formData = new FormData(form);
  return {
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
}

function renderSweep(out) {
  const runs = out.runs || [];
  if (!runs.length) {
    sweepBody.innerHTML = '<tr><td colspan="9">No runs.</td></tr>';
    return;
  }
  const bestKey = JSON.stringify(out.best?.params);
  sweepBody.innerHTML = runs.map((run) => {
    if (run.error || !run.metrics) {
      return `<tr class="err"><td>${JSON.stringify(run.params)}</td><td colspan="8">${run.error || 'failed'}</td></tr>`;
    }
    const m = run.metrics;
    const s = run.significance || {};
    const isBest = JSON.stringify(run.params) === bestKey;
    const sigCls = s.significant ? 'good' : 'bad';
    const verdict = s.significant ? 'real' : 'noise';
    return `
      <tr class="${isBest ? 'best' : ''}">
        <td>${JSON.stringify(run.params)}</td>
        <td>${m.total_return_pct}</td>
        <td>${m.sharpe}</td>
        <td>${m.max_drawdown_pct}</td>
        <td>${m.trade_count}</td>
        <td>${m.win_rate_pct}</td>
        <td>${s.tstat ?? '-'}</td>
        <td>${s.pvalue ?? '-'}</td>
        <td class="${sigCls}">${verdict}</td>
      </tr>
    `;
  }).join('');
}

function legCard(title, leg) {
  const m = leg.metrics;
  const s = leg.significance || {};
  const sigCls = s.significant ? 'good' : 'bad';
  return `
    <div class="wf-leg">
      <div class="wf-leg-title">${title}</div>
      <div class="wf-leg-rows">
        <span>Return %</span><b>${m.total_return_pct}</b>
        <span>Sharpe</span><b>${m.sharpe}</b>
        <span>Max DD %</span><b>${m.max_drawdown_pct}</b>
        <span>Trades</span><b>${m.trade_count}</b>
        <span>t (HAC)</span><b>${s.tstat ?? '-'}</b>
        <span>p-value</span><b>${s.pvalue ?? '-'}</b>
      </div>
      <div class="wf-leg-verdict ${sigCls}">${s.significant ? 'significant' : 'not significant'}</div>
    </div>
  `;
}

function renderWalkForward(out) {
  const decay = out.decay;
  const held = out.holds_out_of_sample;
  const cls = held ? 'good' : 'bad';
  const verdict = held ? 'HOLDS OUT OF SAMPLE' : 'DID NOT HOLD';
  wfResultBox.innerHTML = `
    <div class="wf-banner ${cls}">
      <span class="verdict-tag">${verdict}</span>
      <span class="verdict-stat">OOS decay&nbsp;<b>${decay}</b> pts</span>
      <span class="verdict-stat">split @ bar&nbsp;${out.split_index}</span>
    </div>
    <div class="wf-legs">
      ${legCard('In-sample', out.in_sample)}
      ${legCard('Out-of-sample', out.out_sample)}
    </div>
    <div class="verdict-note">Decay = OOS return − IS return. Strongly negative means the in-sample edge did not survive on unseen data — the overfit tell.</div>
  `;
}

async function runWalkForward() {
  wfStatusBox.textContent = 'Running...';
  wfButton.disabled = true;
  try {
    const payload = buildBasePayload();
    payload.oos_fraction = Number(wfOosBox.value);
    const out = await fetchJson('/api/walkforward', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    renderWalkForward(out);
    wfStatusBox.textContent = 'Done';
  } catch (error) {
    wfStatusBox.textContent = `Error: ${error.message}`;
  } finally {
    wfButton.disabled = false;
  }
}

async function runSweep() {
  sweepStatusBox.textContent = 'Sweeping...';
  sweepButton.disabled = true;
  try {
    const payload = buildBasePayload();
    payload.grid = JSON.parse(sweepGridBox.value || '{}');
    payload.sort_by = sweepSortBox.value;
    const out = await fetchJson('/api/sweep', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    renderSweep(out);
    sweepStatusBox.textContent = `Done — ${out.count} combos`;
  } catch (error) {
    sweepStatusBox.textContent = `Error: ${error.message}`;
  } finally {
    sweepButton.disabled = false;
  }
}

strategySelect?.addEventListener('change', (event) => syncParamsForStrategy(event.target.value));
providerSelect?.addEventListener('change', syncProviderFields);
loadExampleButton?.addEventListener('click', loadCustomExample);
sweepButton?.addEventListener('click', runSweep);
wfButton?.addEventListener('click', runWalkForward);
form?.addEventListener('submit', runBacktest);

Promise.all([loadProviders(), loadStrategies()])
  .then(() => runBacktest(new Event('submit')))
  .catch((error) => {
    statusBox.textContent = `Boot error: ${error.message}`;
  });
