# ICT Silver Bullet v4 — v3 + DISPLACEMENT-QUALITY filter on the FVG trigger.
# New param disp_mult: require the 3-candle FVG gap >= disp_mult * ATR(atr_period).
#   disp_mult = 0.0  -> behaviour IDENTICAL to v3 (any-size FVG). Clean A/B baseline.
#   disp_mult > 0.0  -> only "real displacement" FVGs qualify ("no displacement = no trade").
# Everything else (bias, premium/discount, killzone sweep, exits) unchanged from v3.
def build_signals(df, params):
    p = params or {}
    kz_start = p.get("kz_start", "10:00")
    kz_end   = p.get("kz_end", "11:00")
    ref_start= p.get("ref_start", "09:30")
    eod      = p.get("eod", "15:55")
    tz       = p.get("tz", "America/New_York")
    rr       = float(p.get("rr", 2.0))
    ema_period = int(p.get("ema_period", 20))
    pd_filter  = bool(int(p.get("pd_filter", 1)))
    disp_mult  = float(p.get("disp_mult", 0.0))   # NEW: displacement threshold in ATRs
    atr_period = int(p.get("atr_period", 14))      # NEW

    idx = df.index
    if idx.tz is None:
        idx_et = idx.tz_localize("UTC").tz_convert(tz)
    else:
        idx_et = idx.tz_convert(tz)

    times = list(idx_et.strftime("%H:%M"))
    dates = list(idx_et.strftime("%Y-%m-%d"))
    high  = list(df["High"].astype(float).values)
    low   = list(df["Low"].astype(float).values)
    close = list(df["Close"].astype(float).values)
    n = len(df)

    # ---- HTF daily bias + prior-day range, all shifted to prior completed day ----
    tmp = pd.DataFrame({"date": dates, "high": high, "low": low, "close": close})
    daily = tmp.groupby("date").agg(high=("high", "max"), low=("low", "min"), close=("close", "last")).sort_index()
    ema = daily["close"].ewm(span=ema_period, adjust=False).mean()
    prior_close = daily["close"].shift(1)
    prior_ema   = ema.shift(1)
    pdh = daily["high"].shift(1)
    pdl = daily["low"].shift(1)
    bias_map = {}
    pdh_map = {}
    pdl_map = {}
    for dk in list(daily.index):
        pc = prior_close.get(dk)
        pe = prior_ema.get(dk)
        if pd.isna(pc) or pd.isna(pe):
            bias_map[dk] = 0
        else:
            bias_map[dk] = 1 if pc > pe else -1
        ph = pdh.get(dk)
        pl = pdl.get(dk)
        pdh_map[dk] = None if pd.isna(ph) else float(ph)
        pdl_map[dk] = None if pd.isna(pl) else float(pl)

    # ---- ATR(atr_period) on the trading timeframe, for displacement sizing ----
    atr = [0.0] * n
    csum = 0.0
    for i in range(n):
        if i == 0:
            tr = high[i] - low[i]
        else:
            tr = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
        csum += tr
        if i >= atr_period:
            # subtract the TR that rolls out of the window
            if i - atr_period == 0:
                old = high[0] - low[0]
            else:
                j = i - atr_period
                old = max(high[j] - low[j], abs(high[j] - close[j-1]), abs(low[j] - close[j-1]))
            csum -= old
            atr[i] = csum / atr_period
        else:
            atr[i] = csum / (i + 1)

    bull_fvg = [False] * n
    bear_fvg = [False] * n
    for i in range(2, n):
        thr = disp_mult * atr[i] if disp_mult > 0 else 0.0
        if low[i] > high[i-2] and (low[i] - high[i-2]) >= thr:
            bull_fvg[i] = True
        if high[i] < low[i-2] and (low[i-2] - high[i]) >= thr:
            bear_fvg[i] = True

    pos = [0.0] * n
    cur_date = ""
    ref_hi = -1e18; ref_lo = 1e18
    day_hi = -1e18; day_lo = 1e18
    swept_high = False; swept_low = False
    entered = False
    in_pos = 0.0
    stop = 0.0; target = 0.0
    bias = 0; mid = None
    for i in range(n):
        d = dates[i]; t = times[i]
        if d != cur_date:
            cur_date = d
            ref_hi = -1e18; ref_lo = 1e18
            day_hi = -1e18; day_lo = 1e18
            swept_high = False; swept_low = False
            entered = False; in_pos = 0.0
            stop = 0.0; target = 0.0
            bias = bias_map.get(d, 0)
            ph = pdh_map.get(d); pl = pdl_map.get(d)
            mid = ((ph + pl) / 2.0) if (ph is not None and pl is not None) else None
        if high[i] > day_hi: day_hi = high[i]
        if low[i] < day_lo: day_lo = low[i]

        if in_pos > 0:
            if low[i] <= stop or high[i] >= target:
                in_pos = 0.0
        elif in_pos < 0:
            if high[i] >= stop or low[i] <= target:
                in_pos = 0.0

        if ref_start <= t < kz_start:
            if high[i] > ref_hi: ref_hi = high[i]
            if low[i] < ref_lo: ref_lo = low[i]

        if (kz_start <= t < kz_end) and (not entered) and (in_pos == 0.0) and (ref_hi > -1e17):
            if high[i] > ref_hi: swept_high = True
            if low[i] < ref_lo: swept_low = True
            entry = close[i]
            in_discount = (mid is None) or (entry < mid)
            in_premium  = (mid is None) or (entry > mid)
            if swept_high and bear_fvg[i] and bias < 0 and ((not pd_filter) or in_premium):
                stop = day_hi
                risk = stop - entry
                if risk > 0:
                    target = entry - rr * risk
                    in_pos = -1.0; entered = True
            elif swept_low and bull_fvg[i] and bias > 0 and ((not pd_filter) or in_discount):
                stop = day_lo
                risk = entry - stop
                if risk > 0:
                    target = entry + rr * risk
                    in_pos = 1.0; entered = True

        if t >= eod:
            in_pos = 0.0
        pos[i] = in_pos
    return pd.Series(pos, index=df.index)
