const strategySelect = document.getElementById('strategy-select');
const providerSelect = document.getElementById('provider-select');
const filePathLabel = document.getElementById('file-path-label');
const filePathInput = document.getElementById('file-path-input');
const paramsBox = document.getElementById('params');
const customCodeBox = document.getElementById('custom_code');
const metricsBox = document.getElementById('metrics');
const sourceBox = document.getElementById('source');
const datasetSummaryBox = document.getElementById('dataset-summary');
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
const priceChartCanvas = document.getElementById('price-chart');
const drawdownChartCanvas = document.getElementById('drawdown-chart');
const runsBody = document.getElementById('runs-body');
const datasetsBody = document.getElementById('datasets-body');
const historyStatusBox = document.getElementById('history-status');
const datasetStatusBox = document.getElementById('dataset-status');
const refreshRunsButton = document.getElementById('refresh-runs');
const compareButton = document.getElementById('compare-button');
const compareStatusBox = document.getElementById('compare-status');
const compareBody = document.getElementById('compare-body');
const compareChartCanvas = document.getElementById('compare-chart');
const tabButtons = Array.from(document.querySelectorAll('.tab-button'));
const tabPanels = Array.from(document.querySelectorAll('[data-tab-panel]'));

let strategies = {};
let providers = {};
let priceChart = null;
let drawdownChart = null;
let compareChart = null;
let currentRunId = '';

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body.detail || 'Request failed');
  }
  return body;
}

function safeJsonParse(value, fallback = {}) {
  try {
    return JSON.parse(value || '{}');
  } catch (error) {
    throw new Error(`Invalid JSON: ${error.message}`);
  }
}

function fmt(value, digits = 3) {
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return numeric.toFixed(digits).replace(/\.0+$/, '').replace(/(\.\d*[1-9])0+$/, '$1');
  }
  return String(value);
}

function shortTime(value) {
  if (!value) {
    return '-';
  }
  return String(value).replace('T', ' ').replace('+00:00', ' UTC');
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function setStatus(node, text, tone = '') {
  if (!node) {
    return;
  }
  node.textContent = text;
  node.classList.remove('good', 'bad', 'warn');
  if (tone) {
    node.classList.add(tone);
  }
}

function diffDays(start, end) {
  if (!start || !end) {
    return null;
  }
  const startDate = new Date(start);
  const endDate = new Date(end);
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
    return null;
  }
  return Math.max(0, (endDate - startDate) / 86400000);
}

function coverageSummary(start, end) {
  if (!start || !end) {
    return '-';
  }
  const days = diffDays(start, end);
  if (days === null) {
    return `${shortTime(start)} → ${shortTime(end)}`;
  }
  return `${shortTime(start)} → ${shortTime(end)} (${fmt(days / 365, 2)}y)`;
}

function requestWindowLabel(source, interval) {
  const years = Number(source?.requested_years || 0);
  if (!Number.isFinite(years) || years <= 0) {
    return interval || '-';
  }
  return `${fmt(years, 1)}y @ ${interval || '-'}`;
}

function renderSourceDetails(source = {}, request = {}) {
  sourceBox.textContent = JSON.stringify({ request, source }, null, 2);
}

function activateTab(name) {
  tabButtons.forEach((button) => {
    const active = button.dataset.tab === name;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  tabPanels.forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.tabPanel === name);
  });
}

