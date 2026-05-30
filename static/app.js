// ---------------- element refs ----------------
const strategySelect = document.getElementById('strategy-select');
const providerSelect = document.getElementById('provider-select');
const filePathLabel = document.getElementById('file-path-label');
const filePathInput = document.getElementById('file-path-input');
const paramsBox = document.getElementById('params');
const customCodeBox = document.getElementById('custom_code');
const sourceBox = document.getElementById('source');
const statusBox = document.getElementById('status');
const runBadge = document.getElementById('run-badge');
const tradesBody = document.getElementById('trades-body');
const loadExampleButton = document.getElementById('load-example');
const form = document.getElementById('run-form');
const formSection = document.getElementById('form-section');
const toggleFormButton = document.getElementById('toggle-form');
const reportSection = document.getElementById('report');
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

// ---------------- formatting ----------------
const money0 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
const money2 = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });

function fmtMoney(n, dp = 2) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '--';
  return (dp === 0 ? money0 : money2).format(Number(n));
}
function fmtPct(n, dp = 2) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '--';
  const v = Number(n);
  return `${v >= 0 ? '+' : ''}${v.toFixed(dp)}%`;
}
function fmtNum(n, dp = 2) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return '--';
  return Number(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
function signClass(n) {
  const v = Number(n);
  if (!Number.isFinite(v) || v === 0) return '';
  return v > 0 ? 'good' : 'bad';
}
function fmtDate(iso) {
  if (!iso) return '--';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || 'Request failed');
  return body;
}

// ---------------- report header ----------------
function renderHeader(metrics, source) {
  const report = metrics.report || {};
  document.getElementById('rh-symbol').textContent = source?.symbol || metrics.strategy || '—';
  document.getElementById('rh-interval').textContent = metrics.interval || '';
  const start = fmtDate(metrics.start || metrics.report?.start);
  const end = fmtDate(metrics.end);
  document.getElementById('rh-range').textContent = `${metrics.start ? new Date(metrics.start).toDateString() : ''} — ${metrics.end ? new Date(metrics.end).toDateString() : ''} · ${metrics.bars ?? metrics.bars_4h ?? '—'} bars`;
  document.getElementById('rh-strategy').textContent = `Strategy: ${metrics.strategy} · params ${JSON.stringify(metrics.strategy_params || {})}`;

  const ret = metrics.total_return_pct;
  const retBadge = document.getElementById('rh-return');
  retBadge.textContent = fmtPct(ret);
  retBadge.className = `pill ${signClass(ret)}`;

  const engine = document.getElementById('rh-engine');
  engine.textContent = metrics.execution === 'bracket' ? 'ENGINE · BRACKET' : 'ENGINE · POSITION';
}

// ---------------- summary cards ----------------
function renderSummary(metrics) {
  const r = metrics.report || {};
  const cards = [
    { label: 'NET P&L', value: fmtMoney(r.net_pnl), sub: fmtPct(r.net_pnl_pct), cls: signClass(r.net_pnl) },
    { label: 'MAX DRAWDOWN', value: fmtPct(r.max_drawdown_pct), sub: fmtMoney(r.max_drawdown_value), cls: 'bad' },
    { label: 'TOTAL TRADES', value: String(r.total_trades ?? metrics.trade_count ?? 0), sub: `✓ ${r.wins ?? 0}  ✗ ${r.losses ?? 0}`, cls: '' },
    { label: 'WIN RATE', value: fmtPct(r.win_rate_pct, 1), sub: `avg win ${fmtMoney(r.avg_win)} / loss ${fmtMoney(r.avg_loss)}`, cls: 'good' },
    { label: 'PROFIT FACTOR', value: fmtNum(r.profit_factor, 2), sub: `avg trade ${fmtMoney(r.avg_trade)}`, cls: (r.profit_factor >= 1 ? 'good' : 'bad') },
  ];
  document.getElementById('summary-cards').innerHTML = cards.map((c) => `
    <div class="summary-card ${c.cls}">
      <div class="sc-label">${c.label}</div>
      <div class="sc-value">${c.value}</div>
      <div class="sc-sub">${c.sub}</div>
    </div>`).join('');
}

