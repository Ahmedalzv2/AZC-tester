"""Forward significance tracker for the Alpaca NAV record (hard rule #1 clock)."""
import datetime as dt
import math

from execution.forward_significance import forward_report, nav_returns


def _rows(equities, mode="live-paper"):
    d0 = dt.date(2026, 1, 1)
    return [
        {"date": (d0 + dt.timedelta(days=i)).isoformat(), "mode": mode, "equity": e}
        for i, e in enumerate(equities)
    ]


def test_nav_returns_filters_dryrun_and_dedupes_by_date():
    rows = _rows([100_000, 101_000, 102_010])
    rows.insert(1, {"date": "2026-01-01", "mode": "dry-run", "equity": 50_000})
    # same-date rerun: keep the LAST row for that date
    rows.append({"date": "2026-01-03", "mode": "live-paper", "equity": 100_980})
    rets = nav_returns(rows)
    assert len(rets) == 2
    assert math.isclose(rets[0], 0.01, rel_tol=1e-9)
    assert math.isclose(rets[1], 100_980 / 101_000 - 1, rel_tol=1e-9)


def test_nav_returns_short_or_empty():
    assert nav_returns([]) == []
    assert nav_returns(_rows([100_000])) == []


def test_forward_report_steady_up():
    # 90 days of +0.1%/day, zero drawdown
    eq = [100_000 * (1.001 ** i) for i in range(91)]
    rep = forward_report(_rows(eq))
    assert rep["n_days"] == 90
    assert rep["hac_t"] > 2.0
    assert rep["sharpe_ann"] > 3.0
    assert rep["total_return_pct"] > 8.0
    assert rep["max_dd_pct"] == 0.0
    assert rep["years_to_t2"] is not None and rep["years_to_t2"] < 1.0


def test_forward_report_min_days_gate():
    # high t on a tiny sample must NOT read significant (the live-sig inflation lesson)
    eq = [100_000 * (1.002 ** i) for i in range(10)]
    rep = forward_report(_rows(eq))
    assert rep["n_days"] == 9
    assert rep["significant"] is False
    assert rep["hac_t"] > 2.0  # the t itself is high — the gate is what blocks it


def test_forward_report_bleeding_lane():
    eq = [100_000 * (0.999 ** i) for i in range(40)]
    rep = forward_report(_rows(eq))
    assert rep["hac_t"] < 0
    assert rep["years_to_t2"] is None
    assert rep["significant"] is False
    assert rep["max_dd_pct"] < -3.0


def test_forward_report_empty():
    rep = forward_report([])
    assert rep["n_days"] == 0
    assert rep["significant"] is False
    assert rep["years_to_t2"] is None
