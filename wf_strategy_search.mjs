export const meta = {
  name: 'azc-strategy-search',
  description: 'Honest fee-accurate AZC strategy search across the fixture catalog; finds best asset+strategy and gives a real/noise fundability verdict',
  whenToUse: 'When AZC needs a fundable strategy and you want an exhaustive honest sweep of the backtest-lab engine',
  phases: [
    { title: 'Search', detail: '6 lanes sweep 25 assets at 7.5bps taker via wf_probe' },
    { title: 'Verify', detail: 'adversarial OOS + double-fee + param-neighbor stress on top candidates' },
    { title: 'Synthesize', detail: 'leaderboard + honest fundability verdict + evolab/dashboard shortlist' },
  ],
}

const DIR = '/root/apps/backtest-lab'
const FEE = 7.5 // real MEXC taker, bps — the honest fee wall
const ASSETS = ['AAVE','ADA','ALGO','APT','ARB','ATOM','AVAX','BCH','BNB','BTC','DOGE','DOT','EOS','ETC','ETH','ICP','LINK','LTC','NEAR','RUNE','SOL','SUI','TRX','UNI','XRP']
const sym = a => `${a}-1095d-Min60`

const TREND_CFGS = [{}, {erMin:0.25}, {erMin:0.45}, {trail:2}, {trail:4}, {don:20}]
const MEANREV_CFGS = [{}, {rr:1.0}, {rr:1.5}, {don:20}, {don:40}, {atrMult:1.5}]

const lbl = p => Object.keys(p).length ? Object.entries(p).map(([k,v])=>`${k}=${v}`).join(',') : 'default'
const batchFor = (strategy, cfgs) =>
  ASSETS.flatMap(a => cfgs.map(p => ({symbol: sym(a), strategy, params: p, fee_bps: FEE})))
const genBatch = strategy => ASSETS.map(a => ({symbol: sym(a), strategy, params: {}, fee_bps: FEE}))

const cmd = batch => `cd ${DIR} && python3 wf_probe.py '${JSON.stringify(batch)}'`

const FINDER_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['rows'],
  properties: {
    rows: { type: 'array', items: {
      type: 'object', additionalProperties: false,
      required: ['symbol','params_label','trades','netR_per_trade','total_r','win_rate_pct','tstat','pvalue','significant'],
      properties: {
        symbol: {type:'string'}, params_label: {type:'string'},
        trades: {type:['integer','null']}, netR_per_trade: {type:['number','null']},
        total_r: {type:['number','null']}, win_rate_pct: {type:['number','null']},
        tstat: {type:['number','null']}, pvalue: {type:['number','null']},
        significant: {type:['boolean','null']},
      },
    }},
    note: {type:'string'},
  },
}

const VERIFY_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['symbol','strategy','params_label','full_tstat','oos_tstat','oos_netR','stress15_netR','neighbors_same_sign','neighbors_total','verdict','reasoning'],
  properties: {
    symbol:{type:'string'}, strategy:{type:'string'}, params_label:{type:'string'},
    full_tstat:{type:['number','null']}, oos_tstat:{type:['number','null']}, oos_netR:{type:['number','null']},
    stress15_netR:{type:['number','null']},
    neighbors_same_sign:{type:'integer'}, neighbors_total:{type:'integer'},
    verdict:{type:'string', enum:['REAL','BORDERLINE','NOISE','FRAGILE']},
    reasoning:{type:'string'},
  },
}

const finderPrompt = (name, batch) => `You are a mechanical backtest runner. Run EXACTLY this one command (it runs ${batch.length} honest fee-accurate backtests, ~30-90s):

${cmd(batch)}

It prints one JSON object per line. Each has: symbol, params, trades, netR_per_trade, total_r, win_rate_pct, tstat (HAC Newey-West t-stat on per-trade netR), pvalue, significant. Some lines may have an "error" field — skip those, count them in your note.

Map every successful line to a row: symbol (keep the full fixture stem), params_label (compact like "erMin=0.25" or "default"), trades, netR_per_trade, total_r, win_rate_pct, tstat, pvalue, significant. Sort rows by tstat DESCENDING (nulls last). Return ALL rows. In "note", state how many probes ran, how many errored, and the single best (symbol, params, tstat). Do not editorialize beyond that. Lane: ${name}.`

// ---------- Phase 1: Search ----------
phase('Search')
const finderDefs = [
  ['azc_trend', batchFor('azc_trend', TREND_CFGS)],
  ['azc_meanrev', batchFor('azc_meanrev', MEANREV_CFGS)],
  ['sma_cross', genBatch('sma_cross')],
  ['rsi_reversion', genBatch('rsi_reversion')],
  ['breakout', genBatch('breakout')],
  ['trend_trail', genBatch('trend_trail')],
]

const finderResults = await parallel(finderDefs.map(([name, batch]) => () =>
  agent(finderPrompt(name, batch), {label: `search:${name}`, phase: 'Search', schema: FINDER_SCHEMA})
    .then(r => ({name, rows: (r && r.rows) || [], note: r && r.note}))
))

const allRows = finderResults.filter(Boolean).flatMap(r =>
  r.rows.map(row => ({...row, strategy: r.name})))
