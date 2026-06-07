import lzma, struct, urllib.request, time

sym = "USATECHIDXUSD"
# 2024-09-18 (Wed) several hours, UTC. Sept = 08 zero-indexed.
Y, M0, D = 2024, 8, 18
hours = [14, 15, 16]

def fetch(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return urllib.request.urlopen(req, timeout=60).read(), None
        except Exception as e:
            last = str(e)
            time.sleep(2)
    return None, last

for H in hours:
    url = f"https://datafeed.dukascopy.com/datafeed/{sym}/{Y}/{M0:02d}/{D:02d}/{H:02d}h_ticks.bi5"
    raw, err = fetch(url)
    if err:
        print(f"H{H}: ERR {err}")
        continue
    if not raw:
        print(f"H{H}: EMPTY")
        continue
    data = lzma.decompress(raw)
    nrec = len(data)//20
    print(f"H{H}: OK compressed={len(raw)} decompressed={len(data)} records={nrec}")
    for i in range(0, min(len(data), 20*4), 20):
        ms, ask, bid, av, bv = struct.unpack(">IIIff", data[i:i+20])
        print(f"    ms={ms} ask_raw={ask}  /1000={ask/1000.0}  /100={ask/100.0}  /10={ask/10.0}  vol(a={av:.2f},b={bv:.2f})")
    print("    NDX in 2024-09 was ~19500-20000; pick the divisor that matches.")
    break
