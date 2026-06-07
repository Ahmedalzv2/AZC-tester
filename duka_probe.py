import lzma, struct, urllib.request

# Dukascopy: month is 0-indexed in the path. Probe one liquid hour.
Y, M0, D, H = 2026, 4, 28, 15   # 2026-05-28 15:00 UTC (May = 04 zero-indexed)
candidates = ["USA100IDXUSD", "USATECHIDXUSD", "USTECHIDXUSD", "USA100.IDXUSD", "NASUSDUSD"]

def fetch(sym):
    url = f"https://datafeed.dukascopy.com/datafeed/{sym}/{Y}/{M0:02d}/{D:02d}/{H:02d}h_ticks.bi5"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        raw = urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        return url, f"HTTP-ERR {e}", None
    if not raw:
        return url, "EMPTY (0 bytes)", None
    try:
        data = lzma.decompress(raw)
    except Exception as e:
        return url, f"LZMA-ERR {e} (bytes={len(raw)})", None
    return url, f"OK compressed={len(raw)} decompressed={len(data)} records={len(data)//20}", data

for sym in candidates:
    url, status, data = fetch(sym)
    print(sym, "->", status)
    if data:
        recs = [struct.unpack(">IIIff", data[i:i+20]) for i in range(0, min(len(data), 20*5), 20)]
        for r in recs:
            ms, ask, bid, av, bv = r
            print(f"    ms={ms} ask_raw={ask} bid_raw={bid}  ->/1000 ask={ask/1000.0} /100 ask={ask/100.0}")
        print("    (NDX should be ~22000-30000; pick the divisor that matches)")
        break