log(`Search done: ${allRows.length} backtests across ${finderDefs.length} lanes.`)

// Candidates = the honest bracket lanes only (per-trade netR HAC basis), enough trades, best t-stats.
const BRACKET = new Set(['azc_trend','azc_meanrev'])
const candidates = allRows
  .filter(r => BRACKET.has(r.strategy) && (r.trades||0) >= 30 && r.tstat != null)
  .sort((a,b) => b.tstat - a.tstat)
  .slice(0, 8)
log(`Top candidate (bracket, n>=30): ${candidates[0] ? `${candidates[0].symbol} ${candidates[0].strategy} ${candidates[0].params_label} t=${candidates[0].tstat}` : 'none'}`)

// ---------- Phase 2: Verify ----------
phase('Verify')
const verifyPrompt = c => `Adversarially stress-test whether this is a REAL edge or curve-fit noise. Default to skepticism — call it NOISE/FRAGILE unless it survives every check.

Candidate: symbol=${c.symbol} strategy=${c.strategy} params=${c.params_label} (full-sample HAC t=${c.tstat}, netR/trade=${c.netR_per_trade}, trades=${c.trades}).

Use the probe at ${DIR}. params_label "default" means params {}. Build the JSON params object from params_label (e.g. "erMin=0.25" -> {"erMin":0.25}). Run these via ONE batched call (a JSON array as argv[1]):
  cd ${DIR} && python3 wf_probe.py '[ ...specs... ]'
Each spec: {"symbol":"${c.symbol}","strategy":"${c.strategy}","params":<obj>,"fee_bps":7.5,...}. Include in the batch:
 1. OOS tail: add "oos_fraction":0.3 (same params, trailing 30% only).
 2. Fee stress: "fee_bps":15 (double taker), oos_fraction 0.
 3. THREE param-neighbor configs (perturb the candidate's params slightly, e.g. nudge erMin/trail/don/rr/atrMult by one step), each at fee_bps 7.5, oos_fraction 0.

Read each output line's tstat / netR_per_trade / significant. Then decide:
 - REAL: full t>=2 AND OOS netR same sign as full AND survives 15bps with positive netR AND >=2/3 neighbors keep the same netR sign.
 - BORDERLINE: positive & directionally stable but full t in [1.3,2) or fails exactly one check.
 - FRAGILE: flips sign under fee-stress or across neighbors.
 - NOISE: OOS sign flip or near-zero/negative netR.
Report full_tstat, oos_tstat, oos_netR (netR_per_trade on the OOS run), stress15_netR (netR_per_trade at 15bps), neighbors_same_sign / neighbors_total, verdict, and a one-paragraph reasoning citing the numbers.`

const verdicts = candidates.length
  ? (await parallel(candidates.map(c => () =>
      agent(verifyPrompt(c), {label: `verify:${c.symbol}:${c.strategy}`, phase: 'Verify', schema: VERIFY_SCHEMA})
    ))).filter(Boolean)
  : []

// ---------- Phase 3: Synthesize ----------
phase('Synthesize')
const top20 = [...allRows].filter(r=>r.tstat!=null).sort((a,b)=>b.tstat-a.tstat).slice(0,20)
const synthPrompt = `You are the lead quant writing the verdict for Ahmed's AZC strategy search. Be blunt, no filler, no emojis. The honest reality on this VPS: nothing has cleared HAC t>=2 OOS after real fees — the binding constraint is data+fees, not model capacity. Report the truth; do NOT manufacture a winner.

INPUTS:
Top-20 backtests by HAC t-stat (all lanes; azc_trend/azc_meanrev use per-trade netR HAC basis, generic sma/rsi/breakout/trend_trail use bar-return basis and are NOT directly fundable-comparable):
${JSON.stringify(top20, null, 0)}

Adversarial verify verdicts on the bracket candidates:
${JSON.stringify(verdicts, null, 0)}

Write a markdown report with:
1. **Leaderboard** — a table of the top ~12 (rank, symbol, strategy, params, trades, netR/trade, t-stat, verdict if verified). Mark generic-lane rows as (bar-basis).
2. **Verdict** — is anything fundable (REAL and survives fees+OOS)? State it plainly. If nothing clears the bar, say so and name the closest 2-3 (asset+strategy+config) as research leads only.
3. **Shortlist to ingest** — the 1-3 exact specs (symbol, strategy, params) most worth pinning in the tester dashboard for Ahmed to review. Return these ALSO as a fenced \`\`\`json array of {symbol,strategy,params} so they can be machine-read.
4. **EvoLab guidance** — one or two concrete directions to feed the evolab bot next (param regions, assets, or a different strategy family), grounded in what the sweep showed.
Keep it tight and decision-grade.`

const report = await agent(synthPrompt, {label: 'synthesize', phase: 'Synthesize'})

return {
  backtests_run: allRows.length,
  candidates_verified: verdicts.length,
  real_count: verdicts.filter(v=>v.verdict==='REAL').length,
  borderline_count: verdicts.filter(v=>v.verdict==='BORDERLINE').length,
  top20,
  verdicts,
  report,
}
