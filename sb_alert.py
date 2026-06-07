import json, os, sys, datetime as dt, urllib.request, urllib.parse
import yfinance as yf
import pandas as pd

BASE = "/root/apps/backtest-lab"
STATE = f"{BASE}/sb_alert_state.json"
REC   = f"{BASE}/sb_alerts.jsonl"
RELAY = "/root/apps/ict-autopilot/relay.env"
TZ = "America/New_York"
KZ_START, KZ_END, REF_START = "10:00", "11:00", "09:30"
EMA_PERIOD, RR = 20, 2.0

def load_env(p):
    e = {}
    for ln in open(p):
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1); e[k] = v.strip()
    return e

def telegram(text):
    e = load_env(RELAY)
    tok, chat = e.get("TELEGRAM_BOT_TOKEN"), e.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return "no-creds"
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        return urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20).read().decode()[:60]
    except Exception as ex:
        return f"ERR {ex}"

def flat(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def detect(day, i5, bias, pdh, pdl):
    etidx = i5.index.tz_convert(TZ)
    mask = [d == day for d in etidx.date]
    df = i5[mask]
    if df.empty:
        return None
    et = df.index.tz_convert(TZ)
    times = list(et.strftime("%H:%M"))
    high = list(df["High"].astype(float).values)
    low  = list(df["Low"].astype(float).values)
    close= list(df["Close"].astype(float).values)
    n = len(df)
    bull = [False]*n; bear = [False]*n
    for i in range(2, n):
        if low[i] > high[i-2]: bull[i] = True
        if high[i] < low[i-2]: bear[i] = True
    ref_hi=-1e18; ref_lo=1e18; day_hi=-1e18; day_lo=1e18
    swept_high=False; swept_low=False
    mid = (pdh+pdl)/2.0 if (pdh and pdl) else None
    for i in range(n):
        t = times[i]
        if high[i] > day_hi: day_hi = high[i]
        if low[i] < day_lo: day_lo = low[i]
        if REF_START <= t < KZ_START:
            ref_hi = max(ref_hi, high[i]); ref_lo = min(ref_lo, low[i])
        if KZ_START <= t < KZ_END and ref_hi > -1e17:
            if high[i] > ref_hi: swept_high = True
            if low[i] < ref_lo: swept_low = True
            entry = close[i]
            in_disc = (mid is None) or (entry < mid)
            in_prem = (mid is None) or (entry > mid)
            if swept_high and bear[i] and bias < 0 and in_prem:
                risk = day_hi - entry
                if risk > 0:
                    return {"dir":"short","entry":round(entry,1),"stop":round(day_hi,1),
                            "target":round(entry-RR*risk,1),"time_et":et[i].strftime("%H:%M"),
                            "utc":df.index[i].strftime("%H:%M"),"swept":round(ref_hi,1)}
            if swept_low and bull[i] and bias > 0 and in_disc:
                risk = entry - day_lo
                if risk > 0:
                    return {"dir":"long","entry":round(entry,1),"stop":round(day_lo,1),
                            "target":round(entry+RR*risk,1),"time_et":et[i].strftime("%H:%M"),
                            "utc":df.index[i].strftime("%H:%M"),"swept":round(ref_lo,1)}
    return None

def gst(utc_hhmm):
    h, m = map(int, utc_hhmm.split(":"))
    return f"{(h+4)%24:02d}:{m:02d}"

def main():
    daily = flat(yf.download("^NDX", period="60d", interval="1d", progress=False))
    i5 = flat(yf.download("^NDX", period="5d", interval="5m", progress=False))
    target = sorted(set(i5.index.tz_convert(TZ).date))[-1]
    ema = daily["Close"].ewm(span=EMA_PERIOD, adjust=False).mean()
    pp = [i for i, ts in enumerate(daily.index) if ts.date() < target][-1]
    bias = 1 if float(daily["Close"].iloc[pp]) > float(ema.iloc[pp]) else -1
    pdh, pdl = float(daily["High"].iloc[pp]), float(daily["Low"].iloc[pp])
    res = detect(target, i5, bias, pdh, pdl)
    print(f"target={target} bias={'UP' if bias>0 else 'DOWN'} PDH={pdh:.0f} PDL={pdl:.0f} -> setup: {res}")

    if os.environ.get("TESTPING") == "1":
        print("test ping:", telegram("✅ <b>US100 SB screener</b> is wired up. You'll get an alert only when a bias-aligned Silver Bullet setup forms in the NY killzone. (Screener is breakeven mechanically — your discretion is the edge.)"))

    if res is None:
        return
    state = {}
    if os.path.exists(STATE):
        state = json.load(open(STATE))
    key = f"{target}:{res['dir']}"
    if state.get("last") == key:
        print("already alerted", key); return

    arrow = "🟢 LONG" if res["dir"] == "long" else "🔴 SHORT"
    msg = (f"{arrow} <b>US100 Silver Bullet</b> — bias {'UP' if bias>0 else 'DOWN'}\n"
           f"Swept {res['swept']} → entry ~{res['entry']}\n"
           f"Stop {res['stop']} | Target {res['target']} (2R)\n"
           f"{res['time_et']} ET / {gst(res['utc'])} GST\n"
           f"⚠️ Screener is breakeven — <b>your call decides.</b> Journal it:\n\n"
           f"<code>## {target} — US100 {res['dir']}\n"
           f"instrument:: US100\ndirection:: {res['dir']}\nresult:: \nR:: \n"
           f"- Setup: SB NY-AM killzone, bias {'up' if bias>0 else 'down'}. [[ICT Methodology]]\n"
           f"- Bias before entry: \n- Entry: {res['entry']} @ {gst(res['utc'])} GST\n"
           f"- Stop: {res['stop']} | Target: {res['target']}\n"
           f"- What happened: \n- Mistake / change: \n- Rule followed/broken: </code>")
    print("alert:", telegram(msg))
    with open(REC, "a") as f:
        f.write(json.dumps({"date": str(target), "bias": bias, **res}, default=float) + "\n")
    json.dump({"last": key, "ts": str(target)}, open(STATE, "w"))

if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print("sb_alert error:", ex)
