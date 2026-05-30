// EvoLab dashboard: poll /api/evolab and render. No deps, self-contained.
const $ = (id) => document.getElementById(id);

function fmtR(x) {
  return x === null || x === undefined ? "—" : (x >= 0 ? "+" : "") + Number(x).toFixed(4) + " R";
}

function daemonStatus(d) {
  if (!d || !d.last_cycle_ts) return '<span class="off">not running yet</span>';
  const ageSec = Math.round((Date.now() - d.last_cycle_ts) / 1000);
  const stale = ageSec > 300;
  return `<span class="${stale ? "stale" : "on"}">${stale ? "stale" : "running"} · last cycle ${ageSec}s ago</span>`;
}

function championCell(c) {
  if (!c) return '<span class="null">no champion — honest null</span>';
  const p = Object.entries(c.params || {}).map(([k, v]) => `${k}=${v}`).join(", ");
  return `<span class="champ">${c.family}</span> <span class="muted">${p}</span>` +
         `<br><small>OOS t=${(c.oos_t ?? 0).toFixed(2)}, p=${(c.oos_p ?? 1).toFixed(4)}</small>`;
}

async function refresh() {
  try {
    const r = await fetch("/api/evolab");
    const d = await r.json();
    $("trials").textContent = d.cumulative_trials.toLocaleString();
    $("alpha").textContent = d.alpha_deflated.toExponential(2);
    $("daemon").innerHTML = daemonStatus(d.daemon);
    const rows = (d.assets || []).map((a) =>
      `<tr><td class="asset">${a.asset}</td><td>${a.generation}</td>` +
      `<td>${fmtR(a.best_is_score)}</td><td>${championCell(a.champion)}</td></tr>`
    ).join("");
    $("rows").innerHTML = rows || '<tr><td colspan="4" class="muted">no assets searched yet — run <code>python -m evolab.search SOL</code></td></tr>';
    $("updated").textContent = "updated " + new Date().toLocaleTimeString();
  } catch (e) {
    $("rows").innerHTML = `<tr><td colspan="4" class="muted">error loading: ${e}</td></tr>`;
  }
}

refresh();
setInterval(refresh, 15000);