function renderDatasetSummary(source = {}) {
  const dataset = source.dataset || {};
  const requestedYears = Number(source.requested_years || 0);
  const actualDays = diffDays(dataset.start, dataset.end);
  const actualYears = actualDays === null ? null : actualDays / 365;
  const note = source.source_note || 'No provider note';
  const mismatch = requestedYears > 0 && actualYears !== null && actualYears + 0.15 < requestedYears;
  datasetSummaryBox.innerHTML = `
    <div class="dataset-summary-card ${mismatch ? 'warn' : ''}">
      <div class="dataset-summary-head">
        <div>
          <div class="eyebrow">DATASET SUMMARY</div>
          <div class="dataset-summary-title">${escapeHtml(source.provider || 'provider')} · ${escapeHtml(source.symbol || '-')} · ${escapeHtml(source.interval || '-')}</div>
        </div>
        <div class="dataset-summary-badges">
          <span class="mini-pill">${escapeHtml(requestedYears > 0 ? `${fmt(requestedYears, 1)}y requested` : 'request window unknown')}</span>
          <span class="mini-pill">${escapeHtml(actualYears !== null ? `${fmt(actualYears, 2)}y returned` : 'returned range unknown')}</span>
          <span class="mini-pill">${escapeHtml(`${dataset.rows ?? '-'} rows`)}</span>
        </div>
      </div>
      <div class="dataset-summary-grid">
        <div><span>Coverage</span><strong>${escapeHtml(coverageSummary(dataset.start, dataset.end))}</strong></div>
        <div><span>Market / session</span><strong>${escapeHtml(dataset.market || 'unspecified')} / ${escapeHtml(dataset.session || 'default')}</strong></div>
        <div><span>Timezone</span><strong>${escapeHtml(dataset.timezone || 'UTC')}</strong></div>
        <div><span>Provider note</span><strong>${escapeHtml(note)}</strong></div>
      </div>
      ${mismatch ? '<div class="dataset-warning">Requested history is longer than the dataset that actually came back. This is now shown explicitly.</div>' : ''}
    </div>
  `;
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
        <div class="value">${fmt(value)}</div>
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
  const verdict = real ? 'LIKELY REAL' : 'LOW CONFIDENCE';
  significanceBox.innerHTML = `
    <div class="verdict-row ${cls}">
      <span class="verdict-tag">${verdict}</span>
      <span class="verdict-stat">t <b>${fmt(sig.tstat)}</b></span>
      <span class="verdict-stat">p <b>${fmt(sig.pvalue, 4)}</b></span>
      <span class="verdict-stat">n ${fmt(sig.n, 0)}</span>
      ${currentRunId ? `<span class="verdict-stat">run <b>${currentRunId}</b></span>` : ''}
    </div>
    <div class="verdict-note">Confidence matters. A strong-looking curve with weak stats still counts as noise.</div>
  `;
}

function renderTrades(trades) {
  if (!trades.length) {
    tradesBody.innerHTML = '<tr><td colspan="7" class="empty-state">No completed trades yet.</td></tr>';
    return;
  }
  tradesBody.innerHTML = trades.slice().reverse().map((trade) => `
    <tr>
      <td>${shortTime(trade.entry_at)}</td>
      <td>${shortTime(trade.exit_at)}</td>
      <td>${escapeHtml(trade.side || '-')}</td>
      <td>${fmt(trade.entry_price)}</td>
      <td>${fmt(trade.exit_price)}</td>
      <td>${fmt(trade.pnl_pct)}</td>
      <td>${fmt(trade.equity_after)}</td>
    </tr>
  `).join('');
}

function buildLineChart(target, labels, datasets, axisConfig = {}) {
  return new Chart(target.getContext('2d'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#edf2ff', boxWidth: 14, padding: 18, font: { size: 13 } } },
      },
      scales: {
        x: {
          ticks: { color: '#93a1c6', maxTicksLimit: 8, font: { size: 12 } },
          grid: { color: 'rgba(36, 49, 87, 0.35)' },
        },
        ...axisConfig,
      },
    },
  });
}