// ---------------- returns table ----------------
function renderReturns(report) {
  const s = report.splits || { all: {}, long: {}, short: {} };
  const rows = [
    ['Net P&L', (x) => fmtMoney(x.net_pnl), true],
    ['Net P&L %', (x) => fmtPct(x.net_pnl_pct), true],
    ['Profit Factor', (x) => fmtNum(x.profit_factor, 2), false],
    ['Win Rate', (x) => fmtPct(x.win_rate_pct, 1), false],
    ['Trades', (x) => String(x.trades ?? 0), false],
    ['Avg Trade', (x) => fmtMoney(x.avg_trade), true],
  ];
  const head = `<thead><tr><th></th><th>ALL</th><th>LONG</th><th>SHORT</th></tr></thead>`;
  const body = rows.map(([label, fn, colored]) => {
    const cell = (x) => {
      const val = fn(x);
      const cls = colored ? signClass(x.net_pnl ?? x.net_pnl_pct) : '';
      return `<td class="num ${cls}">${val}</td>`;
    };
    return `<tr><td>${label}</td>${cell(s.all)}${cell(s.long)}${cell(s.short)}</tr>`;
  }).join('');
  document.getElementById('returns-table').innerHTML = head + `<tbody>${body}</tbody>`;
}

// ---------------- profit structure ----------------
function renderProfitStructure(report) {
  const gp = Number(report.gross_profit) || 0;
  const gl = Math.abs(Number(report.gross_loss) || 0);
  const comm = Math.abs(Number(report.commission) || 0);
  const net = Number(report.net_pnl) || 0;
  const scale = Math.max(gp, gl, comm, Math.abs(net), 1);
  const row = (label, value, fillCls, width, display) => `
    <div class="ps-row">
      <div class="ps-label">${label}</div>
      <div class="ps-bar"><div class="ps-fill ${fillCls}" style="width:${Math.max(width, 1)}%"></div></div>
      <div class="ps-value">${display}</div>
    </div>`;
  document.getElementById('profit-structure').innerHTML = [
    row('Gross Profit', gp, 'good', (gp / scale) * 100, fmtMoney(report.gross_profit, 0)),
    row('Gross Loss', gl, 'bad', (gl / scale) * 100, fmtMoney(report.gross_loss, 0)),
    row('Commission', comm, 'bad', (comm / scale) * 100, fmtMoney(-comm, 0)),
    row('Net P&L', Math.abs(net), 'accent', (Math.abs(net) / scale) * 100, fmtMoney(net, 0)),
  ].join('');
}

// ---------------- risk grid ----------------
function renderRisk(report, metrics) {
  const items = [
    ['SHARPE RATIO', fmtNum(report.sharpe ?? metrics.sharpe, 2), ''],
    ['SORTINO RATIO', fmtNum(report.sortino, 2), ''],
    ['MAX DRAWDOWN', fmtPct(report.max_drawdown_pct), 'bad'],
    ['MAX RUN-UP', fmtPct(report.max_runup_pct), 'good'],
    ['AVG BARS / TRADE', fmtNum(report.avg_bars_in_trade, 1), ''],
    ['INITIAL CAPITAL', fmtMoney(report.initial_capital, 0), ''],
  ];
  document.getElementById('risk-grid').innerHTML = items.map(([label, value, cls]) => `
    <div class="risk-item">
      <div class="ri-label">${label}</div>
      <div class="ri-value ${cls}">${value}</div>
    </div>`).join('');
}

// ---------------- win/loss donut ----------------
function renderWinLoss(report) {
  const wins = report.wins ?? 0;
  const losses = report.losses ?? 0;
  Plotly.newPlot('winloss-chart', [{
    type: 'pie',
    hole: 0.62,
    values: [wins, losses],
    labels: ['Wins', 'Losses'],
    marker: { colors: ['#22c55e', '#ef4444'] },
    textinfo: 'none',
    hoverinfo: 'label+value+percent',
    sort: false,
  }], {
    paper_bgcolor: 'transparent',
    font: { color: '#e8edf9' },
    showlegend: false,
    margin: { l: 10, r: 10, t: 10, b: 10 },
    annotations: [{ text: `<b>${fmtPct(report.win_rate_pct, 1)}</b><br>Win Rate`, showarrow: false, font: { size: 16 } }],
  }, { responsive: true, displayModeBar: false });
  document.getElementById('winloss-legend').innerHTML =
    `<span><span class="dot good"></span>Wins: ${wins}</span><span><span class="dot bad"></span>Losses: ${losses}</span>`;
}

