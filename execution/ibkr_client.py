"""IBKR paper micro-futures client (ib_async → IB Gateway/IBeam socket).

Hard paper-guard: refuses to act unless the connected IB account is a paper
'DU…' account (see ibkr_futures.assert_paper_account). Dry-run is the default;
nothing is placed unless dry_run=False.

CONNECTION IS UNVERIFIED IN CI — it needs a running IB Gateway (or IBeam) paper
session on IBKR_HOST:IBKR_PORT. The pure planner (ibkr_futures) is unit-tested;
this socket layer is verified live the first time a session is up. Defaults:
host 127.0.0.1, port 4002 (IB Gateway paper), clientId 17.
"""
from __future__ import annotations

import os

from execution.ibkr_futures import CONTRACT_MAP, assert_paper_account

_MULT = {m["symbol"]: m for m in CONTRACT_MAP.values()}  # future sym -> {exchange, multiplier}


class IbkrPaper:
    def __init__(self, dry_run: bool = True, host: str | None = None,
                 port: int | None = None, client_id: int | None = None) -> None:
        self.dry_run = dry_run
        self.host = host or os.getenv("IBKR_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("IBKR_PORT", "4002"))
        self.client_id = int(client_id or os.getenv("IBKR_CLIENT_ID", "17"))
        self._ib = None
        self._account = ""
        self._con_cache: dict[str, object] = {}

    # --- connection -------------------------------------------------------
    def connect(self):
        from ib_async import IB
        ib = IB()
        ib.connect(self.host, self.port, clientId=self.client_id, timeout=15)
        ib.reqMarketDataType(3)  # delayed data — no live market-data subscription needed for paper
        accounts = ib.managedAccounts()
        if not accounts:
            ib.disconnect()
            raise RuntimeError("IB returned no managed accounts")
        self._account = accounts[0]
        assert_paper_account(self._account)   # refuse anything but DU… paper
        self._ib = ib
        return self

    def disconnect(self) -> None:
        if self._ib is not None:
            self._ib.disconnect()
            self._ib = None

    # --- contracts --------------------------------------------------------
    def _front_month(self, fut_sym: str):
        """Resolve the nearest-expiry contract for a micro future."""
        from ib_async import Future
        if fut_sym in self._con_cache:
            return self._con_cache[fut_sym]
        meta = _MULT[fut_sym]
        details = self._ib.reqContractDetails(
            Future(symbol=fut_sym, exchange=meta["exchange"], currency="USD"))
        if not details:
            raise RuntimeError(f"no contract details for {fut_sym}")
        # Soonest expiry wins (front month).
        nearest = min(details, key=lambda d: d.contract.lastTradeDateOrContractMonth)
        self._con_cache[fut_sym] = nearest.contract
        return nearest.contract

    # --- account state ----------------------------------------------------
    def equity(self) -> float:
        for v in self._ib.accountSummary(self._account):
            if v.tag == "NetLiquidation":
                return float(v.value)
        return 0.0

    def positions(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in self._ib.positions(self._account):
            sym = getattr(p.contract, "symbol", "")
            if sym in _MULT:
                out[sym] = int(out.get(sym, 0) + p.position)
        return out

    def prices(self, fut_syms: list[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for sym in fut_syms:
            try:
                con = self._front_month(sym)
                t = self._ib.reqMktData(con, "", False, False)
                self._ib.sleep(2)
                px = t.last if t.last == t.last else t.close   # NaN-check: last else close
                if px and px == px:
                    out[sym] = float(px)
            except Exception:  # noqa: BLE001 — a single unpriceable leg shouldn't blank the lane
                continue
        return out

    # --- orders -----------------------------------------------------------
    def submit(self, order: dict) -> str:
        sym, action, qty = order["symbol"], order["action"].upper(), int(order["contracts"])
        if self.dry_run:
            return f"DRY {action} {qty} {sym}"
        from ib_async import MarketOrder
        con = self._front_month(sym)
        trade = self._ib.placeOrder(con, MarketOrder(action, qty))
        self._ib.sleep(1)
        return f"{action} {qty} {sym} -> {trade.orderStatus.status}"