function renderCharts(priceBars, curve) {
  const labels = curve.map((row) => row.time);
  const priceMap = new Map(priceBars.map((row) => [row.time, row.close]));
  const priceSeries = labels.map((time) => priceMap.get(time) ?? null);
  const equitySeries = curve.map((row) => row.equity);
  const drawdownSeries = curve.map((row) => row.drawdown);

  if (priceChart) {
    priceChart.destroy();
  }
  if (drawdownChart) {
    drawdownChart.destroy();
  }

  priceChart = buildLineChart(priceChartCanvas, labels, [
    {
      label: 'Close',
      data: priceSeries,
      yAxisID: 'price',
      borderColor: '#6ea8fe',
      backgroundColor: 'rgba(110, 168, 254, 0.15)',
      borderWidth: 2.5,
      pointRadius: 0,
      tension: 0.08,
    },
    {
      label: 'Equity',
      data: equitySeries,
      yAxisID: 'equity',
      borderColor: '#2ecc71',
      backgroundColor: 'rgba(46, 204, 113, 0.15)',
      borderWidth: 2.5,
      pointRadius: 0,
      tension: 0.08,
    },
  ], {
    price: {
      position: 'left',
      ticks: { color: '#93a1c6', font: { size: 12 } },
      grid: { color: 'rgba(36, 49, 87, 0.35)' },
      title: { display: true, text: 'Price', color: '#93a1c6' },
    },
    equity: {
      position: 'right',
      ticks: { color: '#93a1c6', font: { size: 12 } },
      grid: { drawOnChartArea: false },
      title: { display: true, text: 'Equity', color: '#93a1c6' },
    },
  });

  drawdownChart = buildLineChart(drawdownChartCanvas, labels, [{
    label: 'Drawdown %',
    data: drawdownSeries,
    borderColor: '#ff6b6b',
    backgroundColor: 'rgba(255, 107, 107, 0.18)',
    fill: true,
    borderWidth: 2.5,
    pointRadius: 0,
    tension: 0.08,
  }], {
    y: {
      ticks: { color: '#93a1c6', font: { size: 12 } },
      grid: { color: 'rgba(36, 49, 87, 0.35)' },
    },
  });
}

function renderCompareChart(seriesList) {
  if (compareChart) {
    compareChart.destroy();
    compareChart = null;
  }
  if (!seriesList.length) {
    setStatus(compareStatusBox, 'No overlay-ready curves in selected runs.', 'warn');
    return;
  }
  const palette = ['#6ea8fe', '#2ecc71', '#ff6b6b', '#f1c40f', '#9b59b6', '#4dd0e1'];
  compareChart = buildLineChart(compareChartCanvas, seriesList[0].curve.map((row) => row.time), seriesList.map((series, idx) => ({
    label: series.label,
    data: series.curve.map((row) => row.normalized),
    borderColor: palette[idx % palette.length],
    backgroundColor: 'transparent',
    borderWidth: 2.5,
    pointRadius: 0,
    tension: 0.08,
  })), {
    y: {
      ticks: { color: '#93a1c6', font: { size: 12 } },
      grid: { color: 'rgba(36, 49, 87, 0.35)' },
      title: { display: true, text: 'Normalized Equity (100=start)', color: '#93a1c6' },
    },
  });
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
  const provider = providers[providerName] || {};
  const needsFile = Boolean(provider.supports_files);
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

function applyRequestToForm(payload) {
  const mapping = {
    data_provider: providerSelect,
    symbol: form.elements.symbol,
    interval: form.elements.interval,
    years: form.elements.years,
    market: form.elements.market,
    timezone: form.elements.timezone,
    session: form.elements.session,
    file_path: form.elements.file_path,
    initial_cash: form.elements.initial_cash,
    fee_bps: form.elements.fee_bps,
    strategy: strategySelect,
  };
  Object.entries(mapping).forEach(([key, node]) => {
    if (!node || payload[key] === undefined || payload[key] === null) {
      return;
    }
    node.value = payload[key];
  });
  form.elements.refresh_data.checked = Boolean(payload.refresh_data);
  paramsBox.value = JSON.stringify(payload.strategy_params || {}, null, 2);
  customCodeBox.value = payload.custom_code || '';
  syncProviderFields();
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
    strategy_params: safeJsonParse(paramsBox.value || '{}'),
    custom_code: customCodeBox.value,
  };
}