// ---------------- distribution histogram ----------------
function renderDistribution(dist) {
  if (!dist || !dist.counts || !dist.counts.length) {
    Plotly.purge('dist-chart');
    return;
  }
  Plotly.newPlot('dist-chart', [{
    type: 'bar',
    x: dist.centers,
    y: dist.counts,
    marker: { color: dist.colors.map((c) => (c === 'good' ? '#22c55e' : '#ef4444')) },
    hovertemplate: '%{x:.2f}%%: %{y} trades<extra></extra>',
  }], {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: '#8b95ad', size: 11 },
    margin: { l: 30, r: 20, t: 10, b: 30 },
    bargap: 0.08,
    xaxis: { ticksuffix: '%', gridcolor: 'rgba(255,255,255,0.04)' },
    yaxis: { gridcolor: 'rgba(255,255,255,0.04)' },
    shapes: [
      vline(dist.avg_loss_pct, '#ef4444'),
      vline(dist.avg_win_pct, '#22c55e'),
    ],
  }, { responsive: true, displayModeBar: false });
}
function vline(x, color) {
  return { type: 'line', x0: x, x1: x, yref: 'paper', y0: 0, y1: 1, line: { color, width: 1, dash: 'dot' } };
}

// ---------------- performance details table ----------------
function renderDetails(metrics) {
  const r = metrics.report || {};
  const s = r.splits || { all: {}, long: {}, short: {} };
  const triple = (fn, colored) => {
    const cell = (x) => {
      const v = fn(x);
      const cls = colored ? signClass(x.net_pnl ?? x.net_pnl_pct) : '';
      return `<td class="num ${cls}">${v}</td>`;
    };
    return cell(s.all) + cell(s.long) + cell(s.short);
  };
  const allOnly = (val, cls = '') => `<td class="num ${cls}">${val}</td><td class="num">--</td><td class="num">--</td>`;
  const group = (name) => `<tr class="group-row"><td colspan="4">${name}</td></tr>`;
  const rows = [];
  rows.push(group('PERFORMANCE'));
  rows.push(`<tr><td>Net Profit</td>${triple((x) => fmtMoney(x.net_pnl), true)}</tr>`);
  rows.push(`<tr><td>Net Profit %</td>${triple((x) => fmtPct(x.net_pnl_pct), true)}</tr>`);
  rows.push(`<tr><td>Gross Profit</td>${triple((x) => fmtMoney(x.gross_profit), false)}</tr>`);
  rows.push(`<tr><td>Gross Loss</td>${triple((x) => fmtMoney(x.gross_loss), false)}</tr>`);
  rows.push(`<tr><td>Commission</td>${allOnly(fmtMoney(-Math.abs(r.commission || 0)))}</tr>`);
  rows.push(group('RATIOS'));
  rows.push(`<tr><td>Profit Factor</td>${triple((x) => fmtNum(x.profit_factor, 2), false)}</tr>`);
  rows.push(`<tr><td>Max Drawdown</td>${allOnly(`${fmtPct(r.max_drawdown_pct)} / ${fmtMoney(r.max_drawdown_value)}`, 'bad')}</tr>`);
  rows.push(`<tr><td>Max Run-up</td>${allOnly(`${fmtPct(r.max_runup_pct)} / ${fmtMoney(r.max_runup_value)}`, 'good')}</tr>`);
  rows.push(`<tr><td>Sharpe Ratio</td>${allOnly(fmtNum(r.sharpe, 2))}</tr>`);
  rows.push(`<tr><td>Sortino Ratio</td>${allOnly(fmtNum(r.sortino, 2))}</tr>`);
  rows.push(group('TRADES'));
  rows.push(`<tr><td>Total Trades</td>${triple((x) => String(x.trades ?? 0), false)}</tr>`);
  rows.push(`<tr><td>Winning Trades</td>${triple((x) => String(x.wins ?? 0), false)}</tr>`);
  rows.push(`<tr><td>Losing Trades</td>${triple((x) => String(x.losses ?? 0), false)}</tr>`);
  rows.push(`<tr><td>Win Rate</td>${triple((x) => fmtPct(x.win_rate_pct, 1), false)}</tr>`);
  rows.push(`<tr><td>Avg Winning Trade</td>${allOnly(fmtMoney(r.avg_win), 'good')}</tr>`);
  rows.push(`<tr><td>Avg Losing Trade</td>${allOnly(fmtMoney(r.avg_loss), 'bad')}</tr>`);
  rows.push(`<tr><td>Avg Trade P&L</td>${allOnly(fmtMoney(r.avg_trade), signClass(r.avg_trade))}</tr>`);
  rows.push(`<tr><td>Largest Win</td>${allOnly(fmtMoney(r.largest_win), 'good')}</tr>`);
  rows.push(`<tr><td>Largest Loss</td>${allOnly(fmtMoney(r.largest_loss), 'bad')}</tr>`);
  rows.push(`<tr><td>Avg Bars in Trade</td>${allOnly(fmtNum(r.avg_bars_in_trade, 1))}</tr>`);

  const head = `<thead><tr><th></th><th>ALL</th><th>LONG</th><th>SHORT</th></tr></thead>`;
  document.getElementById('details-table').innerHTML = head + `<tbody>${rows.join('')}</tbody>`;
}

