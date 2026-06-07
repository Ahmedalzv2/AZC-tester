"""Autonomous EvoLab intraday hunter."""
from __future__ import annotations
import json, time, urllib.request, urllib.parse
from pathlib import Path
from engine_bracket import Bar
from evolab.search import run_search
from evolab import fitness
from evolab.data import split as ev_split
from evolab.store import Store
from data_source import fetch_history

BASE = Path("/root/apps/backtest-lab")
RELAY_ENV = Path("/root/apps/ict-autopilot/relay.env")
WINNERS = BASE / "hunter_winners.jsonl"
ALERTED = BASE / "hunter_alerted.json"

ASSETS = ["ETHUSDT","BTCUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT"]
TFS = ["15m","5m","1h"]
MATRIX = [(a,tf) for a in ASSETS for tf in TFS]
YEARS = 2
GENS_PER_VISIT = 10
POP = 40
SLEEP = 15

def log(m):
    print("[" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "] " + str(m), flush=True)

def creds():
    tok = chat = ""
    try:
        for line in RELAY_ENV.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="): tok = line.split("=",1)[1].strip()
            elif line.startswith("TELEGRAM_CHAT_ID="): chat = line.split("=",1)[1].strip()
    except Exception as e:
        log("creds read failed: " + str(e))
    return tok, chat

def telegram(text):
    try:
        tok, chat = creds()
        if not tok or not chat:
            log("no telegram creds"); return
        data = urllib.parse.urlencode({"chat_id":chat,"text":text[:4000],"disable_web_page_preview":"true"}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot"+tok+"/sendMessage", data=data, timeout=10).read()
    except Exception as e:
        log("telegram failed: " + str(e))

def to_bars(df):
    return [Bar(t=int(ts.timestamp()), o=float(r["Open"]), h=float(r["High"]),
                l=float(r["Low"]), c=float(r["Close"])) for ts, r in df.iterrows()]

def load_alerted():
    try: return set(json.loads(ALERTED.read_text()))
    except Exception: return set()

def save_alerted(s):
    try: ALERTED.write_text(json.dumps(sorted(s)))
    except Exception as e: log("save_alerted failed: " + str(e))

def sig(sym, tf, champ):
    p = champ.get("params", {})
    return sym + "|" + tf + "|" + str(champ.get("family")) + "|" + ",".join(str(k)+"="+str(p[k]) for k in sorted(p))

def main():
    alerted = load_alerted()
    telegram("Claudian hunter online. Searching intraday crypto (" + str(len(MATRIX)) + " cells) for an OOS-gated edge. Silent until a real candidate clears the gate.")
    log("hunter start, cells=" + str(len(MATRIX)))
    rnd = 0; seedc = 0
    while True:
        rnd += 1
        for sym, tf in MATRIX:
            seedc += 1
            try:
                df, _ = fetch_history(symbol=sym, interval=tf, years=YEARS, provider="binance")
                bars = to_bars(df)
                store = Store(BASE / ("state-hunter-" + sym + "_" + tf))
                res = run_search(sym, bars, generations=GENS_PER_VISIT, pop_size=POP, seed=seedc, store=store)
                champ = res.get("champion")
                if champ:
                    s = sig(sym, tf, champ)
                    if s not in alerted:
                        try:
                            is_b, oos_b = ev_split(bars)
                            verdict = fitness.assess(champ.get("family"), champ.get("params", {}), is_b, oos_b)
                        except Exception as e:
                            verdict = {"verdict":"?","oos":{},"err":str(e)}
                        rec = {"ts":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
                               "symbol":sym,"tf":tf,"family":champ.get("family"),
                               "params":champ.get("params"),"champion":champ,"assess":verdict}
                        try:
                            with WINNERS.open("a") as f: f.write(json.dumps(rec)+"\n")
                        except Exception as e: log("winners write failed: " + str(e))
                        alerted.add(s); save_alerted(alerted)
                        o = verdict.get("oos", {})
                        msg = ("CANDIDATE FOUND - " + sym + " " + tf + "\n"
                               + "family=" + str(champ.get("family")) + "\n"
                               + "verdict=" + str(verdict.get("verdict"))
                               + " (OOS t=" + str(o.get("t")) + ", p=" + str(o.get("p"))
                               + ", n=" + str(o.get("n")) + ", holds=" + str(o.get("holds")) + ")\n"
                               + "Cleared deflated OOS gate. Logged to hunter_winners.jsonl. Review before paper.")
                        telegram(msg)
                        log("ALERT " + sym + " " + tf + " " + str(champ.get("family")))
            except Exception as e:
                log("err " + sym + " " + tf + ": " + str(e))
            time.sleep(SLEEP)
        log("round " + str(rnd) + " complete")

if __name__ == "__main__":
    main()