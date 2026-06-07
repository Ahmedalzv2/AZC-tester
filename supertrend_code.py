# SuperTrend (KivancOzbilgic) as a custom_python strategy.
# Position: +1 when SuperTrend trend is up, -1 when down (always-in reversal),
# or flat-when-down if long_only. Uses hl2 source + Wilder ATR (RMA).
# Decision on bar i uses only data through bar i (same convention as the SB code).
def build_signals(df, params):
    p = params or {}
    period = int(p.get("atr_period", 10))
    mult = float(p.get("multiplier", 3.0))
    long_only = bool(int(p.get("long_only", 0)))

    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    src = (high + low) / 2.0  # hl2

    prev_close = close.shift(1)
    tr = pd.concat([(high - low),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()  # Wilder/RMA

    s = src.values
    c = close.values
    a = atr.values
    n = len(df)

    up = [0.0] * n
    dn = [0.0] * n
    trend = [1] * n
    for i in range(n):
        basic_up = s[i] - mult * a[i]
        basic_dn = s[i] + mult * a[i]
        if i == 0:
            up[i] = basic_up
            dn[i] = basic_dn
            trend[i] = 1
            continue
        up[i] = max(basic_up, up[i-1]) if c[i-1] > up[i-1] else basic_up
        dn[i] = min(basic_dn, dn[i-1]) if c[i-1] < dn[i-1] else basic_dn
        t = trend[i-1]
        if t == -1 and c[i] > dn[i-1]:
            t = 1
        elif t == 1 and c[i] < up[i-1]:
            t = -1
        trend[i] = t

    pos = [0.0] * n
    for i in range(n):
        if trend[i] == 1:
            pos[i] = 1.0
        else:
            pos[i] = 0.0 if long_only else -1.0
    return pd.Series(pos, index=df.index)