// ---------------- equity + drawdown charts ----------------
function renderCharts(curve) {
  const time = curve.map((row) => row.time);
  Plotly.newPlot('equity-chart', [{
    x: time,
    y: curve.map((row) => row.equity),
    type: 'scatter',
    mode: 'lines',
    fill: 'tozeroy',
    fillcolor: 'rgba(124,92,252,0.18)',
    line: { color: '#7c5cfc', width: 2 },
    name: 'Equity',
  }], {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: '#8b95ad', size: 11 },
    margin: { l: 56, r: 20, t: 10, b: 30 },
    xaxis: { gridcolor: 'rgba(255,255,255,0.04)' },
    yaxis: { gridcolor: 'rgba(255,255,255,0.04)', tickprefix: '$' },
    showlegend: false,
  }, { responsive: true, displayModeBar: false });

  Plotly.newPlot('drawdown-chart', [{
    x: time,
    y: curve.map((row) => row.drawdown),
    type: 'scatter',
    fill: 'tozeroy',
    line: { color: '#ef4444', width: 1 },
    fillcolor: 'rgba(239,68,68,0.25)',
    name: 'Drawdown %',
  }], {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: '#8b95ad', size: 11 },
    margin: { l: 56, r: 20, t: 4, b: 24 },
    xaxis: { gridcolor: 'rgba(255,255,255,0.04)' },
    yaxis: { gridcolor: 'rgba(255,255,255,0.04)', ticksuffix: '%' },
    showlegend: false,
  }, { responsive: true, displayModeBar: false });
}

// ---------------- significance verdict ----------------
function renderSignificance(sig) {
  if (!sig || sig.n < 2) { significanceBox.innerHTML = '<div class="verdict-note">Not enough data for a significance test.</div>'; return; }
  const real = sig.significant;
  const cls = real ? 'good' : 'bad';
  const verdict = real ? 'LIKELY REAL' : 'NOT SIGNIFICANT';
  const basis = sig.basis ? ` · ${sig.basis}` : '';
  significanceBox.innerHTML = `
    <div class="verdict-row ${cls}">
      <span class="verdict-tag">${verdict}</span>
      <span class="verdict-stat">t&nbsp;<b>${sig.tstat}</b></span>
      <span class="verdict-stat">p&nbsp;<b>${sig.pvalue}</b></span>
      <span class="verdict-stat">n&nbsp;${sig.n}${basis}</span>
    </div>
    <div class="verdict-note">Edge is trustworthy only when |t| &ge; 2 and p &lt; 0.05. A great curve with weak stats is noise.</div>`;
}

