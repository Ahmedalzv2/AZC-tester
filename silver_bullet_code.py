# ICT Silver Bullet v3 — adds HTF bias filter (the missing ingredient).
# Bias = daily-EMA trend from PRIOR completed days (no lookahead).
#   long only when daily bias up; short only when daily bias down.
# Premium/discount (optional, pd_filter): long only in discount of prior-day
#   range, short only in premium. Entry trigger unchanged: killzone sweep + FVG.
# Exits: stop at swept extreme, rr-multiple target, EOD time-stop. 1 trade/day.
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

    bull_fvg = [False] * n
    bear_fvg = [False] * n
    for i in range(2, n):
        if low[i] > high[i-2]:
            bull_fvg[i] = True
        if high[i] < low[i-2]:
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
            # SHORT: bias down + buyside sweep + bearish FVG (+ premium)
            if swept_high and bear_fvg[i] and bias < 0 and ((not pd_filter) or in_premium):
                stop = day_hi
                risk = stop - entry
                if risk > 0:
                    target = entry - rr * risk
                    in_pos = -1.0; entered = True
            # LONG: bias up + sellside sweep + bullish FVG (+ discount)
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
