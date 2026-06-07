import lzma, struct, urllib.request, urllib.error, time, sys, datetime as dt
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

SYM      = sys.argv[1]
START    = dt.date.fromisoformat(sys.argv[2])
END      = dt.date.fromisoformat(sys.argv[3])
INTERVAL = sys.argv[4] if len(sys.argv) > 4 else "5min"
OUT      = sys.argv[5] if len(sys.argv) > 5 else f"data_cache/{SYM}_5m_dukascopy.csv"
HMIN, HMAX = 12, 21
DIV = 1000.0
WORKERS = 12
CHUNK_DAYS = 10

def fetch_parse(task):
    d, h = task
    url = f"https://datafeed.dukascopy.com/datafeed/{SYM}/{d.year}/{d.month-1:02d}/{d.day:02d}/{h:02d}h_ticks.bi5"
    raw = None
    for _ in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=60).read(); break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return (d, [], "empty")
            time.sleep(1.0)
        except Exception:
            time.sleep(1.0)
    if raw is None:
        return (d, [], "fail")
    if not raw:
        return (d, [], "empty")
    try:
        data = lzma.decompress(raw)
    except Exception:
        return (d, [], "fail")
    base = dt.datetime(d.year, d.month, d.day, h, tzinfo=dt.timezone.utc)
    out = []
    for i in range(0, len(data), 20):
        ms, ask, bid, av, bv = struct.unpack(">IIIff", data[i:i+20])
        out.append((base + dt.timedelta(milliseconds=ms), (ask + bid) / 2.0 / DIV))
    return (d, out, "ok")

weekdays = []
d = START
while d <= END:
    if d.weekday() < 5:
        weekdays.append(d)
    d += dt.timedelta(days=1)

all_bars = []
ok = empty = fail = 0
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    for ci in range(0, len(weekdays), CHUNK_DAYS):
        chunk = weekdays[ci:ci+CHUNK_DAYS]
        tasks = [(dd, h) for dd in chunk for h in range(HMIN, HMAX + 1)]
        daybuf = {dd: [] for dd in chunk}
        for (dd, rows, status) in ex.map(fetch_parse, tasks):
            if status == "ok":
                ok += 1; daybuf[dd].extend(rows)
            elif status == "empty":
                empty += 1
            else:
                fail += 1
        for dd in chunk:
            rows = daybuf[dd]
            if rows:
                s = pd.DataFrame(rows, columns=["time", "price"]).set_index("time").sort_index()
                o = s["price"].resample(INTERVAL).ohlc().dropna()
                o["Volume"] = s["price"].resample(INTERVAL).count()
                o.columns = ["Open", "High", "Low", "Close", "Volume"]
                all_bars.append(o)
        print(f"  ...{chunk[-1]} ok={ok} empty={empty} fail={fail} bars={sum(len(b) for b in all_bars)}", flush=True)

if all_bars:
    df = pd.concat(all_bars)
    df.index.name = "time"
    df.to_csv(OUT)
    print("DONE bars:", len(df), "| range:", df.index[0], "->", df.index[-1])
    print("ok_hrs:", ok, "empty:", empty, "fail:", fail)
else:
    print("NO DATA. ok:", ok, "empty:", empty, "fail:", fail)