// ---------------- trade list ----------------
function renderTrades(trades) {
  document.getElementById('trade-count').textContent = trades.length ? `· ${trades.length} shown` : '';
  if (!trades.length) {
    tradesBody.innerHTML = '<tr><td colspan="15">No completed trades.</td></tr>';
    return;
  }
  tradesBody.innerHTML = trades.map((t, i) => `
    <tr>
      <td>${i + 1}</td>
      <td class="side-${t.side}">${(t.side || '').toUpperCase()}</td>
      <td>${fmtDate(t.entry_at)}</td>
      <td>${fmtMoney(t.entry_price)}</td>
      <td>${fmtDate(t.exit_at)}</td>
      <td>${fmtMoney(t.exit_price)}</td>
      <td>${fmtNum(t.qty, 4)}</td>
      <td>${t.bars ?? '--'}</td>
      <td class="num ${signClass(t.net_pnl)}">${fmtMoney(t.net_pnl)}</td>
      <td class="num ${signClass(t.pnl_pct)}">${fmtPct(t.pnl_pct)}</td>
      <td class="num ${signClass(t.gross_pnl)}">${fmtMoney(t.gross_pnl)}</td>
      <td>${fmtMoney(t.commission)}</td>
      <td class="num ${signClass(t.cum_pnl)}">${fmtMoney(t.cum_pnl)}</td>
      <td class="num good">${fmtMoney(t.runup)}</td>
      <td class="num bad">${fmtMoney(t.drawdown)}</td>
    </tr>`).join('');
}

// ---------------- orchestration ----------------
function renderReport(result) {
  const metrics = result.metrics;
  renderHeader(metrics, result.source);
  renderSummary(metrics);
  renderCharts(result.curve);
  if (metrics.report) {
    renderReturns(metrics.report);
    renderProfitStructure(metrics.report);
    renderRisk(metrics.report, metrics);
    renderWinLoss(metrics.report);
    renderDistribution(metrics.report.distribution);
    renderDetails(metrics);
  }
  renderSignificance(result.significance);
  renderTrades(result.trades || []);
  sourceBox.textContent = JSON.stringify(result.source, null, 2);
  reportSection.classList.remove('hidden');
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

async function runBacktest(event) {
  if (event) event.preventDefault();
  statusBox.textContent = 'Running...';
  runBadge.textContent = 'Running...';
  runBadge.className = 'pill muted-pill';
  try {
    const result = await fetchJson('/api/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildBasePayload()),
    });
    renderReport(result);
    statusBox.textContent = 'Done';
    const ret = result.metrics.total_return_pct;
    runBadge.textContent = fmtPct(ret);
    runBadge.className = `pill ${signClass(ret)}`;
  } catch (error) {
    statusBox.textContent = `Error: ${error.message}`;
    runBadge.textContent = 'Error';
    runBadge.className = 'pill bad';
  }
}

// ---------------- strategy / provider config ----------------
function syncParamsForStrategy(name) {
  const preset = strategies[name]?.params || {};
  paramsBox.value = JSON.stringify(name === 'custom_python' ? {} : preset, null, 2);
}
function syncProviderFields() {
  const provider = providers[providerSelect.value];
  const needsFile = Boolean(provider?.supports_files);
  filePathLabel.classList.toggle('hidden', !needsFile);
  filePathInput.required = needsFile;
}
async function loadStrategies() {
  strategies = await fetchJson('/api/strategies');
  strategySelect.innerHTML = Object.entries(strategies)
    .map(([name, config]) => `<option value="${name}">${config.label}</option>`).join('');
  syncParamsForStrategy(strategySelect.value);
}
async function loadProviders() {
  providers = await fetchJson('/api/providers');
  providerSelect.innerHTML = Object.entries(providers)
    .map(([name, config]) => `<option value="${name}">${config.label}</option>`).join('');
  providerSelect.value = providers.yahoo ? 'yahoo' : Object.keys(providers)[0];
  syncProviderFields();
}
async function loadCustomExample() {
  const result = await fetchJson('/api/example/custom-strategy');
  strategySelect.value = 'custom_python';
  paramsBox.value = JSON.stringify({ fast: 10, slow: 30 }, null, 2);
  customCodeBox.value = result.code;
}