async function runBacktest(event) {
  event.preventDefault();
  activateTab('backtest');
  setStatus(statusBox, 'Running...');
  try {
    const payload = buildBasePayload();
    const result = await fetchJson('/api/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    currentRunId = result.run_id || '';
    renderMetrics(result.metrics);
    renderSignificance(result.significance);
    renderTrades(result.trades || []);
    renderCharts(result.price_bars || [], result.curve || []);
    renderDatasetSummary(result.source || {});
    renderSourceDetails(result.source || {}, payload);
    setStatus(statusBox, result.storage_error ? 'Completed with storage warning' : 'Completed', result.storage_error ? 'warn' : 'good');
    await Promise.all([loadRunHistory(), loadDatasetHistory()]);
  } catch (error) {
    setStatus(statusBox, `Error: ${error.message}`, 'bad');
  }
}

function renderSweep(out) {
  const runs = out.runs || [];
  if (!runs.length) {
    sweepBody.innerHTML = '<tr><td colspan="9" class="empty-state">No sweep results yet. Enter a grid and run the sweep.</td></tr>';
    return;
  }
  const bestKey = JSON.stringify(out.best?.params);
  sweepBody.innerHTML = runs.map((run) => {
    if (run.error || !run.metrics) {
      return `<tr class="err"><td>${escapeHtml(JSON.stringify(run.params))}</td><td colspan="8">${escapeHtml(run.error || 'failed')}</td></tr>`;
    }
    const m = run.metrics;
    const s = run.significance || {};
    const isBest = JSON.stringify(run.params) === bestKey;
    const sigCls = s.significant ? 'good' : 'bad';
    const verdict = s.significant ? 'real' : 'noise';
    return `
      <tr class="${isBest ? 'best' : ''}">
        <td>${escapeHtml(JSON.stringify(run.params))}</td>
        <td>${fmt(m.total_return_pct)}</td>
        <td>${fmt(m.sharpe)}</td>
        <td>${fmt(m.max_drawdown_pct)}</td>
        <td>${fmt(m.trade_count, 0)}</td>
        <td>${fmt(m.win_rate_pct)}</td>
        <td>${fmt(s.tstat)}</td>
        <td>${fmt(s.pvalue, 4)}</td>
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
        <span>Return %</span><b>${fmt(m.total_return_pct)}</b>
        <span>Sharpe</span><b>${fmt(m.sharpe)}</b>
        <span>Max DD %</span><b>${fmt(m.max_drawdown_pct)}</b>
        <span>Trades</span><b>${fmt(m.trade_count, 0)}</b>
        <span>t (HAC)</span><b>${fmt(s.tstat)}</b>
        <span>p-value</span><b>${fmt(s.pvalue, 4)}</b>
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
      <span class="verdict-stat">OOS decay <b>${fmt(decay)}</b> pts</span>
      <span class="verdict-stat">split @ bar <b>${fmt(out.split_index, 0)}</b></span>
      ${out.run_id ? `<span class="verdict-stat">run <b>${out.run_id}</b></span>` : ''}
    </div>
    <div class="wf-legs">
      ${legCard('In-sample', out.in_sample)}
      ${legCard('Out-of-sample', out.out_sample)}
    </div>
    <div class="verdict-note">Decay = OOS return − IS return. Strongly negative means the in-sample edge did not survive on unseen data.</div>
  `;
}

async function runWalkForward() {
  activateTab('research');
  setStatus(wfStatusBox, 'Running...');
  wfButton.disabled = true;
  try {
    const payload = buildBasePayload();
    payload.oos_fraction = Number(wfOosBox.value);
    const out = await fetchJson('/api/walkforward', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    currentRunId = out.run_id || '';
    renderWalkForward(out);
    renderDatasetSummary(out.source || {});
    renderSourceDetails(out.source || {}, payload);
    setStatus(wfStatusBox, out.storage_error ? 'Completed with storage warning' : 'Completed', out.storage_error ? 'warn' : 'good');
    await Promise.all([loadRunHistory(), loadDatasetHistory()]);
  } catch (error) {
    setStatus(wfStatusBox, `Error: ${error.message}`, 'bad');
  } finally {
    wfButton.disabled = false;
  }
}

async function runSweep() {
  activateTab('research');
  setStatus(sweepStatusBox, 'Sweeping...');
  sweepButton.disabled = true;
  try {
    const payload = buildBasePayload();
    payload.grid = safeJsonParse(sweepGridBox.value || '{}');
    payload.sort_by = sweepSortBox.value;
    const out = await fetchJson('/api/sweep', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    currentRunId = out.run_id || '';
    renderSweep(out);
    renderDatasetSummary(out.source || {});
    renderSourceDetails(out.source || {}, payload);
    setStatus(sweepStatusBox, `${out.count} combos complete`, out.storage_error ? 'warn' : 'good');
    await Promise.all([loadRunHistory(), loadDatasetHistory()]);
  } catch (error) {
    setStatus(sweepStatusBox, `Error: ${error.message}`, 'bad');
  } finally {
    sweepButton.disabled = false;
  }
}

async function loadRunHistory() {
  setStatus(historyStatusBox, 'Loading...');
  try {
    const out = await fetchJson('/api/runs?limit=30');
    const rows = out.runs || [];
    if (!rows.length) {
      runsBody.innerHTML = '<tr><td colspan="10" class="empty-state">No saved runs yet. Run a backtest, sweep, or walk-forward pass to build history.</td></tr>';
    } else {
      runsBody.innerHTML = rows.map((run) => {
        const metrics = run.metrics || {};
        const sig = run.significance || {};
        const checked = run.id === currentRunId ? 'checked' : '';
        return `
          <tr>
            <td><input type="checkbox" class="compare-run" value="${run.id}" ${checked} /></td>
            <td>${shortTime(run.created_at)}</td>
            <td>${escapeHtml(run.run_type)}</td>
            <td>${escapeHtml(run.symbol)}</td>
            <td>${escapeHtml(run.strategy)}</td>
            <td>${escapeHtml(`${run.interval} · ${run.provider}`)}</td>
            <td>${fmt(metrics.total_return_pct)}</td>
            <td>${fmt(metrics.sharpe)}</td>
            <td>${sig.significant ? 'real' : 'noise'}</td>
            <td><button type="button" class="ghost small load-run" data-run-id="${run.id}">Load</button></td>
          </tr>
        `;
      }).join('');
    }
    setStatus(historyStatusBox, `${rows.length} saved`, 'good');
  } catch (error) {
    setStatus(historyStatusBox, `Error: ${error.message}`, 'bad');
  }
}

async function loadDatasetHistory() {
  setStatus(datasetStatusBox, 'Loading...');
  try {
    const out = await fetchJson('/api/datasets?limit=20');
    const rows = out.datasets || [];
    if (!rows.length) {
      datasetsBody.innerHTML = '<tr><td colspan="7" class="empty-state">No dataset history yet. Dataset fetches will appear here after runs.</td></tr>';
    } else {
      datasetsBody.innerHTML = rows.map((row) => `
        <tr>
          <td>${shortTime(row.created_at)}</td>
          <td>${escapeHtml(row.provider)}</td>
          <td>${escapeHtml(row.symbol)}</td>
          <td>${escapeHtml(requestWindowLabel(row.source || {}, row.interval))}</td>
          <td>${fmt(row.rows, 0)}</td>
          <td>${escapeHtml(coverageSummary(row.start, row.end))}</td>
          <td>${escapeHtml(row.source_note || '-')}</td>
        </tr>
      `).join('');
    }
    setStatus(datasetStatusBox, `${rows.length} datasets`, 'good');
  } catch (error) {
    setStatus(datasetStatusBox, `Error: ${error.message}`, 'bad');
  }
}

async function loadSavedRun(runId) {
  activateTab('backtest');
  setStatus(statusBox, `Loading saved run ${runId}...`);
  try {
    const out = await fetchJson(`/api/runs/${runId}`);
    currentRunId = out.id;
    applyRequestToForm(out.request || {});
    const result = out.result || {};
    if (out.run_type === 'backtest') {
      renderMetrics(result.metrics || out.metrics || {});
      renderSignificance(result.significance || out.significance || {});
      renderTrades(result.trades || []);
      renderCharts(result.price_bars || [], result.curve || []);
    } else if (out.run_type === 'walkforward') {
      renderWalkForward({ ...result, run_id: out.id });
    } else if (out.run_type === 'sweep') {
      renderSweep(result);
    }
    const source = result.source || out.source || {};
    renderDatasetSummary(source);
    renderSourceDetails(source, out.request || {});
    setStatus(statusBox, `Loaded saved ${out.run_type}`, 'good');
    await loadRunHistory();
  } catch (error) {
    setStatus(statusBox, `Error: ${error.message}`, 'bad');
  }
}

async function compareSelectedRuns() {
  activateTab('history');
  const runIds = Array.from(document.querySelectorAll('.compare-run:checked')).map((node) => node.value);
  if (!runIds.length) {
    setStatus(compareStatusBox, 'Pick at least one saved run.', 'warn');
    return;
  }
  setStatus(compareStatusBox, 'Comparing...');
  try {
    const out = await fetchJson('/api/compare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_ids: runIds }),
    });
    compareBody.innerHTML = out.runs.map((run) => {
      const metrics = run.metrics || {};
      const sig = run.significance || {};
      return `
        <tr>
          <td>${shortTime(run.created_at)}</td>
          <td>${escapeHtml(run.run_type)}</td>
          <td>${escapeHtml(run.symbol)}</td>
          <td>${escapeHtml(run.strategy)}</td>
          <td>${escapeHtml(run.interval)}</td>
          <td>${fmt(metrics.total_return_pct)}</td>
          <td>${fmt(metrics.sharpe)}</td>
          <td>${fmt(metrics.max_drawdown_pct)}</td>
          <td>${fmt(metrics.trade_count, 0)}</td>
          <td>${sig.significant ? 'real' : 'noise'}</td>
        </tr>
      `;
    }).join('');
    renderCompareChart(out.chart_series || []);
    setStatus(compareStatusBox, `Compared ${out.count} run(s)`, 'good');
  } catch (error) {
    setStatus(compareStatusBox, `Error: ${error.message}`, 'bad');
  }
}

strategySelect?.addEventListener('change', (event) => syncParamsForStrategy(event.target.value));
providerSelect?.addEventListener('change', syncProviderFields);
loadExampleButton?.addEventListener('click', loadCustomExample);
sweepButton?.addEventListener('click', runSweep);
wfButton?.addEventListener('click', runWalkForward);
refreshRunsButton?.addEventListener('click', () => Promise.all([loadRunHistory(), loadDatasetHistory()]));
compareButton?.addEventListener('click', compareSelectedRuns);
tabButtons.forEach((button) => {
  button.addEventListener('click', () => activateTab(button.dataset.tab));
});
form?.addEventListener('submit', runBacktest);
runsBody?.addEventListener('click', (event) => {
  const button = event.target.closest('.load-run');
  if (!button) {
    return;
  }
  loadSavedRun(button.dataset.runId);
});

Promise.all([loadProviders(), loadStrategies(), loadRunHistory(), loadDatasetHistory()])
  .then(() => runBacktest(new Event('submit')))
  .catch((error) => {
    setStatus(statusBox, `Boot error: ${error.message}`, 'bad');
  });