// ---------------- sweep ----------------
function renderSweep(out) {
  const runs = out.runs || [];
  if (!runs.length) { sweepBody.innerHTML = '<tr><td colspan="9">No runs.</td></tr>'; return; }
  const bestKey = JSON.stringify(out.best?.params);
  sweepBody.innerHTML = runs.map((run) => {
    if (run.error || !run.metrics) {
      return `<tr class="err"><td>${JSON.stringify(run.params)}</td><td colspan="8">${run.error || 'failed'}</td></tr>`;
    }
    const m = run.metrics;
    const s = run.significance || {};
    const isBest = JSON.stringify(run.params) === bestKey;
    const sigCls = s.significant ? 'good' : 'bad';
    return `<tr class="${isBest ? 'best' : ''}">
      <td>${JSON.stringify(run.params)}</td>
      <td>${m.total_return_pct}</td><td>${m.sharpe}</td><td>${m.max_drawdown_pct}</td>
      <td>${m.trade_count}</td><td>${m.win_rate_pct}</td>
      <td>${s.tstat ?? '-'}</td><td>${s.pvalue ?? '-'}</td>
      <td class="${sigCls}">${s.significant ? 'real' : 'noise'}</td>
    </tr>`;
  }).join('');
}
async function runSweep() {
  sweepStatusBox.textContent = 'Sweeping...';
  sweepButton.disabled = true;
  try {
    const payload = buildBasePayload();
    payload.grid = JSON.parse(sweepGridBox.value || '{}');
    payload.sort_by = sweepSortBox.value;
    const out = await fetchJson('/api/sweep', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    renderSweep(out);
    sweepStatusBox.textContent = `Done — ${out.count} combos`;
  } catch (error) {
    sweepStatusBox.textContent = `Error: ${error.message}`;
  } finally {
    sweepButton.disabled = false;
  }
}

// ---------------- walk-forward ----------------
function legCard(title, leg) {
  const m = leg.metrics;
  const s = leg.significance || {};
  const sigCls = s.significant ? 'good' : 'bad';
  return `<div class="wf-leg">
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
  </div>`;
}
function renderWalkForward(out) {
  const held = out.holds_out_of_sample;
  const cls = held ? 'good' : 'bad';
  wfResultBox.innerHTML = `
    <div class="wf-banner ${cls}">
      <span class="verdict-tag">${held ? 'HOLDS OUT OF SAMPLE' : 'DID NOT HOLD'}</span>
      <span class="verdict-stat">OOS decay&nbsp;<b>${out.decay}</b> pts</span>
      <span class="verdict-stat">split @ bar&nbsp;${out.split_index}</span>
    </div>
    <div class="wf-legs">${legCard('In-sample', out.in_sample)}${legCard('Out-of-sample', out.out_sample)}</div>
    <div class="verdict-note">Decay = OOS return − IS return. Strongly negative means the in-sample edge did not survive on unseen data.</div>`;
}
async function runWalkForward() {
  wfStatusBox.textContent = 'Running...';
  wfButton.disabled = true;
  try {
    const payload = buildBasePayload();
    payload.oos_fraction = Number(wfOosBox.value);
    const out = await fetchJson('/api/walkforward', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    renderWalkForward(out);
    wfStatusBox.textContent = 'Done';
  } catch (error) {
    wfStatusBox.textContent = `Error: ${error.message}`;
  } finally {
    wfButton.disabled = false;
  }
}

// ---------------- events ----------------
strategySelect?.addEventListener('change', (event) => syncParamsForStrategy(event.target.value));
providerSelect?.addEventListener('change', syncProviderFields);
loadExampleButton?.addEventListener('click', loadCustomExample);
sweepButton?.addEventListener('click', runSweep);
wfButton?.addEventListener('click', runWalkForward);
form?.addEventListener('submit', runBacktest);
toggleFormButton?.addEventListener('click', () => formSection.classList.toggle('hidden'));

Promise.all([loadProviders(), loadStrategies()])
  .then(() => runBacktest())
  .catch((error) => { statusBox.textContent = `Boot error: ${error.message}`; });
